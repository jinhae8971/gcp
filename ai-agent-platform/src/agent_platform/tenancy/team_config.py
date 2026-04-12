"""Per-team platform configuration.

Each team can override the default model, harness, prompt version, and
tool allowlist without touching global settings. Configurations are
loaded from a single JSON/YAML file (one document per team) so teams
can PR their own configs.

File layout::

    teams:
      backend:
        default_model: claude-sonnet-4-20250514
        default_harness: plan_execute
        prompt_overrides:
          architect: v3
        tools_enabled: [read_file, write_file, search_files, execute_command]
        budget_monthly_usd: 500
      frontend:
        default_model: gpt-4o
        default_harness: react
        tools_enabled: [read_file, write_file]
        budget_monthly_usd: 200

This module only handles **loading and resolving** — enforcement
happens in the API layer when a session is created.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TeamConfig:
    team_id: str
    default_model: str = ""
    default_harness: str = "react"
    prompt_overrides: dict[str, str] = field(default_factory=dict)
    tools_enabled: list[str] = field(default_factory=list)
    budget_monthly_usd: float = 0.0
    members: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "team_id": self.team_id,
            "default_model": self.default_model,
            "default_harness": self.default_harness,
            "prompt_overrides": dict(self.prompt_overrides),
            "tools_enabled": list(self.tools_enabled),
            "budget_monthly_usd": self.budget_monthly_usd,
            "members": list(self.members),
        }

    def has_member(self, subject: str) -> bool:
        return subject in self.members


class TeamConfigRegistry:
    """Loads and resolves per-team configuration overrides."""

    def __init__(self) -> None:
        self._teams: dict[str, TeamConfig] = {}

    def register(self, config: TeamConfig) -> None:
        self._teams[config.team_id] = config

    def get(self, team_id: str) -> TeamConfig | None:
        return self._teams.get(team_id)

    def find_by_member(self, subject: str) -> TeamConfig | None:
        """Return the first team that lists this subject as a member."""
        for config in self._teams.values():
            if config.has_member(subject):
                return config
        return None

    def list(self) -> list[TeamConfig]:
        return list(self._teams.values())

    def load_file(self, path: str) -> int:
        """Load teams from a JSON file (YAML support requires PyYAML).

        Returns the number of teams loaded.
        """
        p = Path(path)
        if not p.exists():
            return 0

        raw = p.read_text(encoding="utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try YAML only if available — keep core path dep-free
            try:
                import yaml  # type: ignore
                data = yaml.safe_load(raw)
            except Exception:
                return 0

        teams_data = (data or {}).get("teams", {})
        if not isinstance(teams_data, dict):
            return 0

        count = 0
        for team_id, spec in teams_data.items():
            if not isinstance(spec, dict):
                continue
            self.register(TeamConfig(
                team_id=team_id,
                default_model=spec.get("default_model", ""),
                default_harness=spec.get("default_harness", "react"),
                prompt_overrides=dict(spec.get("prompt_overrides", {})),
                tools_enabled=list(spec.get("tools_enabled", [])),
                budget_monthly_usd=float(spec.get("budget_monthly_usd", 0.0)),
                members=list(spec.get("members", [])),
            ))
            count += 1
        return count


def resolve_session_defaults(
    team: TeamConfig | None,
    global_default_model: str,
    global_default_harness: str = "react",
) -> tuple[str, str]:
    """Resolve (model, harness) defaults honoring team overrides."""
    model = team.default_model if team and team.default_model else global_default_model
    harness = team.default_harness if team else global_default_harness
    return model, harness
