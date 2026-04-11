"""Tests for A/B testing framework."""

import math

import pytest

from agent_platform.eval.ab_testing import (
    ABExperiment,
    ABResult,
    ABRunner,
    VariantConfig,
    VariantResult,
    _normal_cdf,
    _welch_t_test,
)


class TestVariantResult:
    def test_mean_score(self):
        vr = VariantResult(variant_name="A", scores=[0.6, 0.8, 1.0])
        assert vr.mean_score == pytest.approx(0.8, abs=0.001)

    def test_mean_score_empty(self):
        vr = VariantResult(variant_name="A")
        assert vr.mean_score == 0.0

    def test_std_score(self):
        vr = VariantResult(variant_name="A", scores=[0.5, 0.5, 0.5])
        assert vr.std_score == 0.0

    def test_std_score_single(self):
        vr = VariantResult(variant_name="A", scores=[0.8])
        assert vr.std_score == 0.0

    def test_std_score_nonzero(self):
        vr = VariantResult(variant_name="A", scores=[0.0, 1.0])
        # sample std of [0, 1] = sqrt(0.5) ≈ 0.707
        assert vr.std_score == pytest.approx(math.sqrt(0.5), abs=0.01)

    def test_mean_latency(self):
        vr = VariantResult(
            variant_name="A",
            total_latency=10.0,
            per_task=[{}, {}, {}, {}, {}],
        )
        assert vr.mean_latency == pytest.approx(2.0)

    def test_mean_latency_empty(self):
        vr = VariantResult(variant_name="A")
        assert vr.mean_latency == 0.0


class TestWelchTTest:
    def test_identical_samples(self):
        a = [0.8, 0.8, 0.8, 0.8]
        b = [0.8, 0.8, 0.8, 0.8]
        winner, confidence = _welch_t_test(a, b)
        assert winner == "tie"

    def test_clearly_different(self):
        a = [0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2]
        b = [0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9]
        winner, confidence = _welch_t_test(a, b)
        assert winner == "B"
        assert confidence > 0.95

    def test_a_wins(self):
        a = [0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9]
        b = [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1]
        winner, confidence = _welch_t_test(a, b)
        assert winner == "A"
        assert confidence > 0.95

    def test_too_few_samples(self):
        winner, confidence = _welch_t_test([0.5], [0.9])
        assert winner == "tie"
        assert confidence == 0.0

    def test_mixed_results_tie(self):
        # Overlapping distributions - not enough signal
        a = [0.5, 0.6, 0.7, 0.4]
        b = [0.6, 0.5, 0.8, 0.3]
        winner, _ = _welch_t_test(a, b)
        assert winner == "tie"


class TestNormalCDF:
    def test_zero(self):
        assert _normal_cdf(0) == pytest.approx(0.5, abs=0.001)

    def test_large_positive(self):
        assert _normal_cdf(5.0) > 0.999

    def test_large_negative(self):
        assert _normal_cdf(-5.0) < 0.001

    def test_symmetry(self):
        assert _normal_cdf(1.0) + _normal_cdf(-1.0) == pytest.approx(1.0, abs=0.001)


class TestABResult:
    def test_to_dict(self):
        result = ABResult(
            experiment_name="test_exp",
            variant_a=VariantResult(variant_name="A", scores=[0.7, 0.8], total_cost=0.02, total_latency=5.0, per_task=[{}, {}]),
            variant_b=VariantResult(variant_name="B", scores=[0.9, 0.85], total_cost=0.03, total_latency=6.0, per_task=[{}, {}]),
            winner="B",
            confidence=0.96,
            score_delta=0.125,
            cost_delta=0.01,
            latency_delta=0.5,
            completed_at="2026-01-01T00:00:00Z",
        )
        d = result.to_dict()
        assert d["experiment"] == "test_exp"
        assert d["winner"] == "B"
        assert d["confidence"] == 0.96
        assert d["variant_a"]["n_samples"] == 2
        assert d["variant_b"]["n_samples"] == 2
        assert "deltas" in d

    def test_save(self, tmp_path):
        result = ABResult(
            experiment_name="test_exp",
            variant_a=VariantResult(variant_name="A", scores=[0.7]),
            variant_b=VariantResult(variant_name="B", scores=[0.8]),
            winner="tie",
            confidence=0.0,
        )
        path = str(tmp_path / "nested" / "result.json")
        result.save(path)
        import json
        data = json.loads((tmp_path / "nested" / "result.json").read_text())
        assert data["experiment"] == "test_exp"


class TestABExperiment:
    def test_defaults(self):
        exp = ABExperiment(
            name="test",
            variant_a=VariantConfig(name="A"),
            variant_b=VariantConfig(name="B"),
        )
        assert exp.num_runs == 1
        assert exp.max_concurrent == 4
        assert "exact_match" in exp.scorers


@pytest.mark.asyncio
async def test_ab_runner_runs_experiment():
    """Test that ABRunner can execute a basic experiment with mock data."""
    from agent_platform.eval.datasets import EvalDataset, EvalTask

    # Create a tiny in-memory dataset
    import tempfile, json, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write(json.dumps({"task_id": "t1", "description": "Test task", "expected_output": "hello"}) + "\n")
        f.write(json.dumps({"task_id": "t2", "description": "Test task 2", "expected_output": "world"}) + "\n")
        dataset_path = f.name

    try:
        experiment = ABExperiment(
            name="test_ab",
            variant_a=VariantConfig(name="A"),
            variant_b=VariantConfig(name="B"),
            dataset_path=dataset_path,
            scorers=["exact_match"],
        )

        runner = ABRunner()
        result = await runner.run(experiment)

        assert result.experiment_name == "test_ab"
        assert result.winner in ("A", "B", "tie")
        assert len(result.variant_a.scores) == 2
        assert len(result.variant_b.scores) == 2
        assert result.completed_at != ""
    finally:
        os.unlink(dataset_path)
