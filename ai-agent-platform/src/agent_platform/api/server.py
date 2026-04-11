"""FastAPI server - REST + WebSocket API for the agent platform.

All endpoints are wired to the PlatformContext created at startup
via the lifespan handler. Sessions are persisted and agent loops
run against real model providers.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from agent_platform.core.factory import PlatformContext, create_platform
from agent_platform.core.session import AgentSession, SessionStatus
from agent_platform.core.agent_loop import run_agent_loop, stream_agent_loop

# Module-level reference set by lifespan
_ctx: PlatformContext | None = None


def _get_ctx() -> PlatformContext:
    if _ctx is None:
        raise RuntimeError("Platform not initialized")
    return _ctx


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _ctx
    _ctx = create_platform()
    yield
    _ctx = None


app = FastAPI(
    title="Agent Platform API",
    version="0.1.0",
    description="In-house Agentic Coding Platform",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Models ──────────────────────────────

class CreateSessionRequest(BaseModel):
    model_id: str = ""
    harness_id: str = "react"
    tools: list[str] | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    model_id: str
    harness_id: str
    status: str


class SendMessageRequest(BaseModel):
    content: str


class SessionResponse(BaseModel):
    session_id: str
    status: str
    messages: list[dict[str, Any]]
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float


class ModelInfo(BaseModel):
    model_id: str
    provider: str
    tier: str
    description: str


class HarnessInfo(BaseModel):
    harness_id: str
    description: str


class EvalRunRequest(BaseModel):
    config_path: str | None = None
    name: str = "default"
    dataset_path: str = "eval/datasets/sample_tasks.jsonl"
    models: list[str] | None = None
    harnesses: list[str] | None = None
    scorers: list[str] | None = None
    min_score_threshold: float = 0.7
    max_concurrent: int = 4
    timeout_per_task: int = 300


class EvalJobResponse(BaseModel):
    job_id: str
    status: str
    message: str


class EvalHistoryResponse(BaseModel):
    runs: list[dict[str, Any]]


class ABTestVariantModel(BaseModel):
    name: str = "A"
    prompt_name: str = ""
    prompt_version: int | None = None
    harness_id: str = "react"
    system_prompt_override: str = ""
    temperature: float = 0.0


class ABTestRequest(BaseModel):
    name: str
    variant_a: ABTestVariantModel
    variant_b: ABTestVariantModel
    dataset_path: str = "eval/datasets/sample_tasks.jsonl"
    model: str = "claude-sonnet-4-20250514"
    scorers: list[str] | None = None
    num_runs: int = 1


class ABTestResponse(BaseModel):
    experiment: str
    winner: str
    confidence: float
    variant_a: dict[str, Any]
    variant_b: dict[str, Any]
    deltas: dict[str, Any]
    completed_at: str


class EvalComparisonResponse(BaseModel):
    current: dict[str, Any]
    previous: dict[str, Any]
    score_delta: float
    pass_rate_delta: float
    cost_delta: float
    regression: bool


class HealthResponse(BaseModel):
    status: str
    providers: dict[str, bool] = {}
    active_sessions: int = 0


# ── Endpoints ──────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    ctx = _get_ctx()
    provider_health = await ctx.gateway.health()
    session_ids = await ctx.session_store.list_ids()
    return HealthResponse(
        status="ok",
        providers=provider_health,
        active_sessions=len(session_ids),
    )


@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    ctx = _get_ctx()
    model_id = req.model_id or ctx.settings.gateway.default_model

    if req.harness_id not in ctx.harnesses:
        raise HTTPException(400, f"Unknown harness: {req.harness_id}")

    session = AgentSession(model_id=model_id, harness_id=req.harness_id)
    await ctx.session_store.save(session)

    return CreateSessionResponse(
        session_id=session.session_id,
        model_id=session.model_id,
        harness_id=session.harness_id,
        status=session.status.value,
    )


@app.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    ctx = _get_ctx()
    session = await ctx.session_store.load(session_id)
    if not session:
        raise HTTPException(404, f"Session not found: {session_id}")

    return SessionResponse(
        session_id=session.session_id,
        status=session.status.value,
        messages=[
            {"role": m.role, "content": m.content, "tool_calls": m.tool_calls or None}
            for m in session.messages
        ],
        total_input_tokens=session.total_input_tokens,
        total_output_tokens=session.total_output_tokens,
        total_cost_usd=session.total_cost_usd,
    )


@app.post("/sessions/{session_id}/message", response_model=SessionResponse)
async def send_message(session_id: str, req: SendMessageRequest) -> SessionResponse:
    """Send a user message and run the agent loop to completion."""
    ctx = _get_ctx()
    session = await ctx.session_store.load(session_id)
    if not session:
        raise HTTPException(404, f"Session not found: {session_id}")

    harness = ctx.harnesses.get(session.harness_id)
    if not harness:
        raise HTTPException(500, f"Harness not found: {session.harness_id}")

    session.add_message("user", req.content)

    # Reset status for this turn
    session.status = SessionStatus.IDLE

    session = await run_agent_loop(session, ctx.gateway, ctx.tool_registry, harness)
    await ctx.session_store.save(session)

    return SessionResponse(
        session_id=session.session_id,
        status=session.status.value,
        messages=[
            {"role": m.role, "content": m.content, "tool_calls": m.tool_calls or None}
            for m in session.messages
        ],
        total_input_tokens=session.total_input_tokens,
        total_output_tokens=session.total_output_tokens,
        total_cost_usd=session.total_cost_usd,
    )


@app.get("/sessions")
async def list_sessions() -> list[str]:
    ctx = _get_ctx()
    return await ctx.session_store.list_ids()


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, str]:
    ctx = _get_ctx()
    await ctx.session_store.delete(session_id)
    return {"status": "deleted", "session_id": session_id}


@app.get("/models", response_model=list[ModelInfo])
async def list_models() -> list[ModelInfo]:
    from agent_platform.models.registry import MODEL_CATALOG

    return [
        ModelInfo(
            model_id=m.model_id,
            provider=m.provider,
            tier=m.tier.value,
            description=m.description,
        )
        for m in MODEL_CATALOG.values()
    ]


@app.get("/harnesses", response_model=list[HarnessInfo])
async def list_harnesses() -> list[HarnessInfo]:
    ctx = _get_ctx()
    return [
        HarnessInfo(harness_id=h_id, description=h.description)
        for h_id, h in ctx.harnesses.items()
    ]


@app.get("/tools")
async def list_tools() -> list[dict[str, Any]]:
    ctx = _get_ctx()
    return [
        {"name": t.name, "description": t.description, "parallel_safe": t.parallel_safe}
        for t in ctx.tool_registry.list_tools()
    ]


@app.post("/eval/run")
async def trigger_eval(req: EvalRunRequest) -> dict[str, Any]:
    """Run an evaluation suite and return the report summary.

    If *config_path* is supplied the YAML file is loaded first and then
    any explicit overrides (models, harnesses, scorers, etc.) are applied
    on top.  Otherwise a config is built purely from the request body.
    """
    from agent_platform.eval.runner import EvalConfig, EvalRunner, EvalReport
    from agent_platform.eval.history import EvalHistory

    try:
        if req.config_path:
            config = EvalConfig.from_yaml(req.config_path)
        else:
            config = EvalConfig(name=req.name, dataset_path=req.dataset_path)

        # Apply explicit overrides
        if req.models:
            config.models = req.models
        if req.harnesses:
            config.harnesses = req.harnesses
        if req.scorers:
            config.scorers = req.scorers
        config.min_score_threshold = req.min_score_threshold
        config.max_concurrent = req.max_concurrent
        config.timeout_per_task = req.timeout_per_task

        runner = EvalRunner()
        report: EvalReport = await runner.run(config)

        # Persist to history
        history = EvalHistory()
        saved_path = history.save(report)

        result = report.to_dict()
        result["history_file"] = saved_path
        return result

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Config or dataset not found: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Eval run failed: {exc}")


@app.get("/eval/history", response_model=EvalHistoryResponse)
async def list_eval_history(
    name: str | None = Query(None, description="Filter by eval config name"),
    limit: int = Query(50, ge=1, le=500, description="Max runs to return"),
) -> EvalHistoryResponse:
    """List recent evaluation runs, newest first."""
    from agent_platform.eval.history import EvalHistory

    history = EvalHistory()
    runs = history.list_runs(name_filter=name, limit=limit)
    return EvalHistoryResponse(runs=runs)


@app.get("/eval/history/{filename}")
async def get_eval_run(filename: str) -> dict[str, Any]:
    """Load a specific historical eval run by filename."""
    from agent_platform.eval.history import EvalHistory

    history = EvalHistory()
    run = history.load_run(filename)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Eval run not found: {filename}")
    return run


@app.get("/eval/trend")
async def get_eval_trend(
    name: str | None = Query(None, description="Filter by eval config name"),
    limit: int = Query(30, ge=1, le=200, description="Max data points"),
) -> list[dict[str, Any]]:
    """Get score trend data for charting (oldest first)."""
    from agent_platform.eval.history import EvalHistory

    history = EvalHistory()
    return history.get_trend(name_filter=name, limit=limit)


@app.get("/eval/compare", response_model=EvalComparisonResponse)
async def compare_eval_runs(
    name: str | None = Query(None, description="Filter by eval config name"),
) -> EvalComparisonResponse:
    """Compare the two most recent eval runs for regression detection."""
    from agent_platform.eval.history import EvalHistory

    history = EvalHistory()
    comparison = history.compare_last_two(name_filter=name)
    if comparison is None:
        raise HTTPException(
            status_code=404,
            detail="Not enough runs to compare. Need at least two historical runs.",
        )
    return EvalComparisonResponse(**comparison)


@app.post("/eval/ab-test", response_model=ABTestResponse)
async def run_ab_test(req: ABTestRequest) -> ABTestResponse:
    """Run an A/B experiment comparing two prompt/harness variants."""
    from agent_platform.eval.ab_testing import (
        ABExperiment,
        ABRunner,
        VariantConfig,
    )

    try:
        experiment = ABExperiment(
            name=req.name,
            variant_a=VariantConfig(
                name=req.variant_a.name,
                prompt_name=req.variant_a.prompt_name,
                prompt_version=req.variant_a.prompt_version,
                harness_id=req.variant_a.harness_id,
                system_prompt_override=req.variant_a.system_prompt_override,
                temperature=req.variant_a.temperature,
            ),
            variant_b=VariantConfig(
                name=req.variant_b.name,
                prompt_name=req.variant_b.prompt_name,
                prompt_version=req.variant_b.prompt_version,
                harness_id=req.variant_b.harness_id,
                system_prompt_override=req.variant_b.system_prompt_override,
                temperature=req.variant_b.temperature,
            ),
            dataset_path=req.dataset_path,
            model=req.model,
            scorers=req.scorers or ["exact_match", "test_pass"],
            num_runs=req.num_runs,
        )

        runner = ABRunner()
        result = await runner.run(experiment)

        result_dict = result.to_dict()
        return ABTestResponse(
            experiment=result_dict["experiment"],
            winner=result_dict["winner"],
            confidence=result_dict["confidence"],
            variant_a=result_dict["variant_a"],
            variant_b=result_dict["variant_b"],
            deltas=result_dict["deltas"],
            completed_at=result_dict["completed_at"],
        )

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Dataset not found: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"A/B test failed: {exc}")


@app.get("/eval/scorers")
async def list_scorers() -> list[str]:
    """List all available scorer names."""
    from agent_platform.eval.scorers import ScorerRegistry

    registry = ScorerRegistry()
    return registry.list_scorers()


@app.get("/eval/dashboard", response_class=HTMLResponse)
async def get_eval_dashboard(
    name: str | None = Query(None, description="Filter history by eval config name"),
) -> HTMLResponse:
    """Generate an HTML dashboard from the most recent eval run."""
    from agent_platform.eval.history import EvalHistory
    from agent_platform.eval.reporters import generate_html_dashboard
    from agent_platform.eval.runner import EvalConfig, EvalReport, TaskResult

    history = EvalHistory()
    runs = history.list_runs(name_filter=name, limit=1)
    if not runs:
        raise HTTPException(
            status_code=404,
            detail="No eval runs found. Run an evaluation first.",
        )

    # Load full run data to reconstruct the report
    run_data = history.load_run(runs[0]["file"])
    if run_data is None:
        raise HTTPException(status_code=404, detail="Could not load latest run data.")

    cfg_data = run_data.get("config", {})
    report = EvalReport(
        config=EvalConfig(
            name=cfg_data.get("name", "unknown"),
            models=cfg_data.get("models", []),
            harnesses=cfg_data.get("harnesses", []),
        ),
        results=[
            TaskResult(
                task_id=r.get("task_id", ""),
                model=r.get("model", ""),
                harness=r.get("harness", ""),
                scores=r.get("scores", {}),
                elapsed_seconds=r.get("elapsed_s", 0.0),
                cost_usd=r.get("cost_usd", 0.0),
                error=r.get("error"),
            )
            for r in run_data.get("results", [])
        ],
        started_at=run_data.get("started_at", ""),
        completed_at=run_data.get("completed_at", ""),
    )

    trend = history.get_trend(name_filter=name)
    dashboard_path = generate_html_dashboard(report, history=trend)

    from pathlib import Path
    html_content = Path(dashboard_path).read_text(encoding="utf-8")
    return HTMLResponse(content=html_content)


@app.post("/eval/dashboard")
async def generate_eval_dashboard(req: EvalRunRequest) -> dict[str, str]:
    """Run an eval with the given config and generate an HTML dashboard.

    Returns the file path of the generated dashboard.
    """
    from agent_platform.eval.runner import EvalConfig, EvalRunner
    from agent_platform.eval.history import EvalHistory
    from agent_platform.eval.reporters import generate_html_dashboard

    try:
        if req.config_path:
            config = EvalConfig.from_yaml(req.config_path)
        else:
            config = EvalConfig(name=req.name, dataset_path=req.dataset_path)

        if req.models:
            config.models = req.models
        if req.harnesses:
            config.harnesses = req.harnesses
        if req.scorers:
            config.scorers = req.scorers
        config.min_score_threshold = req.min_score_threshold
        config.max_concurrent = req.max_concurrent
        config.timeout_per_task = req.timeout_per_task

        runner = EvalRunner()
        report = await runner.run(config)

        # Save to history and generate dashboard
        history = EvalHistory()
        history.save(report)
        trend = history.get_trend(name_filter=config.name)
        dashboard_path = generate_html_dashboard(report, history=trend)

        return {"status": "ok", "dashboard_path": dashboard_path}

    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Config or dataset not found: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Dashboard generation failed: {exc}")


# ── WebSocket - Streaming Agent Loop ──────────────────────

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    """Stream agent responses over WebSocket.

    Client sends: {"content": "user message"}
    Server streams: {"type": "token|tool_calls|tool_result|complete", ...}
    """
    ctx = _get_ctx()
    await websocket.accept()

    session = await ctx.session_store.load(session_id)
    if not session:
        await websocket.send_json({"type": "error", "message": "Session not found"})
        await websocket.close()
        return

    try:
        while True:
            data = await websocket.receive_json()
            content = data.get("content", "")
            if not content:
                continue

            session.add_message("user", content)
            harness = ctx.harnesses.get(session.harness_id)
            if not harness:
                await websocket.send_json({"type": "error", "message": "Invalid harness"})
                continue

            # Stream the agent loop events
            async for event in stream_agent_loop(
                session, ctx.gateway, ctx.tool_registry, harness
            ):
                await websocket.send_json(event)

            await ctx.session_store.save(session)

            # Reset for next turn
            if session.status in (SessionStatus.COMPLETED, SessionStatus.FAILED):
                session.status = SessionStatus.IDLE

    except WebSocketDisconnect:
        await ctx.session_store.save(session)


def cli_main() -> None:
    """CLI entry point for starting the server."""
    import uvicorn
    from agent_platform.config.settings import get_settings

    settings = get_settings()
    uvicorn.run(
        "agent_platform.api.server:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=True,
    )
