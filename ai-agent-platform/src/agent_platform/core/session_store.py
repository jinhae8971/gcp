"""Session persistence backends.

Provides both in-memory (for development) and Redis-backed (for production)
session storage. Sessions are serialized as JSON for Redis storage.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from agent_platform.core.session import AgentSession, Message, SessionStatus


class BaseSessionStore(ABC):
    @abstractmethod
    async def save(self, session: AgentSession) -> None: ...

    @abstractmethod
    async def load(self, session_id: str) -> AgentSession | None: ...

    @abstractmethod
    async def delete(self, session_id: str) -> None: ...

    @abstractmethod
    async def list_ids(self) -> list[str]: ...


class InMemorySessionStore(BaseSessionStore):
    """Simple dict-backed store for development and testing."""

    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}

    async def save(self, session: AgentSession) -> None:
        self._sessions[session.session_id] = session

    async def load(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)

    async def delete(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    async def list_ids(self) -> list[str]:
        return list(self._sessions.keys())


class RedisSessionStore(BaseSessionStore):
    """Redis-backed session store for production use.

    Each session is stored as a JSON string with a configurable TTL.
    Key format: agent_platform:session:{session_id}
    """

    KEY_PREFIX = "agent_platform:session:"
    DEFAULT_TTL = 86400  # 24 hours

    def __init__(self, redis_url: str, ttl: int = DEFAULT_TTL) -> None:
        self._redis_url = redis_url
        self._ttl = ttl
        self._redis: Any = None

    async def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                from redis.asyncio import from_url
                self._redis = from_url(self._redis_url, decode_responses=True)
            except ImportError:
                raise RuntimeError(
                    "Redis support requires the 'redis' package. "
                    "Install with: pip install redis"
                )
        return self._redis

    async def save(self, session: AgentSession) -> None:
        r = await self._get_redis()
        key = f"{self.KEY_PREFIX}{session.session_id}"
        data = _serialize_session(session)
        await r.setex(key, self._ttl, json.dumps(data, ensure_ascii=False))

    async def load(self, session_id: str) -> AgentSession | None:
        r = await self._get_redis()
        key = f"{self.KEY_PREFIX}{session_id}"
        raw = await r.get(key)
        if raw is None:
            return None
        return _deserialize_session(json.loads(raw))

    async def delete(self, session_id: str) -> None:
        r = await self._get_redis()
        key = f"{self.KEY_PREFIX}{session_id}"
        await r.delete(key)

    async def list_ids(self) -> list[str]:
        r = await self._get_redis()
        keys = await r.keys(f"{self.KEY_PREFIX}*")
        prefix_len = len(self.KEY_PREFIX)
        return [k[prefix_len:] for k in keys]

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()


def _serialize_session(session: AgentSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "model_id": session.model_id,
        "harness_id": session.harness_id,
        "status": session.status.value,
        "tools_enabled": session.tools_enabled,
        "metadata": session.metadata,
        "created_at": session.created_at.isoformat(),
        "total_input_tokens": session.total_input_tokens,
        "total_output_tokens": session.total_output_tokens,
        "total_cost_usd": session.total_cost_usd,
        "messages": [
            {
                "role": msg.role,
                "content": msg.content,
                "tool_calls": msg.tool_calls,
                "tool_call_id": msg.tool_call_id,
                "metadata": msg.metadata,
                "timestamp": msg.timestamp.isoformat(),
            }
            for msg in session.messages
        ],
    }


def _deserialize_session(data: dict[str, Any]) -> AgentSession:
    messages = [
        Message(
            role=m["role"],
            content=m["content"],
            tool_calls=m.get("tool_calls", []),
            tool_call_id=m.get("tool_call_id"),
            metadata=m.get("metadata", {}),
            timestamp=datetime.fromisoformat(m["timestamp"]),
        )
        for m in data.get("messages", [])
    ]

    return AgentSession(
        session_id=data["session_id"],
        model_id=data["model_id"],
        harness_id=data.get("harness_id", "react"),
        messages=messages,
        status=SessionStatus(data.get("status", "idle")),
        tools_enabled=data.get("tools_enabled", []),
        metadata=data.get("metadata", {}),
        created_at=datetime.fromisoformat(data["created_at"]),
        total_input_tokens=data.get("total_input_tokens", 0),
        total_output_tokens=data.get("total_output_tokens", 0),
        total_cost_usd=data.get("total_cost_usd", 0.0),
    )
