"""Evaluation report generators.

Produces:
  - JSON report (for CI/CD and programmatic consumption)
  - Interactive HTML dashboard (for human review)
  - Comparison tables across models/harnesses
  - Trend charts over time
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_platform.eval.runner import EvalReport, TaskResult


def generate_html_dashboard(
    report: EvalReport,
    history: list[dict[str, Any]] | None = None,
    output_path: str = "eval/results/dashboard.html",
) -> str:
    """Generate a self-contained HTML dashboard from eval results."""
    summary = report.to_dict()["summary"]
    results = report.results
    config = report.config

    # Build model × harness score matrix
    matrix = _build_score_matrix(results)
    # Build per-task breakdown
    task_rows = _build_task_rows(results)
    # Build trend data if history available
    trend_js = _build_trend_data(history) if history else "[]"

    html = _DASHBOARD_TEMPLATE.format(
        title=f"Eval Report: {config.name}",
        generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        avg_score=summary["average_score"],
        pass_rate=summary["pass_rate"],
        total_cost=summary["total_cost_usd"],
        total_tasks=summary["total_tasks"],
        gate_status="PASSED" if summary["passes_gate"] else "FAILED",
        gate_class="pass" if summary["passes_gate"] else "fail",
        models_json=json.dumps(config.models),
        harnesses_json=json.dumps(config.harnesses),
        matrix_json=json.dumps(matrix),
        task_rows_html=task_rows,
        trend_data_json=trend_js,
        results_json=json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(html, encoding="utf-8")
    return output_path


def _build_score_matrix(results: list[TaskResult]) -> list[dict[str, Any]]:
    """Build model × harness average score matrix."""
    buckets: dict[tuple[str, str], list[float]] = {}
    for r in results:
        if r.error:
            continue
        key = (r.model, r.harness)
        buckets.setdefault(key, [])
        for s in r.scores.values():
            buckets[key].append(s)

    matrix = []
    for (model, harness), scores in sorted(buckets.keys()):
        vals = buckets[(model, harness)]
        matrix.append({
            "model": model,
            "harness": harness,
            "avg_score": round(sum(vals) / len(vals), 4) if vals else 0,
            "count": len(vals),
        })
    return matrix


def _build_task_rows(results: list[TaskResult]) -> str:
    rows = []
    for r in sorted(results, key=lambda x: x.task_id):
        score_val = sum(r.scores.values()) / len(r.scores) if r.scores else 0
        score_class = "high" if score_val >= 0.7 else "mid" if score_val >= 0.4 else "low"
        error_cell = f'<span class="error">{r.error[:60]}</span>' if r.error else ""
        scores_str = ", ".join(f"{k}: {v:.2f}" for k, v in r.scores.items())
        rows.append(
            f"<tr>"
            f"<td>{r.task_id}</td>"
            f"<td>{r.model.split('-')[0]}...{r.model[-8:]}</td>"
            f"<td>{r.harness}</td>"
            f'<td class="{score_class}">{score_val:.2f}</td>'
            f"<td>{scores_str}</td>"
            f"<td>{r.elapsed_seconds:.1f}s</td>"
            f"<td>${r.cost_usd:.4f}</td>"
            f"<td>{error_cell}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


def _build_trend_data(history: list[dict[str, Any]]) -> str:
    """Convert history entries to chart-friendly JSON."""
    points = []
    for entry in history:
        s = entry.get("summary", {})
        points.append({
            "date": entry.get("completed_at", "")[:10],
            "avg_score": s.get("average_score", 0),
            "pass_rate": s.get("pass_rate", 0),
            "cost": s.get("total_cost_usd", 0),
        })
    return json.dumps(points)


_DASHBOARD_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'Inter','Noto Sans KR',system-ui,sans-serif; background:#0d1117; color:#c9d1d9; padding:24px; }}
  h1 {{ color:#58a6ff; font-size:1.5rem; margin-bottom:4px; }}
  h2 {{ color:#58a6ff; font-size:1.1rem; margin:28px 0 12px; border-bottom:1px solid #21262d; padding-bottom:8px; }}
  .meta {{ color:#8b949e; font-size:.85rem; margin-bottom:20px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:16px 0; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; text-align:center; }}
  .card .value {{ font-size:1.6rem; font-weight:700; color:#e6edf3; }}
  .card .label {{ font-size:.8rem; color:#8b949e; margin-top:4px; }}
  .card.pass .value {{ color:#3fb950; }}
  .card.fail .value {{ color:#f85149; }}
  table {{ width:100%; border-collapse:collapse; font-size:.85rem; margin-top:8px; }}
  th {{ background:#161b22; color:#8b949e; text-align:left; padding:8px 12px; border-bottom:2px solid #30363d; }}
  td {{ padding:8px 12px; border-bottom:1px solid #21262d; }}
  .high {{ color:#3fb950; font-weight:600; }}
  .mid {{ color:#d29922; font-weight:600; }}
  .low {{ color:#f85149; font-weight:600; }}
  .error {{ color:#f85149; font-size:.8rem; }}
  .chart-container {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:20px; margin:16px 0; }}
  .bar {{ display:inline-block; height:24px; border-radius:4px; margin:2px 0; min-width:2px; }}
  .bar-row {{ display:flex; align-items:center; gap:8px; margin:4px 0; }}
  .bar-label {{ width:200px; font-size:.8rem; text-align:right; color:#8b949e; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
  .bar-value {{ font-size:.8rem; color:#e6edf3; min-width:40px; }}
  pre {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; font-size:.75rem; overflow-x:auto; max-height:400px; }}
  .trend-row {{ display:flex; gap:12px; flex-wrap:wrap; }}
  .trend-card {{ flex:1; min-width:200px; }}
  .sparkline {{ height:40px; display:flex; align-items:end; gap:2px; }}
  .spark-bar {{ background:#58a6ff; border-radius:2px 2px 0 0; min-width:6px; flex:1; }}
  details {{ margin:8px 0; }}
  summary {{ cursor:pointer; color:#58a6ff; font-size:.9rem; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p class="meta">Generated: {generated_at}</p>

<div class="cards">
  <div class="card"><div class="value">{avg_score:.2%}</div><div class="label">Average Score</div></div>
  <div class="card"><div class="value">{pass_rate:.1%}</div><div class="label">Pass Rate</div></div>
  <div class="card"><div class="value">${total_cost:.4f}</div><div class="label">Total Cost</div></div>
  <div class="card"><div class="value">{total_tasks}</div><div class="label">Total Tasks</div></div>
  <div class="card {gate_class}"><div class="value">{gate_status}</div><div class="label">CI Gate</div></div>
</div>

<h2>Model x Harness Comparison</h2>
<div class="chart-container" id="comparison-chart"></div>

<h2>Per-Task Results</h2>
<table>
<thead><tr><th>Task</th><th>Model</th><th>Harness</th><th>Score</th><th>Details</th><th>Time</th><th>Cost</th><th>Error</th></tr></thead>
<tbody>
{task_rows_html}
</tbody>
</table>

<h2>Score Trend</h2>
<div class="chart-container" id="trend-chart"></div>

<details>
<summary>Raw JSON Results</summary>
<pre>{results_json}</pre>
</details>

<script>
// Comparison bar chart
(function() {{
  const matrix = {matrix_json};
  const container = document.getElementById('comparison-chart');
  if (!matrix.length) {{ container.innerHTML = '<p style="color:#8b949e">No comparison data</p>'; return; }}
  let html = '';
  matrix.forEach(m => {{
    const pct = Math.round(m.avg_score * 100);
    const color = pct >= 70 ? '#3fb950' : pct >= 40 ? '#d29922' : '#f85149';
    html += `<div class="bar-row">
      <div class="bar-label">${{m.model}} / ${{m.harness}}</div>
      <div class="bar" style="width:${{Math.max(pct,2)}}%;background:${{color}}"></div>
      <div class="bar-value">${{pct}}%</div>
    </div>`;
  }});
  container.innerHTML = html;
}})();

// Trend sparklines
(function() {{
  const trend = {trend_data_json};
  const container = document.getElementById('trend-chart');
  if (!trend.length) {{ container.innerHTML = '<p style="color:#8b949e">No historical data yet. Run evaluations to build trend.</p>'; return; }}
  const maxScore = Math.max(...trend.map(t => t.avg_score), 0.01);
  let html = '<div class="trend-row"><div class="trend-card"><h3 style="color:#8b949e;font-size:.85rem">Score Over Time</h3><div class="sparkline">';
  trend.forEach(t => {{
    const h = Math.max((t.avg_score / maxScore) * 40, 2);
    html += `<div class="spark-bar" style="height:${{h}}px" title="${{t.date}}: ${{(t.avg_score*100).toFixed(1)}}%"></div>`;
  }});
  html += '</div></div></div>';
  container.innerHTML = html;
}})();
</script>
</body>
</html>
"""
