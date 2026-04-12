"""Tests for Phase 3 harness implementations."""

import pytest

from agent_platform.core.session import AgentSession
from agent_platform.harness.architect import ArchitectHarness, READ_ONLY_TOOL_NAMES as ARCH_READ_ONLY
from agent_platform.harness.code_review import CodeReviewHarness
from agent_platform.harness.debate import DebateHarness, MAX_DEBATE_ROUNDS
from agent_platform.harness.human_in_loop import (
    ApprovalDecision,
    ApprovalRequest,
    HumanInLoopHarness,
    RISKY_TOOLS,
)
from agent_platform.harness.multi_file import MultiFileHarness
from agent_platform.models.providers.base import ChatResponse, UsageInfo


def _make_response(text: str = "", tool_calls: list | None = None) -> ChatResponse:
    return ChatResponse(
        text=text,
        tool_calls=tool_calls or [],
        usage=UsageInfo(input_tokens=10, output_tokens=20, cost_usd=0.001),
        model="test-model",
    )


def _sample_tools() -> list[dict]:
    return [
        {"name": "read_file", "description": "Read a file", "input_schema": {}},
        {"name": "write_file", "description": "Write a file", "input_schema": {}},
        {"name": "execute_command", "description": "Run shell", "input_schema": {}},
        {"name": "search_files", "description": "Search", "input_schema": {}},
        {"name": "list_directory", "description": "List dir", "input_schema": {}},
    ]


# ── Architect ─────────────────────────────────────────────

class TestArchitectHarness:
    def test_metadata(self):
        h = ArchitectHarness()
        assert h.harness_id == "architect"
        assert "design" in h.description.lower()

    def test_filters_to_read_only_tools(self):
        h = ArchitectHarness(tool_definitions=_sample_tools())
        tool_names = {t["name"] for t in h._tool_definitions}
        assert tool_names == ARCH_READ_ONLY
        assert "write_file" not in tool_names
        assert "execute_command" not in tool_names

    def test_prepare_request(self):
        h = ArchitectHarness(tool_definitions=_sample_tools())
        session = AgentSession(model_id="test", harness_id="architect")
        session.add_message("user", "Design a rate limiter")

        req = h.prepare_request(session)
        assert len(req.messages) == 2  # system + user
        assert req.messages[0]["role"] == "system"
        assert "Architect" in req.messages[0]["content"]
        assert req.temperature == 0.2
        assert req.max_tokens == 8192

    def test_should_stop_on_design_complete(self):
        h = ArchitectHarness()
        session = AgentSession(model_id="test", harness_id="architect")
        response = _make_response(text="Here is the design... DESIGN COMPLETE")
        assert h.should_stop(session, response) is True

    def test_should_stop_case_insensitive(self):
        h = ArchitectHarness()
        session = AgentSession(model_id="test", harness_id="architect")
        response = _make_response(text="design complete")
        assert h.should_stop(session, response) is True

    def test_should_not_stop_when_tool_calls(self):
        h = ArchitectHarness()
        session = AgentSession(model_id="test", harness_id="architect")
        response = _make_response(
            text="Let me check the file",
            tool_calls=[{"name": "read_file", "arguments": {"path": "a.py"}}],
        )
        assert h.should_stop(session, response) is False


# ── Code Review ───────────────────────────────────────────

class TestCodeReviewHarness:
    def test_metadata(self):
        h = CodeReviewHarness()
        assert h.harness_id == "code_review"

    def test_filters_to_read_only(self):
        h = CodeReviewHarness(tool_definitions=_sample_tools())
        tool_names = {t["name"] for t in h._tool_definitions}
        assert "write_file" not in tool_names
        assert "execute_command" not in tool_names
        assert "read_file" in tool_names

    def test_review_complete_stops(self):
        h = CodeReviewHarness()
        session = AgentSession(model_id="test", harness_id="code_review")
        response = _make_response(text="... REVIEW COMPLETE")
        assert h.should_stop(session, response) is True

    def test_system_prompt_has_scoring(self):
        h = CodeReviewHarness()
        prompt = h.get_system_prompt()
        assert "Correctness" in prompt
        assert "Security" in prompt
        assert "Maintainability" in prompt


# ── Multi-File ────────────────────────────────────────────

class TestMultiFileHarness:
    def test_metadata(self):
        h = MultiFileHarness()
        assert h.harness_id == "multi_file"

    def test_extract_manifest(self):
        h = MultiFileHarness()
        text = '''
        Here is my plan:
        {"manifest": [
          {"path": "a.py", "intent": "rename", "status": "pending"},
          {"path": "b.py", "intent": "update imports", "status": "pending"}
        ]}
        '''
        manifest = h._extract_manifest(text)
        assert manifest is not None
        assert len(manifest) == 2
        assert manifest[0]["path"] == "a.py"

    def test_extract_manifest_nested(self):
        h = MultiFileHarness()
        text = '{"manifest": [{"path": "a", "details": {"foo": "bar"}, "status": "pending"}]}'
        manifest = h._extract_manifest(text)
        assert manifest is not None
        assert len(manifest) == 1

    def test_extract_manifest_missing(self):
        h = MultiFileHarness()
        assert h._extract_manifest("no manifest here") is None

    def test_should_stop_with_manifest_in_first_response(self):
        h = MultiFileHarness()
        session = AgentSession(model_id="test", harness_id="multi_file")
        response = _make_response(
            text='{"manifest": [{"path": "a.py", "intent": "x", "status": "pending"}]}',
        )
        # First response sets manifest and continues
        assert h.should_stop(session, response) is False
        assert h._manifest is not None

    def test_refactor_complete_stops(self):
        h = MultiFileHarness()
        h._manifest = [{"path": "a.py", "status": "done"}]
        session = AgentSession(model_id="test", harness_id="multi_file")
        response = _make_response(text="REFACTOR COMPLETE")
        assert h.should_stop(session, response) is True


