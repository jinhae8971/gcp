"""Tests for notification dispatcher and Slack backend."""

from __future__ import annotations

import pytest

from agent_platform.notifier.base import (
    InMemoryBackend,
    LogBackend,
    Notification,
    NotificationBackend,
    NotificationDispatcher,
    Severity,
)
from agent_platform.notifier.slack import SlackWebhookBackend


class FailingBackend(NotificationBackend):
    name = "failing"

    async def send(self, notification: Notification) -> None:
        raise RuntimeError("simulated outage")


class TestNotificationDispatcher:
    @pytest.mark.asyncio
    async def test_dispatch_to_all(self):
        backend_a = InMemoryBackend()
        backend_b = InMemoryBackend()
        dispatcher = NotificationDispatcher([backend_a, backend_b])

        note = Notification(
            title="Budget alert",
            message="team-a at 85%",
            severity=Severity.WARNING,
            source="budget",
            data={"team": "team-a", "ratio": 0.85},
        )
        failed = await dispatcher.dispatch(note)
        assert failed == []
        assert len(backend_a.received) == 1
        assert len(backend_b.received) == 1
        assert backend_a.received[0].title == "Budget alert"

    @pytest.mark.asyncio
    async def test_failure_isolated(self):
        good = InMemoryBackend()
        dispatcher = NotificationDispatcher([good, FailingBackend()])
        note = Notification(title="x", message="y")
        failed = await dispatcher.dispatch(note)
        assert failed == ["failing"]
        assert len(good.received) == 1

    @pytest.mark.asyncio
    async def test_no_backends_ok(self):
        dispatcher = NotificationDispatcher()
        result = await dispatcher.dispatch(Notification(title="x", message="y"))
        assert result == []

    @pytest.mark.asyncio
    async def test_log_backend_runs(self):
        # Just verify it doesn't crash
        dispatcher = NotificationDispatcher([LogBackend()])
        await dispatcher.dispatch(Notification(title="t", message="m"))

    def test_register_adds_backend(self):
        dispatcher = NotificationDispatcher()
        dispatcher.register(InMemoryBackend())
        assert dispatcher.backends() == ["memory"]


class TestNotification:
    def test_as_dict(self):
        note = Notification(
            title="t", message="m",
            severity=Severity.ERROR,
            source="eval",
            data={"k": "v"},
        )
        d = note.as_dict()
        assert d["severity"] == "error"
        assert d["data"] == {"k": "v"}


class TestSlackWebhookBackend:
    def test_rejects_bad_url(self):
        with pytest.raises(ValueError):
            SlackWebhookBackend("http://insecure.example.com/hook")
        with pytest.raises(ValueError):
            SlackWebhookBackend("")

    def test_payload_formatting(self):
        backend = SlackWebhookBackend("https://hooks.slack.com/fake")
        note = Notification(
            title="Budget alert",
            message="Team hit 90%",
            severity=Severity.WARNING,
            source="budget",
            data={"team": "backend"},
        )
        payload = backend.build_payload(note)
        assert payload["username"] == "agent-platform"
        attachment = payload["attachments"][0]
        assert "Budget alert" in attachment["title"]
        assert attachment["color"] == "#daa038"
        assert attachment["fields"][0]["title"] == "team"

    def test_payload_with_channel(self):
        backend = SlackWebhookBackend(
            "https://hooks.slack.com/fake",
            channel="#alerts",
        )
        note = Notification(title="t", message="m")
        payload = backend.build_payload(note)
        assert payload["channel"] == "#alerts"

    def test_severity_color_mapping(self):
        backend = SlackWebhookBackend("https://hooks.slack.com/fake")
        for severity, expected in [
            (Severity.INFO, "#2eb886"),
            (Severity.ERROR, "#cc2d2d"),
            (Severity.CRITICAL, "#7a0000"),
        ]:
            note = Notification(title="x", message="y", severity=severity)
            payload = backend.build_payload(note)
            assert payload["attachments"][0]["color"] == expected
