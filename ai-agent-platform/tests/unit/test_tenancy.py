"""Tests for Phase 5 tenancy: tenant scoping, team configs, usage reports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_platform.core.session import AgentSession
from agent_platform.core.session_store import InMemorySessionStore
from agent_platform.tenancy.tenant import (
    CrossTenantAccess,
    Tenant,
    TenantRegistry,
    TenantScopedSessionStore,
    UnknownTenant,
)
from agent_platform.tenancy.team_config import (
    TeamConfig,
    TeamConfigRegistry,
    resolve_session_defaults,
)
from agent_platform.tenancy.usage_report import (
    generate_usage_report,
)


# ── TenantRegistry ──────────────────────────────────────


class TestTenantRegistry:
    def test_register_and_get(self):
        reg = TenantRegistry()
        reg.register(Tenant(tenant_id="t1", name="Acme"))
        assert reg.get("t1").name == "Acme"

    def test_unknown_raises(self):
        reg = TenantRegistry()
        with pytest.raises(UnknownTenant):
            reg.get("nope")

    def test_list_and_remove(self):
        reg = TenantRegistry()
        reg.register(Tenant(tenant_id="t1", name="A"))
        reg.register(Tenant(tenant_id="t2", name="B"))
        assert len(reg.list()) == 2
        reg.remove("t1")
        assert reg.exists("t2")
        assert not reg.exists("t1")


# ── TenantScopedSessionStore ────────────────────────────


class TestTenantScopedSessionStore:
    @pytest.mark.asyncio
    async def test_save_stamps_tenant(self):
        inner = InMemorySessionStore()
        store = TenantScopedSessionStore(inner, tenant_id="t1")
        session = AgentSession(session_id="s1", model_id="m", harness_id="react")
        await store.save(session)
        reloaded = await inner.load("s1")
        assert reloaded.metadata["tenant_id"] == "t1"

    @pytest.mark.asyncio
    async def test_load_filters_by_tenant(self):
        inner = InMemorySessionStore()
        s = AgentSession(session_id="s1", model_id="m", harness_id="react")
        s.metadata["tenant_id"] = "t1"
        await inner.save(s)

        scoped = TenantScopedSessionStore(inner, tenant_id="t2")
        with pytest.raises(CrossTenantAccess):
            await scoped.load("s1")

    @pytest.mark.asyncio
    async def test_load_missing_returns_none(self):
        inner = InMemorySessionStore()
        scoped = TenantScopedSessionStore(inner, tenant_id="t1")
        assert await scoped.load("nope") is None

    @pytest.mark.asyncio
    async def test_list_ids_only_returns_own_tenant(self):
        inner = InMemorySessionStore()
        s1 = AgentSession(session_id="s1", model_id="m")
        s1.metadata["tenant_id"] = "t1"
        s2 = AgentSession(session_id="s2", model_id="m")
        s2.metadata["tenant_id"] = "t2"
        await inner.save(s1)
        await inner.save(s2)

        store_t1 = TenantScopedSessionStore(inner, tenant_id="t1")
        ids = await store_t1.list_ids()
        assert ids == ["s1"]

    @pytest.mark.asyncio
    async def test_delete_rejects_cross_tenant(self):
        inner = InMemorySessionStore()
        s = AgentSession(session_id="s1", model_id="m")
        s.metadata["tenant_id"] = "t1"
        await inner.save(s)

        scoped = TenantScopedSessionStore(inner, tenant_id="t2")
        with pytest.raises(CrossTenantAccess):
            await scoped.delete("s1")

    @pytest.mark.asyncio
    async def test_save_cannot_steal_session(self):
        inner = InMemorySessionStore()
        s = AgentSession(session_id="s1", model_id="m")
        s.metadata["tenant_id"] = "t1"
        await inner.save(s)

        # Attempt to resave under wrong tenant
        scoped = TenantScopedSessionStore(inner, tenant_id="t2")
        with pytest.raises(CrossTenantAccess):
            await scoped.save(s)


# ── TeamConfig ──────────────────────────────────────────


class TestTeamConfigRegistry:
    def test_register_and_get(self):
        reg = TeamConfigRegistry()
        reg.register(TeamConfig(
            team_id="backend",
            default_model="claude-sonnet-4",
            members=["alice", "bob"],
        ))
        cfg = reg.get("backend")
        assert cfg.default_model == "claude-sonnet-4"
        assert cfg.has_member("alice")

    def test_find_by_member(self):
        reg = TeamConfigRegistry()
        reg.register(TeamConfig(team_id="backend", members=["alice"]))
        reg.register(TeamConfig(team_id="frontend", members=["carol"]))
        assert reg.find_by_member("alice").team_id == "backend"
        assert reg.find_by_member("carol").team_id == "frontend"
        assert reg.find_by_member("nobody") is None

    def test_load_file_json(self, tmp_path: Path):
        path = tmp_path / "teams.json"
        path.write_text(json.dumps({
            "teams": {
                "backend": {
                    "default_model": "claude-sonnet-4",
                    "default_harness": "plan_execute",
                    "tools_enabled": ["read_file", "write_file"],
                    "budget_monthly_usd": 500,
                    "members": ["alice"],
                },
                "frontend": {
                    "default_harness": "react",
                    "members": ["bob"],
                },
            }
        }))

        reg = TeamConfigRegistry()
        n = reg.load_file(str(path))
        assert n == 2
        assert reg.get("backend").budget_monthly_usd == 500
        assert reg.get("frontend").default_harness == "react"

    def test_load_missing_file_returns_zero(self):
        reg = TeamConfigRegistry()
        assert reg.load_file("/nonexistent/teams.json") == 0

    def test_resolve_defaults_with_team(self):
        team = TeamConfig(team_id="backend", default_model="gpt-4o", default_harness="plan_execute")
        model, harness = resolve_session_defaults(team, "claude-sonnet-4")
        assert model == "gpt-4o"
        assert harness == "plan_execute"

    def test_resolve_defaults_without_team(self):
        model, harness = resolve_session_defaults(None, "claude-sonnet-4")
        assert model == "claude-sonnet-4"
        assert harness == "react"


# ── Usage Report ────────────────────────────────────────


def _session(team_id: str, model: str, harness: str, in_tok: int, out_tok: int, cost: float) -> AgentSession:
    s = AgentSession(model_id=model, harness_id=harness)
    s.metadata["team_id"] = team_id
    s.total_input_tokens = in_tok
    s.total_output_tokens = out_tok
    s.total_cost_usd = cost
    return s


class TestUsageReport:
    def test_group_by_team(self):
        sessions = [
            _session("backend", "claude-sonnet-4", "react", 100, 200, 0.10),
            _session("backend", "gpt-4o", "plan_execute", 50, 150, 0.05),
            _session("frontend", "claude-sonnet-4", "react", 30, 60, 0.02),
        ]
        report = generate_usage_report(sessions, group_by="team")
        assert report.total_sessions == 3
        assert len(report.buckets) == 2

        backend = next(b for b in report.buckets if b.key == "backend")
        assert backend.sessions == 2
        assert backend.cost_usd == pytest.approx(0.15)
        assert backend.input_tokens == 150

    def test_group_by_model(self):
        sessions = [
            _session("t", "claude-sonnet-4", "react", 10, 10, 0.01),
            _session("t", "claude-sonnet-4", "react", 20, 20, 0.02),
            _session("t", "gpt-4o", "react", 5, 5, 0.01),
        ]
        report = generate_usage_report(sessions, group_by="model")
        models = {b.key: b for b in report.buckets}
        assert models["claude-sonnet-4"].sessions == 2
        assert models["gpt-4o"].sessions == 1

    def test_buckets_sorted_by_cost(self):
        sessions = [
            _session("cheap", "m", "r", 1, 1, 0.01),
            _session("expensive", "m", "r", 1, 1, 1.0),
        ]
        report = generate_usage_report(sessions, group_by="team")
        assert report.buckets[0].key == "expensive"

    def test_invalid_group_by(self):
        with pytest.raises(ValueError):
            generate_usage_report([], group_by="bogus")

    def test_json_and_csv_output(self):
        sessions = [_session("t", "m", "r", 100, 50, 0.15)]
        report = generate_usage_report(sessions, group_by="team")
        j = report.to_json()
        assert "total_sessions" in j
        assert "0.15" in j

        csv_out = report.to_csv()
        assert "key,sessions" in csv_out
        assert "t," in csv_out
