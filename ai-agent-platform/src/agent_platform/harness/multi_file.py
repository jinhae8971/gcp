"""Multi-file harness - large-scale refactoring agent.

Optimized for changes that span many files (renaming APIs, introducing
new abstractions, migrating patterns across a codebase).

Key differences from ReAct:
  - Maintains an explicit change manifest (list of files touched + intent)
  - Forces "discovery → plan → execute → verify" phases
  - Uses higher max_tokens to keep context of all related files
  - Encourages batched edits and diff-style thinking

Prompt strategy is similar to Plan-Execute but the plan tracks *files*
and *edit intents* rather than steps.
"""

from __future__ import annotations

import json
from typing import Any

from agent_platform.core.session import AgentSession
from agent_platform.harness.base import BaseHarness, LLMRequest
from agent_platform.models.providers.base import ChatResponse

MULTI_FILE_SYSTEM_PROMPT = """\
You are a Senior Refactoring Specialist handling a multi-file change.

## Phased Workflow

### Phase 1: Discovery
- Use `search_files` to find all occurrences of the pattern being changed
- Use `read_file` on each affected file to understand context
- Build a mental model of the call graph and dependencies

### Phase 2: Change Manifest
Produce a JSON manifest of all files to touch:
```json
{{"manifest": [
  {{"path": "src/module/a.py", "intent": "rename function X to Y", "status": "pending"}},
  {{"path": "src/module/b.py", "intent": "update imports", "status": "pending"}},
  {{"path": "tests/test_a.py", "intent": "update assertion strings", "status": "pending"}}
]}}
```

### Phase 3: Execution
- Work through the manifest in dependency order
- After each edit, mark the entry as "done"
- Update the manifest if you discover new files during execution

### Phase 4: Verification
- Run tests (`execute_command`) to confirm nothing broke
- Grep for leftover old names/patterns
- Summarize what changed and why

## Rules
- Never start editing before the manifest is complete
- Edits should be minimal and targeted (no unrelated cleanup)
- If you discover a file mid-execution, add it to the manifest first
- Always verify at the end
- When all manifest entries are "done" and verification passes, state "REFACTOR COMPLETE"
"""


class MultiFileHarness(BaseHarness):
    harness_id = "multi_file"
    description = "Multi-file refactoring: discovery, manifest, execute, verify"

    def __init__(self, tool_definitions: list[dict[str, Any]] | None = None) -> None:
        self._tool_definitions = tool_definitions or []
        self._manifest: list[dict[str, Any]] | None = None

    def prepare_request(self, session: AgentSession) -> LLMRequest:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.get_system_prompt()},
        ]

        if self._manifest is not None:
            # Inject current manifest state as a reminder
            manifest_ctx = (
                "Current change manifest:\n"
                f"```json\n{json.dumps({'manifest': self._manifest}, indent=2)}\n```\n"
                "Continue working through pending entries."
            )
            messages.append({"role": "system", "content": manifest_ctx})

        for msg in session.messages:
            messages.append({"role": msg.role, "content": msg.content})

        return LLMRequest(
            messages=messages,
            tool_definitions=self._tool_definitions,
            temperature=0.0,
            max_tokens=8192,  # Larger context for multi-file state
        )

    def should_stop(self, session: AgentSession, response: ChatResponse) -> bool:
        # Extract manifest on first appearance
        if self._manifest is None and response.text:
            extracted = self._extract_manifest(response.text)
            if extracted:
                self._manifest = extracted
                return False  # Continue to execution

        # Track completion sentinel
        if response.text and "REFACTOR COMPLETE" in response.text.upper():
            return True

        # Otherwise continue while there are tool calls
        return len(response.tool_calls) == 0

    def _extract_manifest(self, text: str) -> list[dict[str, Any]] | None:
        """Parse `{"manifest": [...]}` block from text."""
        try:
            start = text.find('{"manifest"')
            if start == -1:
                start = text.find('{ "manifest"')
            if start == -1:
                return None
            # Find matching closing brace by tracking depth
            depth = 0
            end = start
            for i in range(start, len(text)):
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end <= start:
                return None
            data = json.loads(text[start:end])
            return data.get("manifest", [])
        except (json.JSONDecodeError, KeyError):
            return None

    def get_system_prompt(self) -> str:
        return MULTI_FILE_SYSTEM_PROMPT
