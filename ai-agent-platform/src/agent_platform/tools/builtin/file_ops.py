"""Built-in file operation tools for the agent sandbox."""

from __future__ import annotations

import os
from pathlib import Path

WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/workspace")


def _validate_path(path: str) -> Path:
    """Ensure path stays within workspace (prevent directory traversal)."""
    resolved = Path(WORKSPACE_ROOT, path).resolve()
    workspace = Path(WORKSPACE_ROOT).resolve()
    if not str(resolved).startswith(str(workspace)):
        raise PermissionError(f"Access denied: path escapes workspace: {path}")
    return resolved


async def read_file(path: str, offset: int = 0, limit: int = 2000) -> str:
    target = _validate_path(path)
    if not target.exists():
        return f"Error: File not found: {path}"
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    selected = lines[offset : offset + limit]
    numbered = [f"{i + offset + 1}\t{line}" for i, line in enumerate(selected)]
    return "\n".join(numbered)


async def write_file(path: str, content: str) -> str:
    target = _validate_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Written {len(content)} bytes to {path}"


async def list_directory(path: str = ".") -> str:
    target = _validate_path(path)
    if not target.is_dir():
        return f"Error: Not a directory: {path}"
    entries = sorted(target.iterdir())
    lines = []
    for entry in entries[:200]:
        prefix = "d " if entry.is_dir() else "f "
        rel = entry.relative_to(Path(WORKSPACE_ROOT).resolve())
        lines.append(f"{prefix}{rel}")
    return "\n".join(lines) if lines else "(empty directory)"


async def search_files(pattern: str, path: str = ".") -> str:
    target = _validate_path(path)
    matches = sorted(target.rglob(pattern))[:100]
    workspace = Path(WORKSPACE_ROOT).resolve()
    return "\n".join(str(m.relative_to(workspace)) for m in matches) or "No matches found"


# Tool definitions for registration
FILE_TOOLS = [
    {
        "name": "read_file",
        "description": "Read a file's contents with line numbers. Use offset/limit for large files.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
                "offset": {"type": "integer", "description": "Start line (0-based)", "default": 0},
                "limit": {"type": "integer", "description": "Max lines to read", "default": 2000},
            },
            "required": ["path"],
        },
        "handler": read_file,
        "parallel_safe": True,
        "tags": ["file", "read"],
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates parent directories if needed.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace"},
                "content": {"type": "string", "description": "Content to write"},
            },
            "required": ["path", "content"],
        },
        "handler": write_file,
        "parallel_safe": False,
        "tags": ["file", "write"],
    },
    {
        "name": "list_directory",
        "description": "List files and directories at a given path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path", "default": "."},
            },
        },
        "handler": list_directory,
        "parallel_safe": True,
        "tags": ["file", "read"],
    },
    {
        "name": "search_files",
        "description": "Search for files matching a glob pattern.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. '*.py')"},
                "path": {"type": "string", "description": "Search root directory", "default": "."},
            },
            "required": ["pattern"],
        },
        "handler": search_files,
        "parallel_safe": True,
        "tags": ["file", "search"],
    },
]
