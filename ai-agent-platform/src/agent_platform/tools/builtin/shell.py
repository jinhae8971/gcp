"""Built-in shell execution tool with sandboxing."""

from __future__ import annotations

import asyncio
import os

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")
MAX_EXECUTION_TIME = int(os.environ.get("MAX_EXECUTION_TIME_SECONDS", "120"))
MAX_OUTPUT_SIZE = 512_000  # 512 KB


async def execute_command(command: str, timeout: int | None = None) -> str:
    """Execute a shell command in the workspace directory.

    The command runs in a subprocess with:
      - Working directory set to WORKSPACE_ROOT
      - Timeout enforcement
      - Output size limits
    """
    effective_timeout = min(timeout or MAX_EXECUTION_TIME, MAX_EXECUTION_TIME)

    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=WORKSPACE_ROOT,
        env={**os.environ, "HOME": WORKSPACE_ROOT},
    )

    try:
        stdout, _ = await asyncio.wait_for(
            proc.communicate(), timeout=effective_timeout
        )
    except asyncio.TimeoutError:
        proc.kill()
        return f"Error: Command timed out after {effective_timeout}s"

    output = stdout.decode("utf-8", errors="replace")
    if len(output) > MAX_OUTPUT_SIZE:
        output = output[:MAX_OUTPUT_SIZE] + f"\n... (truncated, {len(output)} total bytes)"

    exit_info = f"\n[exit code: {proc.returncode}]"
    return output + exit_info


SHELL_TOOLS = [
    {
        "name": "execute_command",
        "description": "Execute a shell command in the workspace. Returns stdout+stderr and exit code.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (max 120)",
                },
            },
            "required": ["command"],
        },
        "handler": execute_command,
        "parallel_safe": False,
        "requires_approval": True,
        "timeout_seconds": MAX_EXECUTION_TIME,
        "tags": ["shell", "execute"],
    },
]
