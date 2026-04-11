"""Tests for agent session management."""

from agent_platform.core.session import AgentSession, SessionStatus


def test_session_creation():
    session = AgentSession(model_id="claude-sonnet-4-20250514")
    assert session.session_id
    assert session.model_id == "claude-sonnet-4-20250514"
    assert session.status == SessionStatus.IDLE
    assert session.messages == []


def test_add_message():
    session = AgentSession()
    msg = session.add_message("user", "Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"
    assert len(session.messages) == 1


def test_track_usage():
    session = AgentSession()
    session.track_usage(input_tokens=100, output_tokens=50, cost=0.001)
    session.track_usage(input_tokens=200, output_tokens=100, cost=0.002)
    assert session.total_input_tokens == 300
    assert session.total_output_tokens == 150
    assert abs(session.total_cost_usd - 0.003) < 1e-9
