"""Evaluation scorers - functions that grade agent outputs.

Scorer types:
  - Deterministic: exact match, regex match, test pass, code quality
  - LLM-as-judge: use a model to evaluate output quality on multiple dimensions
  - Custom: domain-specific scoring functions
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

import structlog

from agent_platform.eval.datasets import EvalTask

logger = structlog.get_logger()


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

    def list_scorers(self) -> list[str]:
        return list(self._scorers.keys())

    def _register_builtins(self) -> None:
        self.register("exact_match", _exact_match_scorer)
        self.register("contains", _contains_scorer)
        self.register("test_pass", _test_pass_scorer)
        self.register("regex_match", _regex_match_scorer)
        self.register("code_quality", _code_quality_scorer)


# ── Deterministic Scorers ─────────────────────────────────

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


async def _code_quality_scorer(task: EvalTask, output: str) -> ScoreResult:
    """Heuristic code quality checks: syntax validity, no obvious issues."""
    score = 1.0
    reasons: list[str] = []

    # Check if output contains Python code
    code_blocks = re.findall(r"```python\n(.*?)```", output, re.DOTALL)
    raw_code = code_blocks[0] if code_blocks else output

    # Syntax check
    try:
        compile(raw_code, "<eval>", "exec")
    except SyntaxError as e:
        score -= 0.4
        reasons.append(f"Syntax error: {e.msg}")

    # Basic quality heuristics
    if "TODO" in raw_code or "FIXME" in raw_code:
        score -= 0.1
        reasons.append("Contains TODO/FIXME")
    if "import *" in raw_code:
        score -= 0.1
        reasons.append("Uses wildcard import")
    if raw_code.count("\n") > 0 and not any(raw_code.strip().startswith(kw) for kw in ("def ", "class ", "import ", "from ", "#")):
        pass  # not necessarily code
    if "except:" in raw_code and "except Exception" not in raw_code:
        score -= 0.1
        reasons.append("Bare except clause")

    score = max(0.0, score)
    return ScoreResult(
        scorer_name="code_quality",
        value=round(score, 2),
        reason="; ".join(reasons) if reasons else "Code quality checks passed",
    )


# ── LLM-as-Judge Scorer ──────────────────────────────────

LLM_JUDGE_PROMPT = """\
You are an expert code reviewer evaluating an AI coding agent's output.

## Task Given to the Agent
{task_description}

## Agent's Output
{agent_output}

## Evaluation Criteria
Rate the output on each dimension from 0.0 to 1.0:

1. **correctness**: Does the code solve the task correctly?
2. **completeness**: Does it handle edge cases and cover all requirements?
3. **code_quality**: Is the code clean, readable, and well-structured?
4. **efficiency**: Is the solution reasonably efficient?

## Response Format
Return ONLY a JSON object (no markdown, no explanation):
{{"correctness": 0.0, "completeness": 0.0, "code_quality": 0.0, "efficiency": 0.0, "overall": 0.0, "reason": "brief explanation"}}
"""


def create_llm_judge_scorer(
    gateway: Any,
    judge_model: str = "claude-sonnet-4-20250514",
) -> ScorerFunc:
    """Factory that creates an LLM-as-Judge scorer using the model gateway.

    Usage:
        scorer = create_llm_judge_scorer(gateway, "claude-sonnet-4-20250514")
        registry.register("llm_judge", scorer)
    """

    async def _llm_judge(task: EvalTask, output: str) -> ScoreResult:
        prompt = LLM_JUDGE_PROMPT.format(
            task_description=task.description,
            agent_output=output[:8000],  # Truncate to avoid huge prompts
        )

        try:
            response = await gateway.chat(
                model=judge_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=512,
            )

            # Parse the JSON response
            text = response.text.strip()
            # Handle potential markdown wrapping
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()

            scores = json.loads(text)
            overall = scores.get("overall", 0.0)

            # Validate range
            overall = max(0.0, min(1.0, float(overall)))

            return ScoreResult(
                scorer_name="llm_judge",
                value=overall,
                reason=scores.get("reason", ""),
                metadata={
                    "correctness": scores.get("correctness", 0.0),
                    "completeness": scores.get("completeness", 0.0),
                    "code_quality": scores.get("code_quality", 0.0),
                    "efficiency": scores.get("efficiency", 0.0),
                    "judge_model": judge_model,
                    "judge_cost_usd": response.usage.cost_usd,
                },
            )

        except json.JSONDecodeError:
            logger.warning("llm_judge.parse_error", model=judge_model)
            return ScoreResult(
                scorer_name="llm_judge",
                value=0.5,
                reason="Failed to parse judge response as JSON",
            )
        except Exception as exc:
            logger.error("llm_judge.error", error=str(exc))
            return ScoreResult(
                scorer_name="llm_judge",
                value=0.0,
                reason=f"Judge error: {exc}",
            )

    return _llm_judge


# ── Pairwise Comparison Scorer ────────────────────────────

PAIRWISE_PROMPT = """\
You are comparing two AI coding agent outputs for the same task.

## Task
{task_description}

## Output A ({model_a})
{output_a}

## Output B ({model_b})
{output_b}

## Instructions
Compare the two outputs. Which is better overall?
Return ONLY a JSON object:
{{"winner": "A" or "B" or "tie", "reason": "brief explanation", "confidence": 0.0 to 1.0}}
"""


def create_pairwise_scorer(
    gateway: Any,
    judge_model: str = "claude-sonnet-4-20250514",
) -> Callable:
    """Factory for pairwise A/B comparison between two model outputs.

    Returns a callable that takes (task, output_a, model_a, output_b, model_b)
    and returns comparison results.
    """

    async def _compare(
        task: EvalTask,
        output_a: str, model_a: str,
        output_b: str, model_b: str,
    ) -> dict[str, Any]:
        prompt = PAIRWISE_PROMPT.format(
            task_description=task.description,
            output_a=output_a[:6000],
            model_a=model_a,
            output_b=output_b[:6000],
            model_b=model_b,
        )

        try:
            response = await gateway.chat(
                model=judge_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=256,
            )
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            result = json.loads(text)
            result["judge_model"] = judge_model
            result["judge_cost_usd"] = response.usage.cost_usd
            return result
        except Exception as exc:
            return {"winner": "tie", "reason": f"Error: {exc}", "confidence": 0.0}

    return _compare
