"""Tests for tool registry."""

import pytest

from agent_platform.tools.registry import ToolDefinition, ToolRegistry


async def _echo_handler(text: str = "hello") -> str:
    return f"echo: {text}"


async def _slow_handler() -> str:
    import asyncio
    await asyncio.sleep(100)
    return "done"


@pytest.fixture
def registry() -> ToolRegistry:
    reg = ToolRegistry(max_output_size=1000)
    reg.register(ToolDefinition(
        name="echo",
        description="Echo the input text",
        parameters={"type": "object", "properties": {"text": {"type": "string"}}},
        handler=_echo_handler,
        parallel_safe=True,
    ))
    return reg


@pytest.mark.asyncio
async def test_register_and_execute(registry: ToolRegistry):
    result = await registry.execute({"name": "echo", "id": "1", "arguments": {"text": "world"}})
    assert result == "echo: world"


@pytest.mark.asyncio
async def test_execute_unknown_tool(registry: ToolRegistry):
    result = await registry.execute({"name": "nonexistent", "id": "1", "arguments": {}})
    assert "Unknown tool" in result


@pytest.mark.asyncio
async def test_execute_timeout():
    reg = ToolRegistry()
    reg.register(ToolDefinition(
        name="slow",
        description="A slow tool",
        parameters={"type": "object", "properties": {}},
        handler=_slow_handler,
        timeout_seconds=1,
    ))
    result = await reg.execute({"name": "slow", "id": "1", "arguments": {}})
    assert "timed out" in result


def test_get_llm_definitions(registry: ToolRegistry):
    defs = registry.get_llm_definitions()
    assert len(defs) == 1
    assert defs[0]["name"] == "echo"
    assert "input_schema" in defs[0]


def test_classify_calls(registry: ToolRegistry):
    reg = registry
    reg.register(ToolDefinition(
        name="write",
        description="Write op",
        parameters={},
        handler=_echo_handler,
        parallel_safe=False,
    ))
    calls = [
        {"name": "echo", "id": "1"},
        {"name": "write", "id": "2"},
        {"name": "echo", "id": "3"},
    ]
    parallel, sequential = reg.classify_calls(calls)
    assert len(parallel) == 2
    assert len(sequential) == 1
