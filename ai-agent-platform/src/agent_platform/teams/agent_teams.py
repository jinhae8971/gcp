"""Agent team coordinator using git worktrees for isolation.

Each agent gets a clean worktree branched from the team's base branch,
so their file modifications never collide. Failed agents can be
discarded without touching the main tree; successful ones can be
cherry-picked, merged, or promoted to PRs.

Why worktrees?
  - Single repo clone, many parallel working dirs
  - No slow re-clones; shared object database
  - Each branch is a real ref so `git log` works normally
  - Works locally and in CI identically

This module doesn't invoke git directly in tests. Instead it exposes a
GitRunner protocol that lets tests inject a fake. The default runner
shells out to `git`.
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol


class GitCommandError(RuntimeError):
    """Raised when a git command returns non-zero."""


class GitRunner(Protocol):
    async def run(self, args: list[str], cwd: str) -> str: ...


class ShellGitRunner:
    """Default runner — invokes `git` via subprocess."""

    async def run(self, args: list[str], cwd: str) -> str:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise GitCommandError(
                f"git {' '.join(shlex.quote(a) for a in args)} failed: "
                f"{stderr.decode(errors='replace').strip()}"
            )
        return stdout.decode(errors="replace")


@dataclass
class AgentWorktree:
    agent_id: str
    branch: str
    path: str
    base_branch: str
    active: bool = True
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "branch": self.branch,
            "path": self.path,
            "base_branch": self.base_branch,
            "active": self.active,
            "notes": list(self.notes),
        }


class AgentTeamCoordinator:
    """Coordinates a team of agents, each on its own worktree.

    Usage:
        coord = AgentTeamCoordinator(repo_root="/src/myproj", team_id="refactor-team")
        wt_alice = await coord.spawn(agent_id="alice", base_branch="main")
        wt_bob = await coord.spawn(agent_id="bob", base_branch="main")
        # ... run agents in each worktree ...
        await coord.finalize(wt_alice, keep=True)   # merge into integration branch
        await coord.finalize(wt_bob, keep=False)    # discard
    """

    def __init__(
        self,
        repo_root: str,
        team_id: str,
        worktree_parent: str | None = None,
        runner: GitRunner | None = None,
    ) -> None:
        self._repo_root = str(Path(repo_root).resolve())
        self._team_id = team_id
        self._worktree_parent = worktree_parent or str(
            Path(self._repo_root).parent / f".worktrees-{team_id}"
        )
        self._runner = runner or ShellGitRunner()
        self._worktrees: dict[str, AgentWorktree] = {}

    @property
    def team_id(self) -> str:
        return self._team_id

    @property
    def worktree_parent(self) -> str:
        return self._worktree_parent

    def list_worktrees(self) -> list[AgentWorktree]:
        return list(self._worktrees.values())

    async def spawn(self, agent_id: str, base_branch: str = "main") -> AgentWorktree:
        """Create an isolated worktree for one agent."""
        if agent_id in self._worktrees:
            raise ValueError(f"agent {agent_id!r} already has a worktree")

        branch = f"agent-team/{self._team_id}/{agent_id}"
        path = str(Path(self._worktree_parent) / agent_id)

        Path(self._worktree_parent).mkdir(parents=True, exist_ok=True)

        await self._runner.run(
            ["worktree", "add", "-b", branch, path, base_branch],
            cwd=self._repo_root,
        )

        wt = AgentWorktree(
            agent_id=agent_id,
            branch=branch,
            path=path,
            base_branch=base_branch,
        )
        self._worktrees[agent_id] = wt
        return wt

    async def commit_in_worktree(
        self, worktree: AgentWorktree, message: str
    ) -> None:
        """Stage all changes and create a commit inside the worktree."""
        await self._runner.run(["add", "-A"], cwd=worktree.path)
        await self._runner.run(
            ["commit", "-m", message, "--allow-empty"],
            cwd=worktree.path,
        )
        worktree.notes.append(f"commit: {message}")

    async def merge_back(
        self,
        worktree: AgentWorktree,
        target_branch: str,
        message: str | None = None,
    ) -> None:
        """Merge the worktree's branch into *target_branch* in the main repo."""
        await self._runner.run(["checkout", target_branch], cwd=self._repo_root)
        merge_msg = message or f"Merge {worktree.agent_id} from {self._team_id}"
        await self._runner.run(
            ["merge", "--no-ff", "-m", merge_msg, worktree.branch],
            cwd=self._repo_root,
        )
        worktree.notes.append(f"merged into {target_branch}")

    async def finalize(self, worktree: AgentWorktree, keep: bool) -> None:
        """Tear down an agent's worktree.

        When keep=False the branch is also deleted. When keep=True the branch
        is preserved so humans can review it later.
        """
        await self._runner.run(
            ["worktree", "remove", "--force", worktree.path],
            cwd=self._repo_root,
        )
        if not keep:
            try:
                await self._runner.run(
                    ["branch", "-D", worktree.branch],
                    cwd=self._repo_root,
                )
            except GitCommandError:
                pass  # Branch may have been merged already

        worktree.active = False
        self._worktrees.pop(worktree.agent_id, None)

    async def shutdown(self) -> None:
        """Force-remove every outstanding worktree. Use on cleanup."""
        for wt in list(self._worktrees.values()):
            try:
                await self.finalize(wt, keep=False)
            except Exception:
                pass
