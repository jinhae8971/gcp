"""Tests for Phase 4 security primitives: auth, rate_limit, budget, sandbox."""

from __future__ import annotations

import asyncio
import time

import pytest

from agent_platform.security.auth import (
    AuthService,
    InvalidTokenError,
    PermissionDenied,
    Principal,
    RBAC,
)
from agent_platform.security.budget import (
    BudgetExceeded,
    BudgetState,
    BudgetTracker,
)
from agent_platform.security.rate_limit import (
    BucketPolicy,
    RateLimiter,
    TieredRateLimiter,
)
from agent_platform.security.sandbox_policy import (
    BUILTIN_PROFILES,
    NetworkPolicy,
    SandboxTier,
    get_profile,
    select_profile,
)


# ── Auth ────────────────────────────────────────────────


class TestAuthService:
    def test_roundtrip(self):
        svc = AuthService(secret="secret1")
        token = svc.issue_token("alice", roles=["dev"], tenant_id="t1")
        principal = svc.verify_token(token)
        assert principal.subject == "alice"
        assert principal.roles == ["dev"]
        assert principal.tenant_id == "t1"

    def test_extra_claims_preserved(self):
        svc = AuthService(secret="secret1")
        token = svc.issue_token("bob", extra_claims={"team": "backend"})
        principal = svc.verify_token(token)
        assert principal.claims["team"] == "backend"

    def test_invalid_signature(self):
        svc_a = AuthService(secret="secret1")
        svc_b = AuthService(secret="secret2")
        token = svc_a.issue_token("alice")
        with pytest.raises(InvalidTokenError, match="signature"):
            svc_b.verify_token(token)

    def test_malformed_token(self):
        svc = AuthService(secret="secret1")
        with pytest.raises(InvalidTokenError, match="malformed"):
            svc.verify_token("not-a-token")

    def test_expired_token(self):
        svc = AuthService(secret="secret1", default_ttl=1)
        token = svc.issue_token("alice", ttl_seconds=-10)
        with pytest.raises(InvalidTokenError, match="expired"):
            svc.verify_token(token)

    def test_rejects_empty_secret(self):
        with pytest.raises(ValueError):
            AuthService(secret="")


class TestRBAC:
    def test_grant_and_check(self):
        rbac = RBAC()
        rbac.grant("dev", "session:create")
        p = Principal(subject="alice", roles=["dev"])
        rbac.check(p, "session:create")  # should not raise

    def test_wildcard_all(self):
        rbac = RBAC()
        rbac.grant("admin", "*")
        p = Principal(subject="a", roles=["admin"])
        assert rbac.allowed(p, "session:delete")
        assert rbac.allowed(p, "eval:run")

    def test_resource_wildcard(self):
        rbac = RBAC()
        rbac.grant("dev", "session:*")
        p = Principal(subject="a", roles=["dev"])
        assert rbac.allowed(p, "session:create")
        assert rbac.allowed(p, "session:delete")
        assert not rbac.allowed(p, "eval:run")

    def test_denied_raises(self):
        rbac = RBAC()
        rbac.grant("viewer", "session:read")
        p = Principal(subject="a", roles=["viewer"])
        with pytest.raises(PermissionDenied):
            rbac.check(p, "session:create")

    def test_revoke(self):
        rbac = RBAC()
        rbac.grant("dev", "session:create")
        rbac.revoke("dev", "session:create")
        p = Principal(subject="a", roles=["dev"])
        assert not rbac.allowed(p, "session:create")


# ── Rate Limiter ────────────────────────────────────────


class TestRateLimiter:
    def test_allows_until_capacity(self):
        limiter = RateLimiter(capacity=3, refill_per_second=0)
        assert limiter.acquire_sync("alice")
        assert limiter.acquire_sync("alice")
        assert limiter.acquire_sync("alice")
        assert not limiter.acquire_sync("alice")

    def test_refills_over_time(self):
        limiter = RateLimiter(capacity=2, refill_per_second=1000)
        assert limiter.acquire_sync("bob")
        assert limiter.acquire_sync("bob")
        assert not limiter.acquire_sync("bob")
        time.sleep(0.01)
        assert limiter.acquire_sync("bob")

    def test_separate_keys_are_independent(self):
        limiter = RateLimiter(capacity=1, refill_per_second=0)
        assert limiter.acquire_sync("alice")
        assert not limiter.acquire_sync("alice")
        assert limiter.acquire_sync("bob")

    def test_reset(self):
        limiter = RateLimiter(capacity=1, refill_per_second=0)
        limiter.acquire_sync("alice")
        limiter.reset("alice")
        assert limiter.acquire_sync("alice")

    def test_invalid_config(self):
        with pytest.raises(ValueError):
            RateLimiter(capacity=0, refill_per_second=1)

    @pytest.mark.asyncio
    async def test_async_acquire(self):
        limiter = RateLimiter(capacity=2, refill_per_second=0)
        assert await limiter.acquire("k")
        assert await limiter.acquire("k")
        assert not await limiter.acquire("k")


