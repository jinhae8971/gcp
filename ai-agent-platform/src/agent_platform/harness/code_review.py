"""Code Review harness - specialized reviewer agent.

Analyzes diffs, files, or entire modules and produces structured review
feedback focused on correctness, security, maintainability, and performance.

Unlike ReAct or Plan-Execute, this harness:
  - Does not modify files (read-only tools only)
  - Produces structured output organized by severity
  - Uses a stricter rubric-based system prompt
  - Scores each finding rather than free-form text
"""

from __future__ import annotations

from typing import Any

from agent_platform.core.session import AgentSession
from agent_platform.harness.base import BaseHarness, LLMRequest
from agent_platform.models.providers.base import ChatResponse

CODE_REVIEW_SYSTEM_PROMPT = """\
You are a Staff Engineer performing a rigorous code review.
Your output must be structured, specific, and actionable.

## Review Dimensions (rate each 1-5)

1. **Correctness** - Does the code do what it claims? Edge cases handled?
2. **Security** - Input validation, auth, injection, secrets, unsafe deps?
3. **Maintainability** - Readability, naming, structure, test coverage?
4. **Performance** - Algorithmic complexity, DB queries, N+1, blocking I/O?
5. **Consistency** - Matches existing patterns and conventions?

## Workflow
1. Use read-only tools (read_file, search_files, list_directory) to gather context
2. Read the file(s) under review AND related files (tests, callers, schemas)
3. Search for existing patterns to compare consistency
4. Produce a structured review report

## Review Report Format

```
# Code Review: <subject>

## Summary
<2-3 sentence overall assessment>

## Scores
- Correctness: N/5
- Security: N/5
- Maintainability: N/5
- Performance: N/5
- Consistency: N/5
- **Overall: N/5**

## Findings

### 🔴 Critical (must fix before merge)
- [file:line] Description. Why it matters. Suggested fix.

### 🟡 Important (should fix)
- [file:line] Description. Why it matters. Suggested fix.

### 🔵 Suggestions (nice to have)
- [file:line] Description. Alternative approach.

### ✅ Positives
- What's done well

## Recommendation
APPROVE | REQUEST_CHANGES | BLOCK
```

## Rules
- Be specific: always cite file:line_number
- Suggest fixes, don't just complain
- Distinguish blocking issues from nits
- NEVER modify code - you are a reviewer, not an author
- When the review is complete, state "REVIEW COMPLETE" and stop
"""

READ_ONLY_TOOL_NAMES = {"read_file", "list_directory", "search_files"}


class CodeReviewHarness(BaseHarness):
    harness_id = "code_review"
    description = "Review-focused: produces structured review reports, read-only"

    def __init__(self, tool_definitions: list[dict[str, Any]] | None = None) -> None:
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
            temperature=0.0,  # Deterministic reviews
            max_tokens=6144,
        )

    def should_stop(self, session: AgentSession, response: ChatResponse) -> bool:
        if response.text and "REVIEW COMPLETE" in response.text.upper():
            return True
        return len(response.tool_calls) == 0

    def get_system_prompt(self) -> str:
        return CODE_REVIEW_SYSTEM_PROMPT
