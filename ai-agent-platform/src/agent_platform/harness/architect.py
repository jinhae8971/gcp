"""Architect harness - design-focused agent.

Specializes in upfront technical design before any implementation.
Best for: new features, greenfield modules, cross-cutting changes
where architectural decisions matter more than raw code generation.

Two-phase pattern:
  Phase 1 (Design): Produce a design document covering goals, constraints,
                    options considered, chosen approach, and module boundaries
  Phase 2 (Handoff): Output a structured handoff for an implementation agent
                     (files to create/modify, interfaces, tests)

The Architect does NOT typically write code itself - it uses read-only
tools (read_file, search_files, list_directory) to understand the codebase
and produces design artifacts as text.
"""

from __future__ import annotations

from typing import Any

from agent_platform.core.session import AgentSession
from agent_platform.harness.base import BaseHarness, LLMRequest
from agent_platform.models.providers.base import ChatResponse

ARCHITECT_SYSTEM_PROMPT = """\
You are a Principal Software Architect embedded in an agentic coding environment.
Your job is design, not implementation.

## Workflow
1. **Understand** the request and relevant parts of the codebase (use read-only tools)
2. **Survey** existing patterns, abstractions, and constraints
3. **Design** the solution in a structured design doc
4. **Hand off** implementation tasks to an executor agent

## Design Document Format
Always produce your design as markdown with these sections:

```
# Design: <title>

## Goals
- What this change must accomplish (bullet points)

## Non-Goals
- What is explicitly out of scope

## Constraints
- Technical, organizational, or compatibility constraints

## Options Considered
1. Option A: pros/cons
2. Option B: pros/cons

## Chosen Approach
- Which option and why

## Module Boundaries
- New files/modules to create
- Existing files to modify (with rationale)
- Public interfaces (signatures, types)

## Test Strategy
- Unit tests, integration tests, edge cases

## Handoff Checklist
- [ ] Task 1 for executor
- [ ] Task 2 for executor
```

## Rules
- Do NOT write implementation code - only design artifacts
- Use read-only tools (read_file, search_files, list_directory) to gather context
- Keep designs concise but complete - every decision must be justified
- Explicitly flag risks, unknowns, and assumptions
- When the design is complete, state "DESIGN COMPLETE" and stop
"""

# Only expose read-only tools to the architect
READ_ONLY_TOOL_NAMES = {"read_file", "list_directory", "search_files"}


class ArchitectHarness(BaseHarness):
    harness_id = "architect"
    description = "Design-focused: produces design docs and handoff plans, not code"

    def __init__(self, tool_definitions: list[dict[str, Any]] | None = None) -> None:
        # Filter to read-only tools - architect should not modify files
        all_tools = tool_definitions or []
        self._tool_definitions = [
            t for t in all_tools if t.get("name") in READ_ONLY_TOOL_NAMES
        ]

    def prepare_request(self, session: AgentSession) -> LLMRequest:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.get_system_prompt()},
        ]
        for msg in session.messages:
            messages.append({"role": msg.role, "content": msg.content})

        return LLMRequest(
            messages=messages,
            tool_definitions=self._tool_definitions,
            temperature=0.2,  # Slight creativity for design tradeoffs
            max_tokens=8192,  # Design docs can be longer
        )

    def should_stop(self, session: AgentSession, response: ChatResponse) -> bool:
        # Stop when the architect signals completion or produces no more tool calls
        if response.text and "DESIGN COMPLETE" in response.text.upper():
            return True
        return len(response.tool_calls) == 0

    def get_system_prompt(self) -> str:
        return ARCHITECT_SYSTEM_PROMPT
