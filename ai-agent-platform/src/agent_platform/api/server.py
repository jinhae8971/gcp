"""FastAPI server - REST + WebSocket API for the agent platform.

All endpoints are wired to the PlatformContext created at startup
via the lifespan handler. Sessions are persisted and agent loops
run against real model providers.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
    config_path: str = "eval/configs/default_eval.yaml"
    models: list[str] | None = None
    harnesses: list[str] | None = None


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
async def trigger_eval(req: EvalRunRequest) -> dict[str, str]:
    # TODO: enqueue eval job to worker via Redis
    return {"status": "queued", "config": req.config_path}


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
