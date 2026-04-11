"""Tool registry - manages tool discovery, validation, and execution.

Tools are the agent's hands. This registry provides:
  - Registration of built-in tools and MCP-sourced tools
  - JSON Schema generation for LLM tool definitions
  - Safe execution with timeout and output limits
  - Classification of tools as parallel-safe or sequential
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

import structlog

logger = structlog.get_logger()

ToolFunc = Callable[..., Awaitable[str]]


@dataclass
class ToolDefinition:
    """Metadata for a registered tool."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    handler: ToolFunc
    parallel_safe: bool = True  # Can run concurrently with other tools
    requires_approval: bool = False  # Needs human confirmation before execution
    timeout_seconds: int = 30
    tags: list[str] = field(default_factory=list)

    def to_llm_schema(self) -> dict[str, Any]:
        """Convert to the format expected by LLM APIs."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


class ToolRegistry:
    """Central registry for all available tools."""

    def __init__(self, max_output_size: int = 1_048_576) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._max_output_size = max_output_size

    def register(self, tool: ToolDefinition) -> None:
        if tool.name in self._tools:
            logger.warning("tool.duplicate_registration", name=tool.name)
        self._tools[tool.name] = tool
        logger.info("tool.registered", name=tool.name)

    def register_function(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: ToolFunc,
        **kwargs: Any,
    ) -> None:
        """Convenience method for registering a simple function as a tool."""
        self.register(ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=handler,
            **kwargs,
        ))

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self, tags: list[str] | None = None) -> list[ToolDefinition]:
        if tags:
            return [t for t in self._tools.values() if set(tags) & set(t.tags)]
        return list(self._tools.values())

    def get_llm_definitions(self, tool_names: list[str] | None = None) -> list[dict[str, Any]]:
        """Get tool definitions formatted for LLM consumption."""
        tools = (
            [self._tools[n] for n in tool_names if n in self._tools]
            if tool_names
            else list(self._tools.values())
        )
        return [t.to_llm_schema() for t in tools]

    async def execute(self, tool_call: dict[str, Any]) -> str:
        """Execute a tool call with timeout and output truncation."""
        name = tool_call["name"]
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Unknown tool '{name}'"

        args = tool_call.get("arguments", {})
        if isinstance(args, str):
            args = json.loads(args)

        try:
            result = await asyncio.wait_for(
                tool.handler(**args),
                timeout=tool.timeout_seconds,
            )
        except asyncio.TimeoutError:
            return f"Error: Tool '{name}' timed out after {tool.timeout_seconds}s"
        except Exception as exc:
            logger.error("tool.execution_error", name=name, error=str(exc))
            return f"Error executing '{name}': {exc}"

        # Truncate oversized output
        if len(result) > self._max_output_size:
            truncated = result[: self._max_output_size]
            return truncated + f"\n... (truncated, {len(result)} total chars)"
        return result

    def classify_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split tool calls into parallel-safe and sequential groups."""
        parallel: list[dict[str, Any]] = []
        sequential: list[dict[str, Any]] = []
        for tc in tool_calls:
            tool = self._tools.get(tc["name"])
            if tool and tool.parallel_safe:
                parallel.append(tc)
            else:
                sequential.append(tc)
        return parallel, sequential
