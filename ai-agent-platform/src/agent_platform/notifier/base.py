"""Notification primitives and dispatcher.

Notifications are structured events (not just strings) so that different
backends can format them appropriately. The dispatcher fans out to every
registered backend; individual failures are isolated so one flaky sink
doesn't block the others.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Notification:
    title: str
    message: str
    severity: Severity = Severity.INFO
    source: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "message": self.message,
            "severity": self.severity.value,
            "source": self.source,
            "data": dict(self.data),
            "timestamp": self.timestamp,
        }


class NotificationBackend(ABC):
    name: str = "base"

    @abstractmethod
    async def send(self, notification: Notification) -> None: ...


class LogBackend(NotificationBackend):
    """Sink to structlog. Always enabled as the fallback backend."""

    name = "log"

    async def send(self, notification: Notification) -> None:
        logger.info(
            "notification",
            title=notification.title,
            severity=notification.severity.value,
            source=notification.source,
            message=notification.message,
            **notification.data,
        )


class InMemoryBackend(NotificationBackend):
    """Test / dev backend that collects notifications in a list."""

    name = "memory"

    def __init__(self) -> None:
        self.received: list[Notification] = []

    async def send(self, notification: Notification) -> None:
        self.received.append(notification)


class NotificationDispatcher:
    """Fans out a Notification to every registered backend."""

    def __init__(self, backends: list[NotificationBackend] | None = None) -> None:
        self._backends: list[NotificationBackend] = list(backends or [])

    def register(self, backend: NotificationBackend) -> None:
        self._backends.append(backend)

    def backends(self) -> list[str]:
        return [b.name for b in self._backends]

    async def dispatch(self, notification: Notification) -> list[str]:
        """Send to all backends. Returns the list of backend names that failed."""
        async def _safe(b: NotificationBackend) -> str | None:
            try:
                await b.send(notification)
                return None
            except Exception as exc:
                logger.warning(
                    "notifier.backend_failed",
                    backend=b.name,
                    error=str(exc),
                )
                return b.name

        if not self._backends:
            return []

        results = await asyncio.gather(*(_safe(b) for b in self._backends))
        return [r for r in results if r]
