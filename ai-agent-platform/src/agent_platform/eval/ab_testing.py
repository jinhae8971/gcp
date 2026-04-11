"""Prompt A/B testing framework.

Compares two prompt variants (or harness configs) against the same
task set and determines which performs better with statistical rigor.

Usage:
    experiment = ABExperiment(
        name="system_prompt_v2_test",
        variant_a=VariantConfig(prompt_name="default_system", prompt_version=1),
        variant_b=VariantConfig(prompt_name="default_system", prompt_version=2),
        dataset_path="eval/datasets/sample_tasks.jsonl",
        model="claude-sonnet-4-20250514",
    )
    result = await ab_runner.run(experiment)
    print(result.winner, result.confidence)
"""

from __future__ import annotations

import asyncio
import math
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from agent_platform.eval.datasets import EvalDataset, EvalTask
from agent_platform.eval.scorers import ScorerRegistry, ScoreResult

logger = structlog.get_logger()


@dataclass
class VariantConfig:
    """Configuration for one variant in an A/B test."""

    name: str = "A"
    prompt_name: str = ""
    prompt_version: int | None = None
    harness_id: str = "react"
    system_prompt_override: str = ""
    temperature: float = 0.0


@dataclass
class ABExperiment:
    """Definition of an A/B test experiment."""

    name: str
    variant_a: VariantConfig
    variant_b: VariantConfig
    dataset_path: str = "eval/datasets/sample_tasks.jsonl"
    model: str = "claude-sonnet-4-20250514"
    scorers: list[str] = field(default_factory=lambda: ["exact_match", "test_pass"])
    num_runs: int = 1  # Repeat each task N times to reduce variance
    max_concurrent: int = 4


@dataclass
class VariantResult:
    """Aggregated scores for one variant."""

    variant_name: str
    scores: list[float] = field(default_factory=list)
    total_cost: float = 0.0
    total_latency: float = 0.0
    per_task: list[dict[str, Any]] = field(default_factory=list)

    @property
    def mean_score(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0

    @property
    def std_score(self) -> float:
        if len(self.scores) < 2:
            return 0.0
        mean = self.mean_score
        variance = sum((s - mean) ** 2 for s in self.scores) / (len(self.scores) - 1)
        return math.sqrt(variance)

    @property
    def mean_latency(self) -> float:
        n = len(self.per_task)
        return self.total_latency / n if n else 0.0


@dataclass
class ABResult:
    """Complete result of an A/B experiment."""

    experiment_name: str
    variant_a: VariantResult
    variant_b: VariantResult
    winner: str = ""  # "A", "B", or "tie"
    confidence: float = 0.0  # p-value based confidence
    score_delta: float = 0.0
    cost_delta: float = 0.0
    latency_delta: float = 0.0
    completed_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment_name,
            "winner": self.winner,
            "confidence": round(self.confidence, 4),
            "variant_a": {
                "name": self.variant_a.variant_name,
                "mean_score": round(self.variant_a.mean_score, 4),
                "std_score": round(self.variant_a.std_score, 4),
                "total_cost": round(self.variant_a.total_cost, 4),
                "mean_latency_s": round(self.variant_a.mean_latency, 2),
                "n_samples": len(self.variant_a.scores),
            },
            "variant_b": {
                "name": self.variant_b.variant_name,
                "mean_score": round(self.variant_b.mean_score, 4),
                "std_score": round(self.variant_b.std_score, 4),
                "total_cost": round(self.variant_b.total_cost, 4),
                "mean_latency_s": round(self.variant_b.mean_latency, 2),
                "n_samples": len(self.variant_b.scores),
            },
            "deltas": {
                "score": round(self.score_delta, 4),
                "cost_usd": round(self.cost_delta, 4),
                "latency_s": round(self.latency_delta, 2),
            },
            "completed_at": self.completed_at,
        }

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


