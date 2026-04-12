"""Tests for harness comparison reporter."""

import json

import pytest

from agent_platform.eval.harness_compare import (
    HarnessComparison,
    HarnessMetrics,
    _compute_metrics,
    compare_harnesses,
    load_dataset_categories,
)
from agent_platform.eval.runner import EvalConfig, EvalReport, TaskResult


def _build_report(with_categories: bool = True) -> tuple[EvalReport, dict[str, str]]:
    config = EvalConfig(
        name="harness_compare_test",
        dataset_path="eval/datasets/coding_tasks.jsonl",
        harnesses=["react", "plan_execute", "architect"],
    )
    results = [
        # React: strong on algorithms, weak on design
        TaskResult(task_id="algo_1", model="m1", harness="react",
                   scores={"test_pass": 0.9}, elapsed_seconds=2.0, cost_usd=0.01),
        TaskResult(task_id="algo_2", model="m1", harness="react",
                   scores={"test_pass": 0.85}, elapsed_seconds=1.8, cost_usd=0.01),
        TaskResult(task_id="design_1", model="m1", harness="react",
                   scores={"test_pass": 0.3}, elapsed_seconds=3.0, cost_usd=0.015),

        # Plan-execute: balanced
        TaskResult(task_id="algo_1", model="m1", harness="plan_execute",
                   scores={"test_pass": 0.7}, elapsed_seconds=4.0, cost_usd=0.02),
        TaskResult(task_id="algo_2", model="m1", harness="plan_execute",
                   scores={"test_pass": 0.75}, elapsed_seconds=3.5, cost_usd=0.02),
        TaskResult(task_id="design_1", model="m1", harness="plan_execute",
                   scores={"test_pass": 0.8}, elapsed_seconds=5.0, cost_usd=0.025),

        # Architect: strong on design
        TaskResult(task_id="algo_1", model="m1", harness="architect",
                   scores={"test_pass": 0.5}, elapsed_seconds=3.0, cost_usd=0.02),
        TaskResult(task_id="algo_2", model="m1", harness="architect",
                   scores={"test_pass": 0.6}, elapsed_seconds=2.8, cost_usd=0.02),
        TaskResult(task_id="design_1", model="m1", harness="architect",
                   scores={"test_pass": 0.95}, elapsed_seconds=6.0, cost_usd=0.03),
    ]
    report = EvalReport(config=config, results=results)

    categories = {}
    if with_categories:
        categories = {
            "algo_1": "algorithm",
            "algo_2": "algorithm",
            "design_1": "design",
        }
    return report, categories


class TestComputeMetrics:
    def test_basic_aggregation(self):
        results = [
            TaskResult(task_id="t1", model="m", harness="react",
                       scores={"s": 0.8}, elapsed_seconds=2.0, cost_usd=0.01),
            TaskResult(task_id="t2", model="m", harness="react",
                       scores={"s": 0.6}, elapsed_seconds=3.0, cost_usd=0.02),
        ]
        m = _compute_metrics("react", "general", results, pass_threshold=0.7)
        assert m.avg_score == pytest.approx(0.7, abs=0.01)
        assert m.pass_rate == 0.5  # only t1 passed
        assert m.mean_latency == pytest.approx(2.5)
        assert m.mean_cost == pytest.approx(0.015, abs=0.0001)
        assert m.n_samples == 2
        assert m.errors == 0

    def test_empty_results(self):
        m = _compute_metrics("react", "cat", [], pass_threshold=0.7)
        assert m.avg_score == 0.0
        assert m.n_samples == 0

    def test_counts_errors(self):
        results = [
            TaskResult(task_id="t1", model="m", harness="react",
                       scores={"s": 0.9}, elapsed_seconds=2.0),
            TaskResult(task_id="t2", model="m", harness="react",
                       scores={}, error="timeout"),
        ]
        m = _compute_metrics("react", "cat", results, pass_threshold=0.7)
        assert m.errors == 1
        assert m.n_samples == 1  # only non-error counted


class TestCompareHarnesses:
    def test_overall_winner_determined(self):
        report, cats = _build_report()
        comparison = compare_harnesses(report, task_categories=cats)

        assert comparison.dataset == "coding_tasks.jsonl"
        assert set(comparison.harnesses) == {"react", "plan_execute", "architect"}
        assert comparison.winner in comparison.harnesses

    def test_per_category_best(self):
        report, cats = _build_report()
        comparison = compare_harnesses(report, task_categories=cats)

        # React should win algorithms
        assert comparison.best_per_category["algorithm"] == "react"
        # Architect should win design
        assert comparison.best_per_category["design"] == "architect"

    def test_overall_metrics_match_harness_count(self):
        report, cats = _build_report()
        comparison = compare_harnesses(report, task_categories=cats)
        assert len(comparison.overall) == 3
        for m in comparison.overall:
            assert m.category == "ALL"
            assert m.n_samples == 3

    def test_without_categories_defaults_to_general(self):
        report, _ = _build_report()
        comparison = compare_harnesses(report)
        assert "general" in comparison.per_category

    def test_to_dict_structure(self):
        report, cats = _build_report()
        comparison = compare_harnesses(report, task_categories=cats)
        d = comparison.to_dict()
        assert "winner" in d
        assert "overall" in d
        assert "per_category" in d
        assert "algorithm" in d["per_category"]
        assert d["winner"] == comparison.winner

    def test_to_markdown_renders(self):
        report, cats = _build_report()
        comparison = compare_harnesses(report, task_categories=cats)
        md = comparison.to_markdown()
        assert "# Harness Comparison" in md
        assert "| Harness |" in md
        assert "react" in md
        assert "architect" in md
        assert "🏆" in md

    def test_save_json(self, tmp_path):
        report, cats = _build_report()
        comparison = compare_harnesses(report, task_categories=cats)
        path = str(tmp_path / "compare.json")
        comparison.save_json(path)
        data = json.loads((tmp_path / "compare.json").read_text())
        assert data["winner"] == comparison.winner

    def test_save_json_creates_parent_dirs(self, tmp_path):
        report, cats = _build_report()
        comparison = compare_harnesses(report, task_categories=cats)
        path = str(tmp_path / "nested" / "dir" / "compare.json")
        comparison.save_json(path)
        assert (tmp_path / "nested" / "dir" / "compare.json").exists()


class TestLoadDatasetCategories:
    def test_loads_from_jsonl(self, tmp_path):
        dataset = tmp_path / "tasks.jsonl"
        dataset.write_text(
            '{"task_id": "t1", "description": "x", "category": "bugfix"}\n'
            '{"task_id": "t2", "description": "y", "category": "algorithm"}\n'
            '{"task_id": "t3", "description": "z"}\n'
        )
        cats = load_dataset_categories(str(dataset))
        assert cats["t1"] == "bugfix"
        assert cats["t2"] == "algorithm"
        assert cats["t3"] == "general"  # default

    def test_missing_file(self):
        assert load_dataset_categories("/nonexistent.jsonl") == {}

    def test_malformed_file(self, tmp_path):
        dataset = tmp_path / "bad.jsonl"
        dataset.write_text("not json at all\n")
        assert load_dataset_categories(str(dataset)) == {}
