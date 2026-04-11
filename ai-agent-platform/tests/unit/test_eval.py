"""Tests for evaluation framework."""

import pytest

from agent_platform.eval.datasets import EvalTask
from agent_platform.eval.scorers import ScorerRegistry


@pytest.fixture
def scorer_registry() -> ScorerRegistry:
    return ScorerRegistry()


@pytest.mark.asyncio
async def test_exact_match_scorer(scorer_registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="test", expected_output="hello world")
    result = await scorer_registry.score("exact_match", task, "hello world")
    assert result.value == 1.0


@pytest.mark.asyncio
async def test_exact_match_scorer_fail(scorer_registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="test", expected_output="hello world")
    result = await scorer_registry.score("exact_match", task, "goodbye world")
    assert result.value == 0.0


@pytest.mark.asyncio
async def test_contains_scorer(scorer_registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="test", expected_output="function")
    result = await scorer_registry.score("contains", task, "def function(x): return x + 1")
    assert result.value == 1.0


@pytest.mark.asyncio
async def test_regex_scorer(scorer_registry: ScorerRegistry):
    task = EvalTask(
        task_id="t1", description="test",
        metadata={"regex_pattern": r"def \w+\(.*\):"},
    )
    result = await scorer_registry.score("regex_match", task, "def hello(name): pass")
    assert result.value == 1.0


@pytest.mark.asyncio
async def test_unknown_scorer(scorer_registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="test")
    result = await scorer_registry.score("nonexistent", task, "output")
    assert result.value == 0.0
    assert "Unknown" in result.reason
