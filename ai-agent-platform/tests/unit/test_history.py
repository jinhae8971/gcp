"""Tests for evaluation history management."""

import json

import pytest

from agent_platform.eval.history import EvalHistory
from agent_platform.eval.runner import EvalConfig, EvalReport, TaskResult


def _make_report(name: str = "test", avg: float = 0.8, tasks: int = 3) -> EvalReport:
    config = EvalConfig(name=name)
    results = [
        TaskResult(
            task_id=f"task_{i}",
            model="test-model",
            harness="react",
            scores={"exact_match": avg, "test_pass": avg},
            elapsed_seconds=1.0 + i,
            cost_usd=0.01,
        )
        for i in range(tasks)
    ]
    return EvalReport(
        config=config,
        results=results,
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:01:00Z",
    )


class TestEvalHistory:
    def test_save_and_list(self, tmp_path):
        history = EvalHistory(history_dir=str(tmp_path))
        report = _make_report()
        path = history.save(report)

        assert path.endswith(".json")
        runs = history.list_runs()
        assert len(runs) == 1
        assert runs[0]["name"] == "test"
        assert "average_score" in runs[0]["summary"]

    def test_list_with_name_filter(self, tmp_path):
        history = EvalHistory(history_dir=str(tmp_path))
        history.save(_make_report(name="alpha"))
        history.save(_make_report(name="beta"))

        alpha_runs = history.list_runs(name_filter="alpha")
        assert len(alpha_runs) == 1
        assert alpha_runs[0]["name"] == "alpha"

    def test_load_run(self, tmp_path):
        history = EvalHistory(history_dir=str(tmp_path))
        path = history.save(_make_report())
        filename = path.split("/")[-1]

        data = history.load_run(filename)
        assert data is not None
        assert "summary" in data
        assert data["summary"]["total_tasks"] == 3

    def test_load_run_nonexistent(self, tmp_path):
        history = EvalHistory(history_dir=str(tmp_path))
        assert history.load_run("nonexistent.json") is None

    def test_get_trend(self, tmp_path):
        history = EvalHistory(history_dir=str(tmp_path))
        for i in range(5):
            history.save(_make_report(avg=0.5 + i * 0.1))

        trend = history.get_trend(limit=10)
        assert len(trend) == 5
        # Trend should be oldest-first
        # All have the same name so all should appear

    def test_compare_last_two(self, tmp_path):
        history = EvalHistory(history_dir=str(tmp_path))

        # Only one run - should return None
        history.save(_make_report(avg=0.7))
        assert history.compare_last_two() is None

        # Second run
        history.save(_make_report(avg=0.8))
        comparison = history.compare_last_two()
        assert comparison is not None
        assert "score_delta" in comparison
        assert "regression" in comparison

    def test_compare_detects_regression(self, tmp_path):
        history = EvalHistory(history_dir=str(tmp_path))
        history.save(_make_report(avg=0.9))

        import time
        time.sleep(0.01)  # Ensure different timestamp

        history.save(_make_report(avg=0.5))  # Big drop
        comparison = history.compare_last_two()
        assert comparison is not None
        assert comparison["score_delta"] < 0

    def test_cleanup_old(self, tmp_path):
        history = EvalHistory(history_dir=str(tmp_path))
        for i in range(10):
            history.save(_make_report())

        removed = history.cleanup_old(keep=3)
        assert removed == 7
        remaining = history.list_runs()
        assert len(remaining) == 3

    def test_cleanup_noop_when_few(self, tmp_path):
        history = EvalHistory(history_dir=str(tmp_path))
        history.save(_make_report())
        removed = history.cleanup_old(keep=10)
        assert removed == 0