# ── Debate ────────────────────────────────────────────────

class TestDebateHarness:
    def test_metadata(self):
        h = DebateHarness()
        assert h.harness_id == "debate"

    def test_alternating_prompts(self):
        h = DebateHarness()
        session = AgentSession(model_id="test", harness_id="debate")
        session.add_message("user", "Should we use REST or GraphQL?")

        # Round 0 → Proposer
        req = h.prepare_request(session)
        assert "Proposer" in req.messages[0]["content"]

        # Advance to round 1 → Critic
        h._round = 1
        req = h.prepare_request(session)
        assert "Critic" in req.messages[0]["content"]

        # Advance to judge round
        h._round = MAX_DEBATE_ROUNDS
        req = h.prepare_request(session)
        assert "Judge" in req.messages[0]["content"]

    def test_consensus_reached_twice_jumps_to_judge(self):
        h = DebateHarness()
        session = AgentSession(model_id="test", harness_id="debate")

        # First consensus (from proposer)
        h._round = 0
        response = _make_response(text="Agreed. CONSENSUS REACHED")
        h.should_stop(session, response)
        assert h._consensus_reached is True

        # Second consensus (from critic) → jump to judge
        response2 = _make_response(text="Yes, CONSENSUS REACHED")
        h.should_stop(session, response2)
        assert h._round == MAX_DEBATE_ROUNDS

    def test_judge_round_stops(self):
        h = DebateHarness()
        h._round = MAX_DEBATE_ROUNDS
        session = AgentSession(model_id="test", harness_id="debate")
        response = _make_response(text="DEBATE COMPLETE")
        assert h.should_stop(session, response) is True


# ── Human-in-the-Loop ─────────────────────────────────────

class TestHumanInLoopHarness:
    def test_metadata(self):
        h = HumanInLoopHarness()
        assert h.harness_id == "human_in_loop"

    @pytest.mark.asyncio
    async def test_safe_tool_auto_approved(self):
        h = HumanInLoopHarness(mode="allow_safe")
        decision = await h.check_approval("read_file", {"path": "a.py"})
        assert decision.approved is True
        assert "safe" in decision.reason

    @pytest.mark.asyncio
    async def test_risky_tool_needs_approval(self):
        approved_calls = []

        async def approve_all(req: ApprovalRequest) -> ApprovalDecision:
            approved_calls.append(req.tool_name)
            return ApprovalDecision(approved=True, reason="ok")

        h = HumanInLoopHarness(mode="allow_safe", approval_callback=approve_all)
        decision = await h.check_approval("write_file", {"path": "a.py", "content": "x"})
        assert decision.approved is True
        assert "write_file" in approved_calls

    @pytest.mark.asyncio
    async def test_risky_shell_command(self):
        captured: list[ApprovalRequest] = []

        async def capture(req: ApprovalRequest) -> ApprovalDecision:
            captured.append(req)
            return ApprovalDecision(approved=False, reason="too dangerous")

        h = HumanInLoopHarness(mode="allow_safe", approval_callback=capture)
        decision = await h.check_approval(
            "execute_command", {"command": "sudo rm -rf /"},
        )
        assert decision.approved is False
        assert len(captured) == 1
        assert "sudo" in captured[0].arguments["command"]

    @pytest.mark.asyncio
    async def test_ask_mode_always_prompts(self):
        seen: list[str] = []

        async def cb(req: ApprovalRequest) -> ApprovalDecision:
            seen.append(req.tool_name)
            return ApprovalDecision(approved=True)

        h = HumanInLoopHarness(mode="ask", approval_callback=cb)
        # Even read_file should need approval in ask mode
        await h.check_approval("read_file", {"path": "a.py"})
        assert "read_file" in seen

    @pytest.mark.asyncio
    async def test_rejection_feedback_injected(self):
        async def reject(req: ApprovalRequest) -> ApprovalDecision:
            return ApprovalDecision(approved=False, reason="no way")

        h = HumanInLoopHarness(mode="allow_safe", approval_callback=reject)
        await h.check_approval("write_file", {"path": "a.py"})

        # The next prepare_request should include rejection context
        session = AgentSession(model_id="test", harness_id="human_in_loop")
        session.add_message("user", "Write the file")
        req = h.prepare_request(session)
        joined = " ".join(m["content"] for m in req.messages)
        assert "rejected" in joined.lower()

    def test_risky_tools_listed(self):
        assert "write_file" in RISKY_TOOLS
        assert "execute_command" in RISKY_TOOLS
        assert "read_file" not in RISKY_TOOLS

    def test_task_complete_stops(self):
        h = HumanInLoopHarness()
        session = AgentSession(model_id="test", harness_id="human_in_loop")
        response = _make_response(text="All done. TASK COMPLETE")
        assert h.should_stop(session, response) is True
