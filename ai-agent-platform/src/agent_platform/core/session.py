"""Agent session management.

An AgentSession encapsulates one complete conversation: the message history,
the selected model/harness, and the tool context. Sessions are the unit of
work for the agentic loop.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SessionStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_USER = "waiting_user"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Message:
    role: str  # "user" | "assistant" | "system" | "tool"
    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class AgentSession:
    """Holds the full state needed to run one agent conversation."""

    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    model_id: str = ""
    harness_id: str = "react"  # default harness pattern
    messages: list[Message] = field(default_factory=list)
    status: SessionStatus = SessionStatus.IDLE
    tools_enabled: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0

    def add_message(self, role: str, content: str, **kwargs: Any) -> Message:
        msg = Message(role=role, content=content, **kwargs)
        self.messages.append(msg)
        return msg

    def track_usage(self, input_tokens: int, output_tokens: int, cost: float) -> None:
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost_usd += cost
