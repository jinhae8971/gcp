"""JWT authentication and role-based access control.

A self-contained HS256 JWT implementation using only the stdlib (hmac,
hashlib, base64, json) — no external crypto dependency. Sufficient for
internal platform auth where rotation is controlled.

For multi-party use or asymmetric signing, swap in PyJWT.

Typical usage:
    auth = AuthService(secret="change-me")
    token = auth.issue_token(subject="alice", roles=["developer", "eval:read"])
    principal = auth.verify_token(token)
    assert principal.has_role("developer")

    rbac = RBAC()
    rbac.grant("developer", permission="session:create")
    rbac.grant("admin", permission="*")
    rbac.check(principal, "session:create")  # raises PermissionError if denied
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TTL_SECONDS = 3600  # 1 hour


class AuthError(Exception):
    """Base class for authentication/authorization failures."""


class InvalidTokenError(AuthError):
    """Token is malformed, has a bad signature, or is expired."""


class PermissionDenied(AuthError):
    """Principal does not hold the required permission."""


@dataclass
class Principal:
    """An authenticated subject (user, service, agent run)."""

    subject: str
    roles: list[str] = field(default_factory=list)
    tenant_id: str = ""
    claims: dict[str, Any] = field(default_factory=dict)

    def has_role(self, role: str) -> bool:
        return role in self.roles


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


class AuthService:
    """Issues and verifies HS256 JWTs.

    Token layout: header.payload.signature (standard JWT compact form).
    Header: {"alg": "HS256", "typ": "JWT"}
    Payload: {"sub", "roles", "tenant", "iat", "exp", ...custom claims}
    """

    ALG_HEADER = {"alg": "HS256", "typ": "JWT"}

    def __init__(self, secret: str, default_ttl: int = DEFAULT_TTL_SECONDS) -> None:
        if not secret:
            raise ValueError("secret must be non-empty")
        self._secret = secret.encode("utf-8")
        self._default_ttl = default_ttl

    def issue_token(
        self,
        subject: str,
        roles: list[str] | None = None,
        tenant_id: str = "",
        ttl_seconds: int | None = None,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        payload: dict[str, Any] = {
            "sub": subject,
            "roles": roles or [],
            "tenant": tenant_id,
            "iat": now,
            "exp": now + (ttl_seconds or self._default_ttl),
        }
        if extra_claims:
            payload.update(extra_claims)

        header_b64 = _b64url_encode(
            json.dumps(self.ALG_HEADER, separators=(",", ":")).encode("utf-8")
        )
        payload_b64 = _b64url_encode(
            json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        )
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        signature = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        return f"{header_b64}.{payload_b64}.{_b64url_encode(signature)}"

    def verify_token(self, token: str) -> Principal:
        try:
            header_b64, payload_b64, sig_b64 = token.split(".")
        except ValueError:
            raise InvalidTokenError("malformed token") from None

        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise InvalidTokenError("signature mismatch")

        try:
            payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise InvalidTokenError(f"payload decode failed: {exc}") from exc

        now = int(time.time())
        exp = payload.get("exp", 0)
        if exp and exp < now:
            raise InvalidTokenError("token expired")

        return Principal(
            subject=payload.get("sub", ""),
            roles=list(payload.get("roles", [])),
            tenant_id=payload.get("tenant", ""),
            claims={
                k: v
                for k, v in payload.items()
                if k not in {"sub", "roles", "tenant", "iat", "exp"}
            },
        )


class RBAC:
    """Simple role→permissions mapping with wildcard support.

    Permission strings are colon-separated resource:action pairs
    (e.g. "session:create", "eval:read"). The wildcard "*" grants all.
    """

    def __init__(self) -> None:
        self._grants: dict[str, set[str]] = {}

    def grant(self, role: str, permission: str) -> None:
        self._grants.setdefault(role, set()).add(permission)

    def revoke(self, role: str, permission: str) -> None:
        if role in self._grants:
            self._grants[role].discard(permission)

    def permissions_for(self, role: str) -> set[str]:
        return set(self._grants.get(role, set()))

    def allowed(self, principal: Principal, permission: str) -> bool:
        for role in principal.roles:
            perms = self._grants.get(role, set())
            if "*" in perms or permission in perms:
                return True
            # Resource wildcard: "session:*" matches "session:create"
            resource = permission.split(":", 1)[0]
            if f"{resource}:*" in perms:
                return True
        return False

    def check(self, principal: Principal, permission: str) -> None:
        if not self.allowed(principal, permission):
            raise PermissionDenied(
                f"{principal.subject!r} lacks permission {permission!r}"
            )
