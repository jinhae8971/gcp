"""OpenTelemetry-based tracing for agent operations.

Traces the full lifecycle: session -> agent loop iterations -> tool calls.
Each span captures tokens used, cost, latency, and model information.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource

_tracer: trace.Tracer | None = None


def init_tracer(service_name: str = "agent-platform") -> trace.Tracer:
    """Initialize the global tracer. Call once at startup."""
    global _tracer
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("agent_platform")
    return _tracer


def get_tracer() -> trace.Tracer:
    if _tracer is None:
        return init_tracer()
    return _tracer


@asynccontextmanager
async def trace_agent_session(session_id: str, model: str) -> AsyncIterator[trace.Span]:
    """Top-level span for an entire agent session."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "agent.session",
        attributes={"session.id": session_id, "model.id": model},
    ) as span:
        yield span


@asynccontextmanager
async def trace_iteration(iteration: int) -> AsyncIterator[trace.Span]:
    """Span for one iteration of the agent loop."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "agent.iteration",
        attributes={"iteration.number": iteration},
    ) as span:
        yield span


@asynccontextmanager
async def trace_tool_call(tool_name: str, tool_call_id: str) -> AsyncIterator[trace.Span]:
    """Span for a single tool execution."""
    tracer = get_tracer()
    with tracer.start_as_current_span(
        "agent.tool_call",
        attributes={"tool.name": tool_name, "tool.call_id": tool_call_id},
    ) as span:
        yield span


def record_llm_usage(
    span: trace.Span,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    model: str,
) -> None:
    """Attach LLM usage metrics to a span."""
    span.set_attribute("llm.input_tokens", input_tokens)
    span.set_attribute("llm.output_tokens", output_tokens)
    span.set_attribute("llm.cost_usd", cost_usd)
    span.set_attribute("llm.model", model)
