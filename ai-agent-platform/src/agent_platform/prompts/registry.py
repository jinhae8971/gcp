"""Prompt registry - version-controlled prompt management.

Treats prompts as managed artifacts with:
  - Immutable versioning (v1, v2, ...)
  - Environment separation (dev/staging/prod)
  - Hot-swap without redeployment
  - Performance tracking per version
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class PromptVersion:
    """An immutable snapshot of a prompt."""

    version: int
    content: str
    variables: list[str] = field(default_factory=list)  # Template variables
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    def render(self, **kwargs: str) -> str:
        """Render the prompt template with given variables."""
        result = self.content
        for key, value in kwargs.items():
            result = result.replace(f"{{{{{key}}}}}", value)
        return result


@dataclass
class PromptEntry:
    """A named prompt with version history."""

    name: str
    description: str = ""
    versions: list[PromptVersion] = field(default_factory=list)
    active_version: int = 0  # 0 = latest

    @property
    def latest(self) -> PromptVersion | None:
        return self.versions[-1] if self.versions else None

    @property
    def active(self) -> PromptVersion | None:
        if self.active_version > 0:
            for v in self.versions:
                if v.version == self.active_version:
                    return v
        return self.latest

    def add_version(self, content: str, variables: list[str] | None = None, **metadata: Any) -> PromptVersion:
        next_ver = (self.versions[-1].version + 1) if self.versions else 1
        version = PromptVersion(
            version=next_ver,
            content=content,
            variables=variables or [],
            metadata=metadata,
        )
        self.versions.append(version)
        return version


class PromptRegistry:
    """In-memory prompt registry with file-system persistence."""

    def __init__(self, templates_dir: str = "src/agent_platform/prompts/templates") -> None:
        self._prompts: dict[str, PromptEntry] = {}
        self._templates_dir = Path(templates_dir)

    def register(self, name: str, content: str, description: str = "", **kwargs: Any) -> PromptVersion:
        if name not in self._prompts:
            self._prompts[name] = PromptEntry(name=name, description=description)
        return self._prompts[name].add_version(content, **kwargs)

    def get(self, name: str, version: int | None = None) -> str | None:
        entry = self._prompts.get(name)
        if not entry:
            return None
        if version:
            for v in entry.versions:
                if v.version == version:
                    return v.content
            return None
        active = entry.active
        return active.content if active else None

    def render(self, name: str, version: int | None = None, **kwargs: str) -> str:
        entry = self._prompts.get(name)
        if not entry:
            raise KeyError(f"Prompt not found: {name}")
        target = None
        if version:
            for v in entry.versions:
                if v.version == version:
                    target = v
                    break
        else:
            target = entry.active
        if not target:
            raise KeyError(f"Prompt version not found: {name} v{version}")
        return target.render(**kwargs)

    def list_prompts(self) -> list[dict[str, Any]]:
        return [
            {
                "name": e.name,
                "description": e.description,
                "versions": len(e.versions),
                "active_version": e.active_version or (e.versions[-1].version if e.versions else 0),
            }
            for e in self._prompts.values()
        ]

    def load_from_directory(self) -> int:
        """Load prompt templates from the templates directory."""
        if not self._templates_dir.exists():
            return 0
        count = 0
        for path in sorted(self._templates_dir.glob("*.md")):
            name = path.stem
            content = path.read_text(encoding="utf-8")
            self.register(name, content, description=f"Loaded from {path.name}")
            count += 1
        return count
