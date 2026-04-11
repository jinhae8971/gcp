"""FastAPI server - REST + WebSocket API for the agent platform.

Endpoints:
  - POST /sessions        Create a new agent session
  - POST /sessions/{id}/message   Send a message to a session
  - GET  /models          List available models
  - GET  /harnesses       List available harness patterns
  - POST /eval/run        Trigger an evaluation run
  - GET  /eval/results    Get evaluation results
  - GET  /health          Health check
  - WS   /ws/{session_id} WebSocket for streaming agent responses
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="Agent Platform API",
    version="0.1.0",
    description="In-house Agentic Coding Platform",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response Models ──────────────────────────────

class CreateSessionRequest(BaseModel):
    model_id: str = "claude-sonnet-4-20250514"
    harness_id: str = "react"
    tools: list[str] | None = None


class CreateSessionResponse(BaseModel):
    session_id: str
    model_id: str
    harness_id: str
    status: str


class SendMessageRequest(BaseModel):
    content: str


class MessageResponse(BaseModel):
    role: str
    content: str
    tool_calls: list[dict[str, Any]] | None = None


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


# ── Endpoints ──────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest) -> CreateSessionResponse:
    from agent_platform.core.session import AgentSession

    session = AgentSession(model_id=req.model_id, harness_id=req.harness_id)
    # TODO: persist session to store
    return CreateSessionResponse(
        session_id=session.session_id,
        model_id=session.model_id,
        harness_id=session.harness_id,
        status=session.status.value,
    )


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
    return [
        HarnessInfo(harness_id="react", description="ReAct pattern: interleaved reasoning and tool use"),
        HarnessInfo(harness_id="plan_execute", description="Two-phase: plan first, then execute step by step"),
    ]


@app.post("/eval/run")
async def trigger_eval(req: EvalRunRequest) -> dict[str, str]:
    # TODO: enqueue eval job to worker
    return {"status": "queued", "config": req.config_path}


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str) -> None:
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            # TODO: route to agent loop streaming
            await websocket.send_json({
                "type": "ack",
                "session_id": session_id,
                "message": data.get("content", ""),
            })
    except WebSocketDisconnect:
        pass


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