class TestTieredRateLimiter:
    @pytest.mark.asyncio
    async def test_tier_resolution(self):
        limiter = TieredRateLimiter(
            tiers={
                "free": BucketPolicy(capacity=2, refill_per_second=0),
                "pro": BucketPolicy(capacity=10, refill_per_second=0),
            },
            default_tier="free",
        )
        assert limiter.tier_for_roles(["pro"]) == "pro"
        assert limiter.tier_for_roles(["unknown"]) == "free"

    @pytest.mark.asyncio
    async def test_pro_gets_more_than_free(self):
        limiter = TieredRateLimiter(
            tiers={
                "free": BucketPolicy(capacity=1, refill_per_second=0),
                "pro": BucketPolicy(capacity=5, refill_per_second=0),
            },
            default_tier="free",
        )
        # Free tier user
        assert await limiter.acquire("alice", roles=["free"])
        assert not await limiter.acquire("alice", roles=["free"])
        # Pro tier user
        for _ in range(5):
            assert await limiter.acquire("bob", roles=["pro"])
        assert not await limiter.acquire("bob", roles=["pro"])


# ── Budget Tracker ──────────────────────────────────────


class TestBudgetTracker:
    def test_healthy_at_start(self):
        t = BudgetTracker()
        t.set_budget("team-a", monthly_limit_usd=100)
        event = t.record_spend("team-a", 10.0)
        assert event.state == BudgetState.HEALTHY
        assert event.ratio == 0.1

    def test_alert_threshold_crossed(self):
        t = BudgetTracker()
        t.set_budget("team-a", monthly_limit_usd=100, alert_ratio=0.8)
        e1 = t.record_spend("team-a", 50.0)
        assert e1.state == BudgetState.HEALTHY
        e2 = t.record_spend("team-a", 35.0)
        assert e2.state == BudgetState.ALERT
        assert e2.threshold_crossed is True

    def test_hard_stop(self):
        t = BudgetTracker()
        t.set_budget("team-a", monthly_limit_usd=10, hard_stop=True)
        t.record_spend("team-a", 8.0)
        with pytest.raises(BudgetExceeded):
            t.record_spend("team-a", 5.0)

    def test_soft_limit_allows_overspend(self):
        t = BudgetTracker()
        t.set_budget("team-a", monthly_limit_usd=10, hard_stop=False)
        t.record_spend("team-a", 8.0)
        event = t.record_spend("team-a", 5.0)
        assert event.state == BudgetState.EXCEEDED

    def test_get_status(self):
        t = BudgetTracker()
        t.set_budget("team-a", monthly_limit_usd=100)
        t.record_spend("team-a", 42.0)
        status = t.get_status("team-a")
        assert status.spent_usd == 42.0
        assert status.limit_usd == 100
        assert status.ratio == 0.42

    def test_reset_clears_period(self):
        t = BudgetTracker()
        t.set_budget("team-a", monthly_limit_usd=100)
        t.record_spend("team-a", 50.0)
        t.reset("team-a")
        status = t.get_status("team-a")
        assert status.spent_usd == 0.0

    def test_rejects_bad_config(self):
        t = BudgetTracker()
        with pytest.raises(ValueError):
            t.set_budget("x", monthly_limit_usd=-1)
        with pytest.raises(ValueError):
            t.set_budget("x", monthly_limit_usd=10, alert_ratio=1.5)


# ── Sandbox Policy ──────────────────────────────────────


class TestSandboxPolicy:
    def test_builtin_profiles_exist(self):
        for name in ("dev", "standard", "hardened", "isolated_vm"):
            assert name in BUILTIN_PROFILES

    def test_hardened_has_no_network(self):
        p = get_profile("hardened")
        assert p.tier == SandboxTier.GVISOR
        assert p.network == NetworkPolicy.NONE
        assert "mount" in p.blocked_syscalls

    def test_unknown_profile_raises(self):
        with pytest.raises(KeyError):
            get_profile("nope")

    def test_select_profile_maps_tier(self):
        assert select_profile("gvisor").name == "hardened"
        assert select_profile("container").name == "standard"
        assert select_profile("local").name == "dev"
        assert select_profile("unknown-tier").name == "standard"

    def test_serialization(self):
        p = get_profile("standard")
        d = p.to_dict()
        assert d["tier"] == "container"
        assert "limits" in d
        assert d["limits"]["memory_mb"] == 2048
