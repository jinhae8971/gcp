"""Core agentic loop.

The heart of the platform: send message -> LLM response -> tool execution -> repeat.
Designed to be harness-agnostic; the Harness class controls *how* the loop behaves
(e.g., ReAct vs Plan-Execute), while this module provides the *engine*.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any, AsyncIterator

import structlog

from agent_platform.core.session import AgentSession, SessionStatus

if TYPE_CHECKING:
    from agent_platform.harness.base import BaseHarness
    from agent_platform.models.gateway import ModelGateway
    from agent_platform.tools.registry import ToolRegistry

logger = structlog.get_logger()

MAX_ITERATIONS = 50  # safety limit to prevent infinite loops


async def run_agent_loop(
    session: AgentSession,
    gateway: "ModelGateway",
    tool_registry: "ToolRegistry",
    harness: "BaseHarness",
) -> AgentSession:
    """Execute the agentic loop until the harness signals completion.

    Flow per iteration:
        1. Harness prepares the request (system prompt, tool definitions, etc.)
        2. Gateway sends to the selected model
        3. If model returns tool calls -> execute tools -> feed results back
        4. If model returns final text -> harness decides: continue or stop
    """
    session.status = SessionStatus.RUNNING
    log = logger.bind(session_id=session.session_id, model=session.model_id)
    log.info("agent_loop.start")

    for iteration in range(1, MAX_ITERATIONS + 1):
        t0 = time.monotonic()

        # 1) Harness builds the LLM request
        request = harness.prepare_request(session)

        # 2) Call the model via gateway
        response = await gateway.chat(
            model=session.model_id,
            messages=request.messages,
            tools=request.tool_definitions,
            temperature=request.temperature,
        )

        session.track_usage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cost=response.usage.cost_usd,
        )

        # 3) Process tool calls if any
        if response.tool_calls:
            tool_results = await _execute_tools(response.tool_calls, tool_registry, log)
            session.add_message("assistant", response.text, tool_calls=response.tool_calls)
            for result in tool_results:
                session.add_message(
                    "tool",
                    result["output"],
                    tool_call_id=result["tool_call_id"],
                )
        else:
            session.add_message("assistant", response.text)

        elapsed = time.monotonic() - t0
        log.info("agent_loop.iteration", iteration=iteration, elapsed_s=round(elapsed, 2))

        # 4) Harness decides whether to continue
        if harness.should_stop(session, response):
            log.info("agent_loop.complete", iterations=iteration)
            session.status = SessionStatus.COMPLETED
            return session

    log.warning("agent_loop.max_iterations_reached")
    session.status = SessionStatus.FAILED
    return session


async def _execute_tools(
    tool_calls: list[dict[str, Any]],
    registry: "ToolRegistry",
    log: Any,
) -> list[dict[str, Any]]:
    """Execute tool calls in parallel where safe, sequentially otherwise."""
    results: list[dict[str, Any]] = []

    # Group into parallel-safe and sequential
    parallel, sequential = registry.classify_calls(tool_calls)

    # Run parallel batch
    if parallel:
        coros = [registry.execute(tc) for tc in parallel]
        parallel_results = await asyncio.gather(*coros, return_exceptions=True)
        for tc, res in zip(parallel, parallel_results):
            if isinstance(res, Exception):
                log.error("tool.error", tool=tc["name"], error=str(res))
                results.append({"tool_call_id": tc["id"], "output": f"Error: {res}"})
            else:
                results.append({"tool_call_id": tc["id"], "output": res})

    # Run sequential
    for tc in sequential:
        try:
            res = await registry.execute(tc)
            results.append({"tool_call_id": tc["id"], "output": res})
        except Exception as exc:
            log.error("tool.error", tool=tc["name"], error=str(exc))
            results.append({"tool_call_id": tc["id"], "output": f"Error: {exc}"})

    return results


async def stream_agent_loop(
    session: AgentSession,
    gateway: "ModelGateway",
    tool_registry: "ToolRegistry",
    harness: "BaseHarness",
) -> AsyncIterator[dict[str, Any]]:
    """Streaming variant that yields events for WebSocket consumers."""
    session.status = SessionStatus.RUNNING

    for iteration in range(1, MAX_ITERATIONS + 1):
        request = harness.prepare_request(session)

        yield {"type": "iteration_start", "iteration": iteration}

        async for chunk in gateway.stream_chat(
            model=session.model_id,
            messages=request.messages,
            tools=request.tool_definitions,
        ):
            yield {"type": "token", "content": chunk.delta}

        response = await gateway.collect_stream()
        session.track_usage(
            response.usage.input_tokens, response.usage.output_tokens, response.usage.cost_usd
        )

        if response.tool_calls:
            yield {"type": "tool_calls", "calls": response.tool_calls}
            tool_results = await _execute_tools(response.tool_calls, tool_registry, logger)
            session.add_message("assistant", response.text, tool_calls=response.tool_calls)
            for result in tool_results:
                session.add_message("tool", result["output"], tool_call_id=result["tool_call_id"])
                yield {"type": "tool_result", "result": result}
        else:
            session.add_message("assistant", response.text)

        if harness.should_stop(session, response):
            session.status = SessionStatus.COMPLETED
            yield {"type": "complete", "iterations": iteration}
            return

    session.status = SessionStatus.FAILED
    yield {"type": "max_iterations", "iterations": MAX_ITERATIONS}
