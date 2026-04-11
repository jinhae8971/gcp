"""Base harness interface.

A Harness controls *how* the agent loop behaves -- the system prompt strategy,
tool selection, stop conditions, and request preparation. Different harness
implementations encode different agentic patterns (ReAct, Plan-Execute, etc.)
so they can be swapped and compared via the evaluation framework.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from agent_platform.core.session import AgentSession
from agent_platform.models.providers.base import ChatResponse


@dataclass
class LLMRequest:
    """Prepared request to send to the model gateway."""

    messages: list[dict[str, Any]]
    tool_definitions: list[dict[str, Any]] = field(default_factory=list)
    temperature: float = 0.0
    max_tokens: int = 4096


class BaseHarness(ABC):
    """Every harness pattern must implement these methods."""

    harness_id: str = ""
    description: str = ""

    @abstractmethod
    def prepare_request(self, session: AgentSession) -> LLMRequest:
        """Build the LLM request from the current session state.

        This is where the harness injects its system prompt, selects
        which tools to expose, and formats the conversation history.
        """

    @abstractmethod
    def should_stop(self, session: AgentSession, response: ChatResponse) -> bool:
        """Decide whether the agentic loop should terminate.

        Returns True if the agent has completed its task or reached a
        natural stopping point.
        """

    def get_system_prompt(self) -> str:
        """Return the system prompt for this harness pattern."""
        return ""
