"""Human-in-the-Loop (HITL) harness.

Requires human approval for destructive or consequential tool calls.
The harness intercepts tool calls before execution and checks them
against an approval policy.

Two modes:
  - **ask**: Every call classified as risky waits for approval
  - **allow_safe**: Parallel-safe read-only tools auto-approve; risky ones wait

Approval flow:
  1. Agent emits tool call(s)
  2. Harness classifies each: auto-approve vs require-approval
  3. For require-approval calls, emit an approval request event
  4. Wait for human decision (via callback or external signal)
  5. If approved → execute; if denied → feed rejection back to the model

This harness is intended to be used with a UI or CLI that relays
approval prompts to a human operator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

from agent_platform.core.session import AgentSession
from agent_platform.harness.base import BaseHarness, LLMRequest
from agent_platform.models.providers.base import ChatResponse

HITL_SYSTEM_PROMPT = """\
You are an AI coding agent operating in Human-in-the-Loop mode.

## Operating Rules
- A human reviewer may approve or reject any tool call you make
- If a call is rejected, you will receive feedback and must adapt
- Be especially explicit about your reasoning before risky operations:
  - File writes or deletions
  - Shell commands that change state
  - Any operation that touches production data

## Transparency
Before any tool call, briefly state:
1. **Why** this call is necessary
2. **What** it will change
3. **Rollback plan** if it fails

This lets the human make an informed approval decision.

## Completion
When the task is complete, state "TASK COMPLETE".
"""

# Tool names that always require approval (destructive or state-changing)
RISKY_TOOLS = {
    "write_file",
    "execute_command",
    "delete_file",
    "run_migration",
    "deploy",
}

# Shell commands that auto-require approval even if the tool is "execute_command"
RISKY_SHELL_PATTERNS = (
    "rm ", "rm -", "sudo ", "chmod ", "chown ",
    "git push", "git reset --hard", "git clean",
    "dd ", "mkfs", "fdisk",
    "curl -X POST", "curl -X PUT", "curl -X DELETE",
    "docker rm", "docker kill",
    ">/", "> /",
)


@dataclass
class ApprovalRequest:
    """A pending tool call awaiting human decision."""

    tool_name: str
    arguments: dict[str, Any]
    reason: str = ""


@dataclass
class ApprovalDecision:
    """Human's response to an ApprovalRequest."""

    approved: bool
    reason: str = ""


ApprovalCallback = Callable[[ApprovalRequest], Awaitable[ApprovalDecision]]


async def _auto_approve(req: ApprovalRequest) -> ApprovalDecision:
    """Default callback - auto-approves everything. Replace in production."""
    return ApprovalDecision(approved=True, reason="auto-approved (no callback wired)")


class HumanInLoopHarness(BaseHarness):
    harness_id = "human_in_loop"
    description = "Requires human approval for risky tool calls"

    def __init__(
        self,
        tool_definitions: list[dict[str, Any]] | None = None,
        approval_callback: ApprovalCallback | None = None,
        mode: str = "allow_safe",
    ) -> None:
        self._tool_definitions = tool_definitions or []
        self._approval_callback = approval_callback or _auto_approve
        self._mode = mode  # "ask" | "allow_safe"
        self._pending_rejections: list[str] = []

    def prepare_request(self, session: AgentSession) -> LLMRequest:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.get_system_prompt()},
        ]

        # Inject rejection feedback if present
        if self._pending_rejections:
            rejection_text = "\n".join(
                f"- Rejected: {r}" for r in self._pending_rejections
            )
            messages.append({
                "role": "system",
                "content": (
                    "The human reviewer rejected your previous tool calls:\n"
                    f"{rejection_text}\n"
                    "Adapt your approach or ask for clarification."
                ),
            })
            self._pending_rejections = []

        for msg in session.messages:
            messages.append({"role": msg.role, "content": msg.content})

        return LLMRequest(
            messages=messages,
            tool_definitions=self._tool_definitions,
            temperature=0.0,
            max_tokens=4096,
        )

    def should_stop(self, session: AgentSession, response: ChatResponse) -> bool:
        if response.text and "TASK COMPLETE" in response.text.upper():
            return True
        return len(response.tool_calls) == 0

    async def check_approval(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> ApprovalDecision:
        """Check whether a tool call requires approval and get the decision.

        Called by the agent loop before executing any tool call when this
        harness is active.
        """
        if not self._is_risky(tool_name, arguments):
            return ApprovalDecision(approved=True, reason="auto-approved (safe)")

        request = ApprovalRequest(
            tool_name=tool_name,
            arguments=arguments,
            reason=self._explain_risk(tool_name, arguments),
        )
        decision = await self._approval_callback(request)

        if not decision.approved:
            self._pending_rejections.append(
                f"{tool_name}({arguments}): {decision.reason}"
            )

        return decision

    def _is_risky(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        if self._mode == "ask":
            return True  # Everything requires approval
        # allow_safe mode: only risky tools need approval
        if tool_name in RISKY_TOOLS:
            return True
        # Extra check: shell commands with dangerous patterns
        if tool_name == "execute_command":
            cmd = str(arguments.get("command", "")).lower()
            if any(p in cmd for p in RISKY_SHELL_PATTERNS):
                return True
        return False

    def _explain_risk(self, tool_name: str, arguments: dict[str, Any]) -> str:
        if tool_name == "write_file":
            return f"Will modify file: {arguments.get('path', 'unknown')}"
        if tool_name == "execute_command":
            return f"Will execute shell: {arguments.get('command', '')[:200]}"
        if tool_name == "delete_file":
            return f"Will DELETE file: {arguments.get('path', 'unknown')}"
        return f"Risky operation: {tool_name}"

    def get_system_prompt(self) -> str:
        return HITL_SYSTEM_PROMPT
