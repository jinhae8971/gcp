"""Tenant registry and tenant-scoped session store.

Provides strong isolation between tenants by:
  1. Recording tenant_id on every session at creation time
  2. Wrapping any BaseSessionStore to enforce tenant_id filtering
  3. Rejecting cross-tenant reads/writes with a clear error

A tenant is the coarsest boundary — typically a company or team that
shares a billing account and cannot see each others' sessions. Within a
tenant, further partitioning (projects, users) is done via metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_platform.core.session import AgentSession
from agent_platform.core.session_store import BaseSessionStore


class TenantError(Exception):
    """Base class for tenant-related errors."""


class CrossTenantAccess(TenantError):
    """Raised when a tenant tries to access another tenant's data."""


class UnknownTenant(TenantError):
    """Raised when an unregistered tenant_id is used."""


@dataclass
class Tenant:
    tenant_id: str
    name: str
    settings: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "settings": dict(self.settings),
            "enabled": self.enabled,
        }


class TenantRegistry:
    """In-memory tenant catalog. Swap for DB-backed registry in production."""

    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}

    def register(self, tenant: Tenant) -> None:
        self._tenants[tenant.tenant_id] = tenant

    def get(self, tenant_id: str) -> Tenant:
        if tenant_id not in self._tenants:
            raise UnknownTenant(f"tenant {tenant_id!r} not registered")
        return self._tenants[tenant_id]

    def exists(self, tenant_id: str) -> bool:
        return tenant_id in self._tenants

    def list(self) -> list[Tenant]:
        return list(self._tenants.values())

    def remove(self, tenant_id: str) -> None:
        self._tenants.pop(tenant_id, None)


class TenantScopedSessionStore(BaseSessionStore):
    """Wraps any session store and enforces tenant_id on all operations.

    The tenant_id is stored in session.metadata["tenant_id"]. Reads that
    don't match the expected tenant raise CrossTenantAccess.
    """

    METADATA_KEY = "tenant_id"

    def __init__(self, inner: BaseSessionStore, tenant_id: str) -> None:
        if not tenant_id:
            raise ValueError("tenant_id must be non-empty")
        self._inner = inner
        self._tenant_id = tenant_id

    @property
    def tenant_id(self) -> str:
        return self._tenant_id

    async def save(self, session: AgentSession) -> None:
        existing = session.metadata.get(self.METADATA_KEY)
        if existing and existing != self._tenant_id:
            raise CrossTenantAccess(
                f"cannot save session owned by {existing!r} into {self._tenant_id!r}"
            )
        session.metadata[self.METADATA_KEY] = self._tenant_id
        await self._inner.save(session)

    async def load(self, session_id: str) -> AgentSession | None:
        session = await self._inner.load(session_id)
        if session is None:
            return None
        owner = session.metadata.get(self.METADATA_KEY)
        if owner != self._tenant_id:
            raise CrossTenantAccess(
                f"session {session_id!r} belongs to {owner!r}, not {self._tenant_id!r}"
            )
        return session

    async def delete(self, session_id: str) -> None:
        # Only allow delete if the session already belongs to this tenant.
        session = await self._inner.load(session_id)
        if session is None:
            return
        owner = session.metadata.get(self.METADATA_KEY)
        if owner != self._tenant_id:
            raise CrossTenantAccess(
                f"cannot delete session {session_id!r} owned by {owner!r}"
            )
        await self._inner.delete(session_id)

    async def list_ids(self) -> list[str]:
        all_ids = await self._inner.list_ids()
        # Filter to sessions whose metadata.tenant_id matches
        owned: list[str] = []
        for sid in all_ids:
            sess = await self._inner.load(sid)
            if sess is not None and sess.metadata.get(self.METADATA_KEY) == self._tenant_id:
                owned.append(sid)
        return owned
