"""ReAct (Reasoning + Acting) harness.

The classic agentic pattern: the model reasons about what to do, takes an
action (tool call), observes the result, and repeats. This is the default
harness and works well for most coding tasks.

Reference: Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models"
"""

from __future__ import annotations

from typing import Any

from agent_platform.core.session import AgentSession
from agent_platform.harness.base import BaseHarness, LLMRequest
from agent_platform.models.providers.base import ChatResponse

REACT_SYSTEM_PROMPT = """\
You are an expert software engineer working in an agentic coding environment.

## Approach
1. **Reason** about the task and what information you need
2. **Act** by using the tools available to you
3. **Observe** the results and adjust your approach
4. Repeat until the task is complete

## Guidelines
- Read files before modifying them
- Run tests after making changes
- Prefer small, focused edits over large rewrites
- Explain your reasoning before taking action
"""


class ReactHarness(BaseHarness):
    harness_id = "react"
    description = "ReAct pattern: interleaved reasoning and tool use"

    def __init__(self, tool_definitions: list[dict[str, Any]] | None = None) -> None:
        self._tool_definitions = tool_definitions or []

    def prepare_request(self, session: AgentSession) -> LLMRequest:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.get_system_prompt()},
        ]
        for msg in session.messages:
            messages.append({"role": msg.role, "content": msg.content})

        return LLMRequest(
            messages=messages,
            tool_definitions=self._tool_definitions,
            temperature=0.0,
        )

    def should_stop(self, session: AgentSession, response: ChatResponse) -> bool:
        # Stop when the model produces a text response with no tool calls
        return len(response.tool_calls) == 0

    def get_system_prompt(self) -> str:
        return REACT_SYSTEM_PROMPT
