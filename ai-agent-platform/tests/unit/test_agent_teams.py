"""Tests for agent team coordinator (worktree isolation)."""

from __future__ import annotations

import pytest

from agent_platform.teams.agent_teams import (
    AgentTeamCoordinator,
    GitCommandError,
    GitRunner,
)


class FakeGitRunner:
    """Records git invocations instead of running them."""

    def __init__(self, fail_on: list[str] | None = None) -> None:
        self.calls: list[tuple[list[str], str]] = []
        self.fail_on = fail_on or []

    async def run(self, args: list[str], cwd: str) -> str:
        self.calls.append((list(args), cwd))
        joined = " ".join(args)
        for trigger in self.fail_on:
            if trigger in joined:
                raise GitCommandError(f"fake failure for {trigger}")
        return ""


class TestAgentTeamCoordinator:
    @pytest.mark.asyncio
    async def test_spawn_creates_worktree(self, tmp_path):
        runner = FakeGitRunner()
        coord = AgentTeamCoordinator(
            repo_root=str(tmp_path),
            team_id="refactor",
            runner=runner,
        )
        wt = await coord.spawn("alice", base_branch="main")
        assert wt.agent_id == "alice"
        assert wt.branch == "agent-team/refactor/alice"
        assert "alice" in wt.path
        assert wt.base_branch == "main"

        # Worktree add call should be recorded
        add_call = next(c for c, _ in runner.calls if "worktree" in c)
        assert "add" in add_call
        assert "-b" in add_call

    @pytest.mark.asyncio
    async def test_duplicate_agent_raises(self, tmp_path):
        runner = FakeGitRunner()
        coord = AgentTeamCoordinator(
            repo_root=str(tmp_path), team_id="t", runner=runner
        )
        await coord.spawn("alice")
        with pytest.raises(ValueError, match="already"):
            await coord.spawn("alice")

    @pytest.mark.asyncio
    async def test_commit_and_merge(self, tmp_path):
        runner = FakeGitRunner()
        coord = AgentTeamCoordinator(
            repo_root=str(tmp_path), team_id="t", runner=runner
        )
        wt = await coord.spawn("alice")
        await coord.commit_in_worktree(wt, "WIP: refactor step 1")
        await coord.merge_back(wt, target_branch="develop")

        git_calls = [c[0] for c in runner.calls]
        assert ["add", "-A"] in git_calls
        assert any("commit" in c for c in git_calls)
        assert any("merge" in c and "--no-ff" in c for c in git_calls)
        assert "merged into develop" in wt.notes[-1]

    @pytest.mark.asyncio
    async def test_finalize_discard(self, tmp_path):
        runner = FakeGitRunner()
        coord = AgentTeamCoordinator(
            repo_root=str(tmp_path), team_id="t", runner=runner
        )
        wt = await coord.spawn("alice")
        await coord.finalize(wt, keep=False)

        git_calls = [c[0] for c in runner.calls]
        assert any("worktree" in c and "remove" in c for c in git_calls)
        assert any("branch" in c and "-D" in c for c in git_calls)
        assert wt.active is False
        assert coord.list_worktrees() == []

    @pytest.mark.asyncio
    async def test_finalize_keep_preserves_branch(self, tmp_path):
        runner = FakeGitRunner()
        coord = AgentTeamCoordinator(
            repo_root=str(tmp_path), team_id="t", runner=runner
        )
        wt = await coord.spawn("alice")
        await coord.finalize(wt, keep=True)

        git_calls = [c[0] for c in runner.calls]
        assert any("worktree" in c and "remove" in c for c in git_calls)
        # No branch -D when keeping
        assert not any("branch" in c and "-D" in c for c in git_calls)

    @pytest.mark.asyncio
    async def test_shutdown_removes_all(self, tmp_path):
        runner = FakeGitRunner()
        coord = AgentTeamCoordinator(
            repo_root=str(tmp_path), team_id="t", runner=runner
        )
        await coord.spawn("alice")
        await coord.spawn("bob")
        await coord.shutdown()
        assert coord.list_worktrees() == []

    @pytest.mark.asyncio
    async def test_finalize_discard_tolerates_branch_delete_failure(self, tmp_path):
        # Simulate the branch already being merged and deleted
        runner = FakeGitRunner(fail_on=["branch -D"])
        coord = AgentTeamCoordinator(
            repo_root=str(tmp_path), team_id="t", runner=runner
        )
        wt = await coord.spawn("alice")
        # Should not raise
        await coord.finalize(wt, keep=False)
        assert wt.active is False
