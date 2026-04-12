"""Agent Teams: multi-agent collaboration primitives (Phase 5).

An "agent team" is a group of independent agent sessions working on the
same overall goal, each isolated on its own git worktree so their file
changes don't conflict. A coordinator merges successful worktrees back.
"""
