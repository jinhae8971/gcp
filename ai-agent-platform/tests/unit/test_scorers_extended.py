"""Extended tests for Phase 2 scorers: code_quality, LLM-as-Judge factory, pairwise factory."""

import pytest

from agent_platform.eval.datasets import EvalTask
from agent_platform.eval.scorers import ScorerRegistry


@pytest.fixture
def registry() -> ScorerRegistry:
    return ScorerRegistry()


# ── code_quality scorer ──────────────────────────────────

@pytest.mark.asyncio
async def test_code_quality_valid_python(registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="Write a function")
    output = "def hello(name):\n    return f'Hello, {name}!'\n"
    result = await registry.score("code_quality", task, output)
    assert result.value == 1.0
    assert "passed" in result.reason.lower()


@pytest.mark.asyncio
async def test_code_quality_syntax_error(registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="Write a function")
    output = "def hello(name\n    return name"
    result = await registry.score("code_quality", task, output)
    assert result.value < 1.0
    assert "syntax" in result.reason.lower()


@pytest.mark.asyncio
async def test_code_quality_wildcard_import(registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="Write code")
    output = "from os import *\ndef foo(): pass\n"
    result = await registry.score("code_quality", task, output)
    assert result.value < 1.0
    assert "wildcard" in result.reason.lower()


@pytest.mark.asyncio
async def test_code_quality_bare_except(registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="Write code")
    output = "try:\n    x = 1\nexcept:\n    pass\n"
    result = await registry.score("code_quality", task, output)
    assert result.value < 1.0
    assert "except" in result.reason.lower()


@pytest.mark.asyncio
async def test_code_quality_todo(registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="Write code")
    output = "def foo():\n    # TODO: implement\n    pass\n"
    result = await registry.score("code_quality", task, output)
    assert result.value < 1.0
    assert "TODO" in result.reason


@pytest.mark.asyncio
async def test_code_quality_code_block(registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="Write a function")
    output = "Here is the solution:\n```python\ndef add(a, b):\n    return a + b\n```\n"
    result = await registry.score("code_quality", task, output)
    assert result.value == 1.0


# ── Scorer listing ──────────────────────────────────────

def test_list_scorers(registry: ScorerRegistry):
    scorers = registry.list_scorers()
    assert "exact_match" in scorers
    assert "contains" in scorers
    assert "regex_match" in scorers
    assert "test_pass" in scorers
    assert "code_quality" in scorers


# ── Edge cases ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_exact_match_whitespace_normalized(registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="test", expected_output="hello")
    result = await registry.score("exact_match", task, "  hello  ")
    assert result.value == 1.0


@pytest.mark.asyncio
async def test_exact_match_no_expected(registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="test")
    result = await registry.score("exact_match", task, "anything")
    assert result.value == 0.5
    assert "No expected" in result.reason


@pytest.mark.asyncio
async def test_contains_no_expected(registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="test")
    result = await registry.score("contains", task, "anything")
    assert result.value == 0.5


@pytest.mark.asyncio
async def test_regex_no_pattern(registry: ScorerRegistry):
    task = EvalTask(task_id="t1", description="test", metadata={})
    result = await registry.score("regex_match", task, "anything")
    assert result.value == 0.5
    assert "No regex" in result.reason


# ── LLM-as-Judge / Pairwise factory tests ───────────────
# These test the factory signatures without calling real LLMs

def test_create_llm_judge_scorer_returns_callable():
    from agent_platform.eval.scorers import create_llm_judge_scorer

    class FakeGateway:
        pass

    scorer = create_llm_judge_scorer(FakeGateway())
    assert callable(scorer)


def test_create_pairwise_scorer_returns_callable():
    from agent_platform.eval.scorers import create_pairwise_scorer

    class FakeGateway:
        pass

    scorer = create_pairwise_scorer(FakeGateway())
    assert callable(scorer)
