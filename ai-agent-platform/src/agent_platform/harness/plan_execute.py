"""Plan-and-Execute harness.

Two-phase pattern:
  Phase 1 (Plan): Generate a structured plan with numbered steps
  Phase 2 (Execute): Execute each step using tools, updating the plan as needed

This harness is better for complex, multi-file tasks where upfront planning
reduces wasted tool calls and improves coherence.
"""

from __future__ import annotations

import json
from typing import Any

from agent_platform.core.session import AgentSession
from agent_platform.harness.base import BaseHarness, LLMRequest
from agent_platform.models.providers.base import ChatResponse

PLAN_SYSTEM_PROMPT = """\
You are an expert software engineer. You work in two phases:

## Phase 1: Planning
When you receive a task, first create a structured plan:
```json
{{"plan": [
  {{"step": 1, "action": "description", "status": "pending"}},
  ...
]}}
```

## Phase 2: Execution
Execute each step, marking it complete as you go.
After completing a step, output the updated plan.

## Rules
- Always plan before acting
- Each step should be atomic and testable
- Update step status to "done" or "failed" as you progress
- If a step fails, re-plan the remaining steps
- When all steps are "done", output your final summary
"""

EXECUTE_SYSTEM_PROMPT = """\
You are executing step {current_step} of your plan.

Current plan state:
{plan_json}

Execute the current step using the available tools.
After completion, mark the step as "done" and proceed to the next.
When all steps are complete, provide a final summary.
"""


class PlanExecuteHarness(BaseHarness):
    harness_id = "plan_execute"
    description = "Two-phase: plan first, then execute step by step"

    def __init__(self, tool_definitions: list[dict[str, Any]] | None = None) -> None:
        self._tool_definitions = tool_definitions or []
        self._plan: list[dict[str, Any]] | None = None
        self._current_step = 0

    def prepare_request(self, session: AgentSession) -> LLMRequest:
        messages: list[dict[str, Any]] = []

        if self._plan is None:
            # Phase 1: Planning
            messages.append({"role": "system", "content": PLAN_SYSTEM_PROMPT})
        else:
            # Phase 2: Execution
            system = EXECUTE_SYSTEM_PROMPT.format(
                current_step=self._current_step + 1,
                plan_json=json.dumps(self._plan, indent=2),
            )
            messages.append({"role": "system", "content": system})

        for msg in session.messages:
            messages.append({"role": msg.role, "content": msg.content})

        return LLMRequest(
            messages=messages,
            tool_definitions=self._tool_definitions,
            temperature=0.0,
        )

    def should_stop(self, session: AgentSession, response: ChatResponse) -> bool:
        # Try to extract plan from response
        if self._plan is None and response.text:
            self._plan = self._extract_plan(response.text)
            if self._plan:
                return False  # Continue to execution phase

        # During execution: stop when no tool calls (step complete or all done)
        if response.tool_calls:
            return False

        # Check if all steps are done
        if self._plan:
            self._current_step += 1
            if self._current_step >= len(self._plan):
                return True  # All steps completed
            return False  # More steps to execute

        return True  # Fallback: stop if no plan and no tool calls

    def _extract_plan(self, text: str) -> list[dict[str, Any]] | None:
        """Try to parse a plan from the model's response."""
        try:
            # Look for JSON block in the response
            start = text.find('{"plan"')
            if start == -1:
                start = text.find("```json")
                if start != -1:
                    start = text.find("{", start)
            if start == -1:
                return None
            end = text.rfind("}") + 1
            if end <= start:
                return None
            data = json.loads(text[start:end])
            return data.get("plan", [])
        except (json.JSONDecodeError, KeyError):
            return None

    def get_system_prompt(self) -> str:
        return PLAN_SYSTEM_PROMPT
