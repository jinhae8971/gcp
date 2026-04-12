"""Slack webhook notification backend.

Posts to an incoming webhook URL using urllib (no httpx dependency).
Messages are formatted as Slack Block Kit attachments so severity is
color-coded in the channel.

Usage:
    backend = SlackWebhookBackend("https://hooks.slack.com/services/...")
    dispatcher.register(backend)
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any

from agent_platform.notifier.base import (
    NotificationBackend,
    Notification,
    Severity,
)

_SEVERITY_COLOR = {
    Severity.INFO: "#2eb886",      # green
    Severity.WARNING: "#daa038",   # amber
    Severity.ERROR: "#cc2d2d",     # red
    Severity.CRITICAL: "#7a0000",  # dark red
}

_SEVERITY_EMOJI = {
    Severity.INFO: ":information_source:",
    Severity.WARNING: ":warning:",
    Severity.ERROR: ":x:",
    Severity.CRITICAL: ":rotating_light:",
}


class SlackWebhookBackend(NotificationBackend):
    name = "slack"

    def __init__(
        self,
        webhook_url: str,
        username: str = "agent-platform",
        channel: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        if not webhook_url or not webhook_url.startswith("https://"):
            raise ValueError("webhook_url must be a valid https URL")
        self._url = webhook_url
        self._username = username
        self._channel = channel
        self._timeout = timeout

    def build_payload(self, notification: Notification) -> dict[str, Any]:
        emoji = _SEVERITY_EMOJI.get(notification.severity, "")
        color = _SEVERITY_COLOR.get(notification.severity, "#888888")
        fields = [
            {"title": k, "value": str(v), "short": True}
            for k, v in notification.data.items()
        ]
        payload: dict[str, Any] = {
            "username": self._username,
            "attachments": [{
                "color": color,
                "title": f"{emoji} {notification.title}".strip(),
                "text": notification.message,
                "fields": fields,
                "footer": notification.source or "agent-platform",
                "ts": _parse_ts(notification.timestamp),
            }],
        }
        if self._channel:
            payload["channel"] = self._channel
        return payload

    async def send(self, notification: Notification) -> None:
        payload = self.build_payload(notification)
        body = json.dumps(payload).encode("utf-8")
        await asyncio.to_thread(self._post, body)

    def _post(self, body: bytes) -> None:
        req = urllib.request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Slack webhook returned {resp.status}")
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Slack webhook failed: {exc}") from exc


def _parse_ts(iso_string: str) -> int:
    """Slack expects a unix timestamp. Best-effort parse."""
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(iso_string.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return 0
