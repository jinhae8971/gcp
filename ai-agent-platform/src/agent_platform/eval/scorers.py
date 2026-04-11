"""Evaluation scorers - functions that grade agent outputs.

Scorer types:
  - Deterministic: exact match, regex match, test pass
  - LLM-as-judge: use a model to evaluate output quality
  - Custom: domain-specific scoring functions
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

from agent_platform.eval.datasets import EvalTask


@dataclass
class ScoreResult:
    """Result from a single scorer."""

    scorer_name: str
    value: float  # 0.0 to 1.0
    reason: str = ""
    metadata: dict[str, Any] | None = None


ScorerFunc = Callable[[EvalTask, str], Awaitable[ScoreResult]]


class ScorerRegistry:
    """Registry of scoring functions."""

    def __init__(self) -> None:
        self._scorers: dict[str, ScorerFunc] = {}
        self._register_builtins()

    def register(self, name: str, func: ScorerFunc) -> None:
        self._scorers[name] = func

    async def score(self, name: str, task: EvalTask, output: str) -> ScoreResult:
        scorer = self._scorers.get(name)
        if not scorer:
            return ScoreResult(scorer_name=name, value=0.0, reason=f"Unknown scorer: {name}")
        return await scorer(task, output)

    def _register_builtins(self) -> None:
        self.register("exact_match", _exact_match_scorer)
        self.register("contains", _contains_scorer)
        self.register("test_pass", _test_pass_scorer)
        self.register("regex_match", _regex_match_scorer)


async def _exact_match_scorer(task: EvalTask, output: str) -> ScoreResult:
    """Score 1.0 if output matches expected exactly (whitespace-normalized)."""
    if not task.expected_output:
        return ScoreResult(scorer_name="exact_match", value=0.5, reason="No expected output defined")
    expected = task.expected_output.strip()
    actual = output.strip()
    match = expected == actual
    return ScoreResult(
        scorer_name="exact_match",
        value=1.0 if match else 0.0,
        reason="Exact match" if match else "Output differs from expected",
    )


async def _contains_scorer(task: EvalTask, output: str) -> ScoreResult:
    """Score 1.0 if output contains the expected string."""
    if not task.expected_output:
        return ScoreResult(scorer_name="contains", value=0.5, reason="No expected output defined")
    found = task.expected_output.strip() in output
    return ScoreResult(
        scorer_name="contains",
        value=1.0 if found else 0.0,
        reason="Found expected content" if found else "Expected content not found",
    )


async def _regex_match_scorer(task: EvalTask, output: str) -> ScoreResult:
    """Score 1.0 if output matches the expected regex pattern."""
    pattern = task.metadata.get("regex_pattern", "")
    if not pattern:
        return ScoreResult(scorer_name="regex_match", value=0.5, reason="No regex pattern defined")
    match = bool(re.search(pattern, output, re.MULTILINE))
    return ScoreResult(
        scorer_name="regex_match",
        value=1.0 if match else 0.0,
        reason="Regex matched" if match else "Regex did not match",
    )


async def _test_pass_scorer(task: EvalTask, output: str) -> ScoreResult:
    """Score 1.0 if the test command exits with code 0."""
    if not task.test_command:
        return ScoreResult(scorer_name="test_pass", value=0.5, reason="No test command defined")

    proc = await asyncio.create_subprocess_shell(
        task.test_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    passed = proc.returncode == 0
    return ScoreResult(
        scorer_name="test_pass",
        value=1.0 if passed else 0.0,
        reason="Tests passed" if passed else f"Tests failed (exit {proc.returncode})",
    )
