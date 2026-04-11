"""Evaluation history management.

Stores eval results as timestamped JSON files and provides
querying/comparison over time. Used by the dashboard for trend charts
and by CI for regression detection.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from agent_platform.eval.runner import EvalReport

logger = structlog.get_logger()

DEFAULT_HISTORY_DIR = "eval/results/history"


class EvalHistory:
    """File-based evaluation history store."""

    def __init__(self, history_dir: str = DEFAULT_HISTORY_DIR) -> None:
        self._dir = Path(history_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, report: EvalReport) -> str:
        """Save a report to the history directory. Returns the file path."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        name = f"{report.config.name}_{ts}.json"
        path = self._dir / name
        data = report.to_dict()
        data["completed_at"] = report.completed_at
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("eval_history.saved", path=str(path))
        return str(path)

    def list_runs(self, name_filter: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List recent evaluation runs, newest first."""
        files = sorted(self._dir.glob("*.json"), reverse=True)
        runs: list[dict[str, Any]] = []
        for f in files[:limit * 2]:  # read extra in case of filter
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                cfg_name = data.get("config", {}).get("name", "")
                if name_filter and name_filter not in cfg_name:
                    continue
                runs.append({
                    "file": f.name,
                    "name": cfg_name,
                    "completed_at": data.get("completed_at", ""),
                    "summary": data.get("summary", {}),
                })
                if len(runs) >= limit:
                    break
            except (json.JSONDecodeError, KeyError):
                continue
        return runs

    def load_run(self, filename: str) -> dict[str, Any] | None:
        """Load a specific historical run by filename."""
        path = self._dir / filename
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_trend(self, name_filter: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
        """Get score trend data for charting. Returns oldest-first."""
        runs = self.list_runs(name_filter=name_filter, limit=limit)
        runs.reverse()  # oldest first for charting
        return runs

    def compare_last_two(self, name_filter: str | None = None) -> dict[str, Any] | None:
        """Compare the two most recent runs. Useful for CI regression detection."""
        runs = self.list_runs(name_filter=name_filter, limit=2)
        if len(runs) < 2:
            return None

        current = runs[0]["summary"]
        previous = runs[1]["summary"]

        score_delta = current.get("average_score", 0) - previous.get("average_score", 0)
        pass_delta = current.get("pass_rate", 0) - previous.get("pass_rate", 0)
        cost_delta = current.get("total_cost_usd", 0) - previous.get("total_cost_usd", 0)

        return {
            "current": runs[0],
            "previous": runs[1],
            "score_delta": round(score_delta, 4),
            "pass_rate_delta": round(pass_delta, 4),
            "cost_delta": round(cost_delta, 4),
            "regression": score_delta < -0.05,  # >5% drop = regression
        }

    def cleanup_old(self, keep: int = 100) -> int:
        """Remove old history files, keeping the most recent `keep` entries."""
        files = sorted(self._dir.glob("*.json"), reverse=True)
        removed = 0
        for f in files[keep:]:
            f.unlink()
            removed += 1
        if removed:
            logger.info("eval_history.cleanup", removed=removed)
        return removed
