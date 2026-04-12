"""Harness comparison reporter.

Produces a focused report comparing the performance of multiple harnesses
on the same dataset. Highlights per-category strengths and weaknesses so
teams can choose the right harness for each task type.

Input: an EvalReport (with multiple harnesses in config.harnesses)
Output: a structured comparison dict + optional markdown/HTML

Metrics computed per (harness, category):
  - average score
  - pass rate
  - mean latency
  - mean cost
  - sample size

Also computes an overall ranking across harnesses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_platform.eval.runner import EvalReport, TaskResult


@dataclass
class HarnessMetrics:
    """Aggregated metrics for one harness on one category (or overall)."""

    harness: str
    category: str = "ALL"
    avg_score: float = 0.0
    pass_rate: float = 0.0
    mean_latency: float = 0.0
    mean_cost: float = 0.0
    n_samples: int = 0
    errors: int = 0


@dataclass
class HarnessComparison:
    """Full comparison output."""

    dataset: str
    harnesses: list[str]
    overall: list[HarnessMetrics] = field(default_factory=list)
    per_category: dict[str, list[HarnessMetrics]] = field(default_factory=dict)
    winner: str = ""  # highest overall avg_score
    best_per_category: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "harnesses": self.harnesses,
            "winner": self.winner,
            "best_per_category": self.best_per_category,
            "overall": [_metrics_to_dict(m) for m in self.overall],
            "per_category": {
                cat: [_metrics_to_dict(m) for m in metrics]
                for cat, metrics in self.per_category.items()
            },
        }

    def save_json(self, path: str) -> str:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def to_markdown(self) -> str:
        """Render comparison as a markdown report."""
        lines: list[str] = [
            f"# Harness Comparison: {self.dataset}",
            "",
            f"**Harnesses compared**: {', '.join(self.harnesses)}",
            f"**Overall winner**: `{self.winner}`",
            "",
            "## Overall Results",
            "",
            "| Harness | Avg Score | Pass Rate | Mean Latency | Mean Cost | N | Errors |",
            "|---------|-----------|-----------|--------------|-----------|---|--------|",
        ]
        for m in self.overall:
            lines.append(
                f"| `{m.harness}` | {m.avg_score:.4f} | {m.pass_rate:.2%} "
                f"| {m.mean_latency:.2f}s | ${m.mean_cost:.4f} | {m.n_samples} | {m.errors} |"
            )

        lines.extend(["", "## Per-Category Results", ""])
        for category, metrics in sorted(self.per_category.items()):
            best = self.best_per_category.get(category, "")
            lines.append(f"### {category}  (best: `{best}`)")
            lines.append("")
            lines.append("| Harness | Score | Pass Rate | Latency | Cost | N |")
            lines.append("|---------|-------|-----------|---------|------|---|")
            for m in metrics:
                marker = " 🏆" if m.harness == best else ""
                lines.append(
                    f"| `{m.harness}`{marker} | {m.avg_score:.4f} | {m.pass_rate:.2%} "
                    f"| {m.mean_latency:.2f}s | ${m.mean_cost:.4f} | {m.n_samples} |"
                )
            lines.append("")

        return "\n".join(lines)


def _metrics_to_dict(m: HarnessMetrics) -> dict[str, Any]:
    return {
        "harness": m.harness,
        "category": m.category,
        "avg_score": round(m.avg_score, 4),
        "pass_rate": round(m.pass_rate, 4),
        "mean_latency": round(m.mean_latency, 2),
        "mean_cost": round(m.mean_cost, 4),
        "n_samples": m.n_samples,
        "errors": m.errors,
    }


def compare_harnesses(
    report: EvalReport,
    pass_threshold: float = 0.7,
    task_categories: dict[str, str] | None = None,
) -> HarnessComparison:
    """Analyze an EvalReport and produce a harness comparison.

    Args:
        report: The eval report to analyze (must contain multiple harnesses).
        pass_threshold: Score threshold for counting a task as "passed".
        task_categories: Optional mapping {task_id: category}. If not provided,
            all tasks are grouped under "general".
    """
    config = report.config
    categories = task_categories or {}

    # Group results: (harness, category) → list of TaskResult
    by_harness_cat: dict[tuple[str, str], list[TaskResult]] = {}
    by_harness: dict[str, list[TaskResult]] = {}

    for r in report.results:
        category = categories.get(r.task_id, "general")
        by_harness_cat.setdefault((r.harness, category), []).append(r)
        by_harness.setdefault(r.harness, []).append(r)

    # Overall metrics per harness
    overall: list[HarnessMetrics] = []
    for harness in config.harnesses:
        results = by_harness.get(harness, [])
        overall.append(_compute_metrics(harness, "ALL", results, pass_threshold))

    # Per-category metrics
    per_category: dict[str, list[HarnessMetrics]] = {}
    all_categories = {cat for (_, cat) in by_harness_cat.keys()}
    for category in sorted(all_categories):
        cat_metrics: list[HarnessMetrics] = []
        for harness in config.harnesses:
            results = by_harness_cat.get((harness, category), [])
            cat_metrics.append(_compute_metrics(harness, category, results, pass_threshold))
        per_category[category] = cat_metrics

    # Determine winners
    winner = ""
    if overall:
        winner = max(overall, key=lambda m: m.avg_score).harness

    best_per_category: dict[str, str] = {}
    for category, metrics in per_category.items():
        if metrics:
            best_per_category[category] = max(metrics, key=lambda m: m.avg_score).harness

    return HarnessComparison(
        dataset=config.dataset_path.split("/")[-1],
        harnesses=list(config.harnesses),
        overall=overall,
        per_category=per_category,
        winner=winner,
        best_per_category=best_per_category,
    )


def _compute_metrics(
    harness: str,
    category: str,
    results: list[TaskResult],
    pass_threshold: float,
) -> HarnessMetrics:
    """Aggregate a list of TaskResults into HarnessMetrics."""
    if not results:
        return HarnessMetrics(harness=harness, category=category)

    all_scores: list[float] = []
    passed = 0
    total_latency = 0.0
    total_cost = 0.0
    errors = 0

    for r in results:
        if r.error:
            errors += 1
            continue
        if r.scores:
            avg = sum(r.scores.values()) / len(r.scores)
            all_scores.append(avg)
            if avg >= pass_threshold:
                passed += 1
        total_latency += r.elapsed_seconds
        total_cost += r.cost_usd

    n = len(results)
    valid = len(all_scores)
    return HarnessMetrics(
        harness=harness,
        category=category,
        avg_score=sum(all_scores) / valid if valid else 0.0,
        pass_rate=passed / valid if valid else 0.0,
        mean_latency=total_latency / n if n else 0.0,
        mean_cost=total_cost / n if n else 0.0,
        n_samples=valid,
        errors=errors,
    )


def load_dataset_categories(dataset_path: str) -> dict[str, str]:
    """Extract {task_id: category} mapping from a JSONL dataset."""
    categories: dict[str, str] = {}
    try:
        with open(dataset_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                task_id = data.get("task_id")
                if task_id:
                    categories[task_id] = data.get("category", "general")
    except (OSError, json.JSONDecodeError):
        return {}
    return categories
