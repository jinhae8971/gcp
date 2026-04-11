"""Tests for evaluation report generators."""

import json

import pytest

from agent_platform.eval.reporters import (
    generate_html_dashboard,
    _build_score_matrix,
    _build_task_rows,
    _build_trend_data,
)
from agent_platform.eval.runner import EvalConfig, EvalReport, TaskResult


def _make_report(**overrides) -> EvalReport:
    config = EvalConfig(
        name=overrides.pop("name", "test_eval"),
        models=overrides.pop("models", ["model-a", "model-b"]),
        harnesses=overrides.pop("harnesses", ["react"]),
    )
    results = overrides.pop("results", [
        TaskResult(
            task_id="task_1", model="model-a", harness="react",
            scores={"exact_match": 1.0, "test_pass": 0.8},
            elapsed_seconds=2.5, cost_usd=0.01,
        ),
        TaskResult(
            task_id="task_2", model="model-a", harness="react",
            scores={"exact_match": 0.0, "test_pass": 0.0},
            elapsed_seconds=1.2, cost_usd=0.005, error="Timeout",
        ),
        TaskResult(
            task_id="task_1", model="model-b", harness="react",
            scores={"exact_match": 0.5, "test_pass": 0.6},
            elapsed_seconds=3.0, cost_usd=0.02,
        ),
    ])
    return EvalReport(
        config=config,
        results=results,
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:05:00Z",
    )


class TestBuildScoreMatrix:
    def test_groups_by_model_and_harness(self):
        results = [
            TaskResult(task_id="t1", model="m1", harness="react", scores={"s": 0.8}),
            TaskResult(task_id="t2", model="m1", harness="react", scores={"s": 0.6}),
            TaskResult(task_id="t1", model="m2", harness="react", scores={"s": 1.0}),
        ]
        matrix = _build_score_matrix(results)
        assert len(matrix) == 2
        m1_entry = next(m for m in matrix if m["model"] == "m1")
        assert m1_entry["avg_score"] == pytest.approx(0.7, abs=0.01)

    def test_skips_error_results(self):
        results = [
            TaskResult(task_id="t1", model="m1", harness="react", scores={"s": 0.8}),
            TaskResult(task_id="t2", model="m1", harness="react", scores={}, error="fail"),
        ]
        matrix = _build_score_matrix(results)
        assert len(matrix) == 1
        assert matrix[0]["count"] == 1


class TestBuildTaskRows:
    def test_generates_html_rows(self):
        results = [
            TaskResult(
                task_id="hello_world", model="test-model", harness="react",
                scores={"exact_match": 1.0}, elapsed_seconds=1.5, cost_usd=0.01,
            ),
        ]
        html = _build_task_rows(results)
        assert "<tr>" in html
        assert "hello_world" in html
        assert "1.00" in html

    def test_handles_error_results(self):
        results = [
            TaskResult(
                task_id="fail_task", model="test-model", harness="react",
                scores={}, elapsed_seconds=0.5, cost_usd=0.0, error="Connection timeout",
            ),
        ]
        html = _build_task_rows(results)
        assert "Connection timeout" in html
        assert 'class="error"' in html

    def test_score_css_classes(self):
        high = TaskResult(task_id="t1", model="m", harness="h", scores={"s": 0.9})
        mid = TaskResult(task_id="t2", model="m", harness="h", scores={"s": 0.5})
        low = TaskResult(task_id="t3", model="m", harness="h", scores={"s": 0.2})

        html = _build_task_rows([high, mid, low])
        assert 'class="high"' in html
        assert 'class="mid"' in html
        assert 'class="low"' in html


class TestBuildTrendData:
    def test_converts_history_to_json(self):
        history = [
            {
                "completed_at": "2026-01-01T00:00:00Z",
                "summary": {"average_score": 0.7, "pass_rate": 0.8, "total_cost_usd": 0.05},
            },
            {
                "completed_at": "2026-01-02T00:00:00Z",
                "summary": {"average_score": 0.85, "pass_rate": 0.9, "total_cost_usd": 0.04},
            },
        ]
        result = _build_trend_data(history)
        data = json.loads(result)
        assert len(data) == 2
        assert data[0]["date"] == "2026-01-01"
        assert data[1]["avg_score"] == 0.85

    def test_empty_history(self):
        result = _build_trend_data([])
        assert json.loads(result) == []


class TestGenerateHtmlDashboard:
    def test_generates_valid_html(self, tmp_path):
        report = _make_report()
        output_path = str(tmp_path / "dashboard.html")
        result = generate_html_dashboard(report, output_path=output_path)

        assert result == output_path
        content = (tmp_path / "dashboard.html").read_text()
        assert "<!DOCTYPE html>" in content
        assert "test_eval" in content
        assert "PASSED" in content or "FAILED" in content

    def test_includes_trend_data(self, tmp_path):
        report = _make_report()
        history = [
            {
                "completed_at": "2026-01-01T00:00:00Z",
                "summary": {"average_score": 0.7, "pass_rate": 0.8, "total_cost_usd": 0.05},
            },
        ]
        output_path = str(tmp_path / "dashboard.html")
        generate_html_dashboard(report, history=history, output_path=output_path)
        content = (tmp_path / "dashboard.html").read_text()
        assert "Score Over Time" in content

    def test_creates_parent_directories(self, tmp_path):
        report = _make_report()
        output_path = str(tmp_path / "nested" / "dir" / "dashboard.html")
        result = generate_html_dashboard(report, output_path=output_path)
        assert result == output_path
