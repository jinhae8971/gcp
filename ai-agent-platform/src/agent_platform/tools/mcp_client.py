"""MCP (Model Context Protocol) client integration.

Discovers tools from external MCP servers and registers them into
the platform's ToolRegistry. This enables the agent to use any
MCP-compatible tool server without custom integration code.

MCP servers are configured via a JSON config file:
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]
    },
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "..."}
    }
  }
}
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass, field
from typing import Any

import structlog

from agent_platform.tools.registry import ToolDefinition, ToolRegistry

logger = structlog.get_logger()

MCP_CONFIG_PATH = os.environ.get("MCP_CONFIG_PATH", "mcp_servers.json")


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class MCPToolInfo:
    """Tool metadata received from an MCP server."""

    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


class MCPServerConnection:
    """Manages a single MCP server subprocess using stdio transport."""

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0

    async def start(self) -> None:
        env = {**os.environ, **self.config.env}
        self._process = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        # Send initialize request
        await self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agent-platform", "version": "0.1.0"},
        })
        logger.info("mcp.server_started", name=self.config.name)

    async def stop(self) -> None:
        if self._process:
            self._process.terminate()
            await self._process.wait()
            logger.info("mcp.server_stopped", name=self.config.name)

    async def list_tools(self) -> list[MCPToolInfo]:
        result = await self._send_request("tools/list", {})
        tools = result.get("tools", [])
        return [
            MCPToolInfo(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=self.config.name,
            )
            for t in tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        # MCP returns content as a list of content blocks
        content = result.get("content", [])
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts) if parts else json.dumps(result)

    async def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self._process or not self._process.stdin or not self._process.stdout:
            raise RuntimeError(f"MCP server '{self.config.name}' not running")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        message = json.dumps(request) + "\n"
        self._process.stdin.write(message.encode())
        await self._process.stdin.drain()

        # Read response line
        line = await asyncio.wait_for(self._process.stdout.readline(), timeout=30)
        if not line:
            raise RuntimeError(f"MCP server '{self.config.name}' returned empty response")

        response = json.loads(line.decode())
        if "error" in response:
            err = response["error"]
            raise RuntimeError(f"MCP error: {err.get('message', err)}")

        return response.get("result", {})


class MCPManager:
    """Manages multiple MCP server connections."""

    def __init__(self) -> None:
        self._connections: dict[str, MCPServerConnection] = {}

    async def load_config(self, config_path: str = MCP_CONFIG_PATH) -> int:
        """Load MCP server configs and start connections."""
        if not os.path.exists(config_path):
            logger.info("mcp.no_config", path=config_path)
            return 0

        with open(config_path) as f:
            config = json.load(f)

        servers = config.get("servers", {})
        count = 0
        for name, spec in servers.items():
            server_config = MCPServerConfig(
                name=name,
                command=spec["command"],
                args=spec.get("args", []),
                env=spec.get("env", {}),
            )
            conn = MCPServerConnection(server_config)
            try:
                await conn.start()
                self._connections[name] = conn
                count += 1
            except Exception as exc:
                logger.error("mcp.server_start_failed", name=name, error=str(exc))

        return count

    async def discover_and_register(self, registry: ToolRegistry) -> int:
        """Discover tools from all MCP servers and register them."""
        total = 0
        for name, conn in self._connections.items():
            try:
                tools = await conn.list_tools()
                for tool_info in tools:
                    _register_mcp_tool(registry, conn, tool_info)
                    total += 1
                logger.info("mcp.tools_discovered", server=name, count=len(tools))
            except Exception as exc:
                logger.error("mcp.discovery_failed", server=name, error=str(exc))
        return total

    async def shutdown(self) -> None:
        for conn in self._connections.values():
            await conn.stop()
        self._connections.clear()


def _register_mcp_tool(
    registry: ToolRegistry,
    connection: MCPServerConnection,
    tool_info: MCPToolInfo,
) -> None:
    """Wrap an MCP tool as a ToolDefinition and register it."""

    async def handler(**kwargs: Any) -> str:
        return await connection.call_tool(tool_info.name, kwargs)

    # Prefix with server name to avoid collisions
    full_name = f"mcp_{tool_info.server_name}_{tool_info.name}"

    registry.register(ToolDefinition(
        name=full_name,
        description=f"[MCP:{tool_info.server_name}] {tool_info.description}",
        parameters=tool_info.input_schema,
        handler=handler,
        parallel_safe=True,
        tags=["mcp", tool_info.server_name],
    ))
