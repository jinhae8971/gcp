"""Debate harness - two-agent adversarial debate.

Two specialized personas (Proposer and Critic) take turns defending
and attacking a solution until they reach consensus or a judge decides.

Pattern:
  Round 1: Proposer proposes a solution
  Round 2: Critic finds flaws
  Round 3: Proposer defends / revises
  Round 4: Critic re-evaluates
  ...
  Final:   Judge synthesizes consensus (or declares a winner)

Useful for:
  - Ambiguous design decisions
  - Security-sensitive code where adversarial thinking helps
  - Problems with multiple reasonable approaches

Note: This harness swaps personas across iterations by varying the
system prompt based on the current "round" in the session metadata.
"""

from __future__ import annotations

from typing import Any

from agent_platform.core.session import AgentSession
from agent_platform.harness.base import BaseHarness, LLMRequest
from agent_platform.models.providers.base import ChatResponse

PROPOSER_PROMPT = """\
You are the Proposer in a technical debate. Your role is to:

1. Present the strongest possible solution to the problem
2. Defend your approach against the Critic's objections
3. Revise your position ONLY if the critique is substantive
4. Acknowledge valid criticism honestly - don't defend bad ideas

## Output Format
Label each turn clearly:

**PROPOSAL (Round N)**: <your solution or defense>

**Rationale**: <why this is the right approach>

**Acknowledged concerns**: <what the critic got right, if anything>

If you are convinced the debate has reached consensus, end with:
**CONSENSUS REACHED**
"""

CRITIC_PROMPT = """\
You are the Critic in a technical debate. Your role is to:

1. Find the strongest objections to the Proposer's solution
2. Consider edge cases, failure modes, hidden costs, alternatives
3. Be rigorous but fair - only raise objections that matter
4. Concede points where the Proposer is correct

## Output Format
Label each turn clearly:

**CRITIQUE (Round N)**: <your objection or analysis>

**Failure modes**: <specific scenarios where the proposal breaks>

**Alternative**: <better approach if you have one>

If you believe the Proposer's solution is sound, end with:
**CONSENSUS REACHED**
"""

JUDGE_PROMPT = """\
You are the Judge synthesizing a debate between a Proposer and a Critic.

Review the full conversation and produce:

## Final Verdict
- **Winner**: Proposer | Critic | Consensus
- **Reasoning**: Why this side prevailed
- **Final solution**: The approach to implement (may combine both positions)
- **Remaining risks**: What to watch out for

End with "DEBATE COMPLETE"
"""

MAX_DEBATE_ROUNDS = 6  # 3 proposals + 3 critiques, then judge


class DebateHarness(BaseHarness):
    harness_id = "debate"
    description = "Two-agent adversarial debate with judge synthesis"

    def __init__(self, tool_definitions: list[dict[str, Any]] | None = None) -> None:
        self._tool_definitions = tool_definitions or []
        self._round = 0
        self._consensus_reached = False

    def prepare_request(self, session: AgentSession) -> LLMRequest:
        # Round 0, 2, 4 → Proposer
        # Round 1, 3, 5 → Critic
        # Round 6 → Judge
        system_prompt = self._select_prompt()
        round_marker = f"(Current round: {self._round + 1})"

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": f"{system_prompt}\n\n{round_marker}"},
        ]
        for msg in session.messages:
            messages.append({"role": msg.role, "content": msg.content})

        return LLMRequest(
            messages=messages,
            tool_definitions=self._tool_definitions,
            # Slight variance between personas encourages differentiation
            temperature=0.3,
            max_tokens=4096,
        )

    def _select_prompt(self) -> str:
        if self._round >= MAX_DEBATE_ROUNDS:
            return JUDGE_PROMPT
        if self._round % 2 == 0:
            return PROPOSER_PROMPT
        return CRITIC_PROMPT

    def should_stop(self, session: AgentSession, response: ChatResponse) -> bool:
        text_upper = (response.text or "").upper()

        # Judge phase always terminates the debate
        if self._round >= MAX_DEBATE_ROUNDS:
            return True

        # Early termination if both sides agree
        if "CONSENSUS REACHED" in text_upper:
            if self._consensus_reached:
                # Both sides agreed - jump to judge
                self._round = MAX_DEBATE_ROUNDS
                return False
            self._consensus_reached = True

        # Advance to next round
        self._round += 1

        # If we've hit max rounds, one more iteration for the judge
        if self._round >= MAX_DEBATE_ROUNDS:
            return False

        return False

    def get_system_prompt(self) -> str:
        return PROPOSER_PROMPT