class ABRunner:
    """Executes A/B experiments."""

    def __init__(
        self,
        scorer_registry: ScorerRegistry | None = None,
        agent_runner: Any = None,
    ) -> None:
        self._scorers = scorer_registry or ScorerRegistry()
        self._agent_runner = agent_runner

    async def run(self, experiment: ABExperiment) -> ABResult:
        """Run a complete A/B experiment."""
        dataset = EvalDataset.load(experiment.dataset_path)
        logger.info("ab_test.start", name=experiment.name, tasks=len(dataset.tasks))

        semaphore = asyncio.Semaphore(experiment.max_concurrent)
        variant_a = VariantResult(variant_name=experiment.variant_a.name)
        variant_b = VariantResult(variant_name=experiment.variant_b.name)

        async def run_variant(task: EvalTask, variant: VariantConfig) -> dict[str, Any]:
            async with semaphore:
                return await self._run_single(task, variant, experiment)

        # Run both variants for each task
        tasks_a = [run_variant(t, experiment.variant_a) for t in dataset.tasks for _ in range(experiment.num_runs)]
        tasks_b = [run_variant(t, experiment.variant_b) for t in dataset.tasks for _ in range(experiment.num_runs)]

        results_a = await asyncio.gather(*tasks_a, return_exceptions=True)
        results_b = await asyncio.gather(*tasks_b, return_exceptions=True)

        for r in results_a:
            if isinstance(r, Exception):
                variant_a.scores.append(0.0)
            else:
                variant_a.scores.append(r.get("avg_score", 0.0))
                variant_a.total_cost += r.get("cost", 0.0)
                variant_a.total_latency += r.get("elapsed", 0.0)
                variant_a.per_task.append(r)

        for r in results_b:
            if isinstance(r, Exception):
                variant_b.scores.append(0.0)
            else:
                variant_b.scores.append(r.get("avg_score", 0.0))
                variant_b.total_cost += r.get("cost", 0.0)
                variant_b.total_latency += r.get("elapsed", 0.0)
                variant_b.per_task.append(r)

        # Statistical comparison
        winner, confidence = _welch_t_test(variant_a.scores, variant_b.scores)

        result = ABResult(
            experiment_name=experiment.name,
            variant_a=variant_a,
            variant_b=variant_b,
            winner=winner,
            confidence=confidence,
            score_delta=variant_b.mean_score - variant_a.mean_score,
            cost_delta=variant_b.total_cost - variant_a.total_cost,
            latency_delta=variant_b.mean_latency - variant_a.mean_latency,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )

        logger.info(
            "ab_test.complete",
            winner=winner,
            confidence=f"{confidence:.2%}",
            a_score=f"{variant_a.mean_score:.4f}",
            b_score=f"{variant_b.mean_score:.4f}",
        )
        return result

    async def _run_single(
        self, task: EvalTask, variant: VariantConfig, experiment: ABExperiment,
    ) -> dict[str, Any]:
        """Run a single task with a specific variant. Placeholder for actual agent execution."""
        import time
        t0 = time.monotonic()

        # TODO: Replace with actual agent execution using variant config
        output = f"[placeholder] {task.task_id} with {variant.name}"

        scores: dict[str, float] = {}
        for scorer_name in experiment.scorers:
            score = await self._scorers.score(scorer_name, task, output)
            scores[scorer_name] = score.value

        elapsed = time.monotonic() - t0
        avg_score = sum(scores.values()) / len(scores) if scores else 0.0

        return {
            "task_id": task.task_id,
            "variant": variant.name,
            "scores": scores,
            "avg_score": avg_score,
            "elapsed": elapsed,
            "cost": 0.0,
        }


def _welch_t_test(a: list[float], b: list[float]) -> tuple[str, float]:
    """Welch's t-test for unequal variances. Returns (winner, confidence)."""
    n_a, n_b = len(a), len(b)
    if n_a < 2 or n_b < 2:
        return "tie", 0.0

    mean_a = sum(a) / n_a
    mean_b = sum(b) / n_b
    var_a = sum((x - mean_a) ** 2 for x in a) / (n_a - 1)
    var_b = sum((x - mean_b) ** 2 for x in b) / (n_b - 1)

    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se < 1e-10:
        return "tie", 1.0 if abs(mean_a - mean_b) < 1e-10 else 0.0

    t_stat = (mean_b - mean_a) / se

    # Welch-Satterthwaite degrees of freedom
    num = (var_a / n_a + var_b / n_b) ** 2
    denom = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
    df = num / denom if denom > 0 else 1

    # Approximate p-value using normal distribution (good for df > 30)
    # For smaller df, this is an approximation
    p_value = 2 * (1 - _normal_cdf(abs(t_stat)))

    confidence = 1 - p_value
    if confidence < 0.95:
        winner = "tie"
    elif mean_b > mean_a:
        winner = "B"
    else:
        winner = "A"

    return winner, confidence


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF using Abramowitz & Stegun formula."""
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    p = 0.3275911
    sign = 1 if x >= 0 else -1
    x = abs(x) / math.sqrt(2)
    t = 1.0 / (1.0 + p * x)
    y = 1.0 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * math.exp(-x * x)
    return 0.5 * (1.0 + sign * y)
