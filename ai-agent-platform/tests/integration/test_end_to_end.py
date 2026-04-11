"""End-to-end integration tests.

These tests verify the full pipeline without real LLM calls:
  Factory → Session → Harness → (mocked) Gateway → Tools → Result

Uses a mock provider that returns deterministic responses.
"""

from __future__ import annotations

import pytest
from typing import Any, AsyncIterator

from agent_platform.config.settings import Settings
from agent_platform.core.agent_loop import run_agent_loop
from agent_platform.core.factory import create_platform, PlatformContext
from agent_platform.core.session import AgentSession, SessionStatus
from agent_platform.models.gateway import ModelGateway
from agent_platform.models.providers.base import (
    BaseProvider, ChatRequest, ChatResponse, StreamChunk, UsageInfo,
)


class MockProvider(BaseProvider):
    """Deterministic provider for testing."""

    provider_name = "mock"
    supported_models = ["mock-model"]

    def __init__(self, responses: list[ChatResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self._call_count = 0

    async def chat(self, model: str, request: ChatRequest) -> ChatResponse:
        self._call_count += 1
        if self._responses:
            return self._responses.pop(0)
        # Default: return a plain text response (no tool calls → loop stops)
        return ChatResponse(
            text="Task completed successfully.",
            tool_calls=[],
            usage=UsageInfo(input_tokens=100, output_tokens=50, cost_usd=0.001),
            model=model,
        )

    async def stream_chat(self, model: str, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        yield StreamChunk(delta="Task completed.")

    async def health_check(self) -> bool:
        return True


@pytest.fixture
def mock_gateway() -> ModelGateway:
    """Gateway with a mock provider."""
    from agent_platform.models.gateway import _MODEL_PROVIDER_MAP
    _MODEL_PROVIDER_MAP["mock-model"] = "mock"

    provider = MockProvider()
    return ModelGateway(
        providers={"mock": provider},
        default_model="mock-model",
    )


@pytest.fixture
def mock_gateway_with_tools() -> tuple[ModelGateway, MockProvider]:
    """Gateway with a mock provider that requests tool calls first."""
    from agent_platform.models.gateway import _MODEL_PROVIDER_MAP
    _MODEL_PROVIDER_MAP["mock-model"] = "mock"

    responses = [
        # First response: call read_file tool
        ChatResponse(
            text="Let me read the file.",
            tool_calls=[{
                "id": "call_1",
                "name": "read_file",
                "arguments": {"path": "test.py"},
            }],
            usage=UsageInfo(input_tokens=100, output_tokens=50, cost_usd=0.001),
        ),
        # Second response: final answer (no tool calls → stops)
        ChatResponse(
            text="The file contains a print statement.",
            tool_calls=[],
            usage=UsageInfo(input_tokens=200, output_tokens=100, cost_usd=0.002),
        ),
    ]
    provider = MockProvider(responses=responses)
    gateway = ModelGateway(
        providers={"mock": provider},
        default_model="mock-model",
    )
    return gateway, provider


@pytest.mark.asyncio
async def test_simple_agent_loop(mock_gateway: ModelGateway):
    """Agent loop completes in a single iteration with no tool calls."""
    from agent_platform.harness.react import ReactHarness
    from agent_platform.tools.registry import ToolRegistry

    session = AgentSession(model_id="mock-model", harness_id="react")
    session.add_message("user", "Say hello")

    harness = ReactHarness()
    tools = ToolRegistry()

    result = await run_agent_loop(session, mock_gateway, tools, harness)

    assert result.status == SessionStatus.COMPLETED
    assert len(result.messages) >= 2  # user + assistant
    assert result.messages[-1].role == "assistant"
    assert result.messages[-1].content == "Task completed successfully."
    assert result.total_input_tokens == 100
    assert result.total_output_tokens == 50


@pytest.mark.asyncio
async def test_agent_loop_with_tool_calls(mock_gateway_with_tools, tmp_path):
    """Agent loop executes tool calls and then completes."""
    import os
    from agent_platform.harness.react import ReactHarness
    from agent_platform.tools.registry import ToolRegistry, ToolDefinition
    from agent_platform.tools.builtin.file_ops import FILE_TOOLS

    gateway, provider = mock_gateway_with_tools

    # Set up workspace with a test file
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "test.py").write_text("print('hello')\n")
    os.environ["WORKSPACE_ROOT"] = str(workspace)

    # Register file tools
    tools = ToolRegistry()
    for tool_spec in FILE_TOOLS:
        spec = dict(tool_spec)
        handler = spec.pop("handler")
        tags = spec.pop("tags", [])
        tools.register(ToolDefinition(handler=handler, tags=tags, **spec))

    harness = ReactHarness(tool_definitions=tools.get_llm_definitions())
    session = AgentSession(model_id="mock-model", harness_id="react")
    session.add_message("user", "What's in test.py?")

    result = await run_agent_loop(session, gateway, tools, harness)

    assert result.status == SessionStatus.COMPLETED
    # Should have: user, assistant (with tool call), tool result, assistant (final)
    assert len(result.messages) >= 4
    assert result.total_cost_usd == pytest.approx(0.003)

    # Verify tool was actually executed
    tool_msgs = [m for m in result.messages if m.role == "tool"]
    assert len(tool_msgs) == 1
    assert "print('hello')" in tool_msgs[0].content


@pytest.mark.asyncio
async def test_session_store_roundtrip():
    """Session survives save/load cycle."""
    from agent_platform.core.session_store import InMemorySessionStore

    store = InMemorySessionStore()
    session = AgentSession(model_id="mock-model", harness_id="react")
    session.add_message("user", "Hello")
    session.track_usage(100, 50, 0.001)

    await store.save(session)
    loaded = await store.load(session.session_id)

    assert loaded is not None
    assert loaded.session_id == session.session_id
    assert loaded.model_id == "mock-model"
    assert len(loaded.messages) == 1


@pytest.mark.asyncio
async def test_platform_factory_no_keys():
    """Factory should work even with no API keys (no providers)."""
    import os
    # Clear any API keys
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        os.environ.pop(key, None)

    settings = Settings()
    ctx = create_platform(settings)

    assert ctx.gateway is not None
    assert len(ctx.harnesses) == 2
    assert len(ctx.tool_registry.list_tools()) > 0


@pytest.mark.asyncio
async def test_circuit_breaker_integration():
    """Circuit breaker opens after repeated failures."""
    from agent_platform.models.gateway import _MODEL_PROVIDER_MAP

    class FailingProvider(BaseProvider):
        provider_name = "failing"
        supported_models = ["fail-model"]

        async def chat(self, model: str, request: ChatRequest) -> ChatResponse:
            raise ConnectionError("Provider down")

        async def stream_chat(self, model: str, request: ChatRequest) -> AsyncIterator[StreamChunk]:
            raise ConnectionError("Provider down")
            yield  # type: ignore[misc]

        async def health_check(self) -> bool:
            return False

    _MODEL_PROVIDER_MAP["fail-model"] = "failing"
    gateway = ModelGateway(
        providers={"failing": FailingProvider()},
        default_model="fail-model",
        max_retries=1,
    )

    with pytest.raises(RuntimeError, match="All providers failed"):
        await gateway.chat(model="fail-model", messages=[{"role": "user", "content": "test"}])
