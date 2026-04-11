"""Evaluation runner - execute benchmark suites and collect results.

Runs evaluation tasks against one or more model+harness combinations,
collects scores, and generates comparison reports. Designed to integrate
with CI/CD pipelines as a quality gate.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml

from agent_platform.eval.datasets import EvalDataset, EvalTask
from agent_platform.eval.scorers import ScorerRegistry, ScoreResult

logger = structlog.get_logger()


@dataclass
class EvalConfig:
    """Configuration for an evaluation run."""

    name: str = "default"
    dataset_path: str = "eval/datasets/sample_tasks.jsonl"
    models: list[str] = field(default_factory=lambda: ["claude-sonnet-4-20250514"])
    harnesses: list[str] = field(default_factory=lambda: ["react"])
    scorers: list[str] = field(default_factory=lambda: ["exact_match", "test_pass"])
    min_score_threshold: float = 0.7  # CI gate: fail if below this
    max_concurrent: int = 4
    timeout_per_task: int = 300

    @classmethod
    def from_yaml(cls, path: str) -> "EvalConfig":
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(**data)


@dataclass
class TaskResult:
    task_id: str
    model: str
    harness: str
    scores: dict[str, float] = field(default_factory=dict)
    output: str = ""
    elapsed_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None


@dataclass
class EvalReport:
    """Aggregated results from an evaluation run."""

    config: EvalConfig
    results: list[TaskResult] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""

    @property
    def average_score(self) -> float:
        all_scores = [s for r in self.results for s in r.scores.values() if r.error is None]
        return sum(all_scores) / len(all_scores) if all_scores else 0.0

    @property
    def pass_rate(self) -> float:
        passed = sum(
            1 for r in self.results
            if r.error is None and all(s >= self.config.min_score_threshold for s in r.scores.values())
        )
        total = len(self.results)
        return passed / total if total else 0.0

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.results)

    def passes_gate(self) -> bool:
        """Does this run pass the CI quality gate?"""
        return self.average_score >= self.config.min_score_threshold

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": {
                "name": self.config.name,
                "models": self.config.models,
                "harnesses": self.config.harnesses,
            },
            "summary": {
                "average_score": round(self.average_score, 4),
                "pass_rate": round(self.pass_rate, 4),
                "total_cost_usd": round(self.total_cost, 4),
                "total_tasks": len(self.results),
                "passes_gate": self.passes_gate(),
            },
            "results": [
                {
                    "task_id": r.task_id,
                    "model": r.model,
                    "harness": r.harness,
                    "scores": r.scores,
                    "elapsed_s": round(r.elapsed_seconds, 2),
                    "cost_usd": round(r.cost_usd, 4),
                    "error": r.error,
                }
                for r in self.results
            ],
        }

    def save(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        logger.info("eval.report_saved", path=path)


class EvalRunner:
    """Orchestrates evaluation runs."""

    def __init__(
        self,
        agent_factory: Any = None,  # Callable that creates configured agent sessions
        scorer_registry: ScorerRegistry | None = None,
    ) -> None:
        self._agent_factory = agent_factory
        self._scorers = scorer_registry or ScorerRegistry()

    async def run(self, config: EvalConfig) -> EvalReport:
        """Execute a full evaluation suite."""
        dataset = EvalDataset.load(config.dataset_path)
        report = EvalReport(config=config, started_at=_now_iso())

        logger.info(
            "eval.start",
            name=config.name,
            tasks=len(dataset.tasks),
            models=config.models,
            harnesses=config.harnesses,
        )

        # Generate all (task, model, harness) combinations
        combos = [
            (task, model, harness)
            for task in dataset.tasks
            for model in config.models
            for harness in config.harnesses
        ]

        # Run with concurrency limit
        semaphore = asyncio.Semaphore(config.max_concurrent)

        async def _run_one(task: EvalTask, model: str, harness: str) -> TaskResult:
            async with semaphore:
                return await self._run_task(task, model, harness, config)

        results = await asyncio.gather(
            *[_run_one(t, m, h) for t, m, h in combos],
            return_exceptions=True,
        )

        for combo, result in zip(combos, results):
            if isinstance(result, Exception):
                report.results.append(TaskResult(
                    task_id=combo[0].task_id, model=combo[1],
                    harness=combo[2], error=str(result),
                ))
            else:
                report.results.append(result)

        report.completed_at = _now_iso()
        logger.info(
            "eval.complete",
            average_score=report.average_score,
            pass_rate=report.pass_rate,
            passes_gate=report.passes_gate(),
        )
        return report

    async def _run_task(
        self, task: EvalTask, model: str, harness: str, config: EvalConfig
    ) -> TaskResult:
        """Run a single evaluation task."""
        t0 = time.monotonic()
        result = TaskResult(task_id=task.task_id, model=model, harness=harness)

        try:
            # TODO: Create agent session via factory and run the task
            # For now, this is a placeholder for the actual agent execution
            result.output = f"[placeholder] Task {task.task_id} with {model}/{harness}"
            result.elapsed_seconds = time.monotonic() - t0

            # Score the output
            for scorer_name in config.scorers:
                score = await self._scorers.score(scorer_name, task, result.output)
                result.scores[scorer_name] = score.value

        except Exception as exc:
            result.error = str(exc)
            result.elapsed_seconds = time.monotonic() - t0

        return result


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def cli_main() -> None:
    """CLI entry point for running evaluations."""
    import argparse

    parser = argparse.ArgumentParser(description="Agent Platform Evaluation Runner")
    parser.add_argument("--config", default="eval/configs/default_eval.yaml")
    parser.add_argument("--output", default="eval/results/latest.json")
    parser.add_argument("--ci-gate", action="store_true", help="Exit with code 1 if gate fails")
    args = parser.parse_args()

    config = EvalConfig.from_yaml(args.config)
    runner = EvalRunner()
    report = asyncio.run(runner.run(config))
    report.save(args.output)

    print(json.dumps(report.to_dict()["summary"], indent=2))

    if args.ci_gate and not report.passes_gate():
        print(f"\nCI GATE FAILED: average score {report.average_score:.4f} "
              f"< threshold {config.min_score_threshold}")
        raise SystemExit(1)
