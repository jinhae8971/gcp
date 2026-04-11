"""Abstract base for LLM providers.

Each provider adapter normalizes its vendor-specific API into a common
interface so the gateway can route transparently.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class UsageInfo:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


@dataclass
class ChatResponse:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: UsageInfo = field(default_factory=UsageInfo)
    model: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamChunk:
    delta: str = ""
    tool_call_delta: dict[str, Any] | None = None
    finish_reason: str | None = None


@dataclass
class ChatRequest:
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    temperature: float = 0.0
    max_tokens: int = 4096


class BaseProvider(ABC):
    """Interface that every provider adapter must implement."""

    provider_name: str = ""
    supported_models: list[str] = []

    @abstractmethod
    async def chat(self, model: str, request: ChatRequest) -> ChatResponse:
        """Send a chat completion request and return the full response."""

    @abstractmethod
    async def stream_chat(self, model: str, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        """Stream a chat completion, yielding chunks as they arrive."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if this provider is reachable and functional."""

    def supports_model(self, model_id: str) -> bool:
        return model_id in self.supported_models
