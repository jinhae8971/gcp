"""Usage aggregation and reporting per tenant/team/project.

Consumes completed AgentSession objects and summarizes:
- token volume (input/output)
- cost
- session counts
- model / harness distribution

Output is JSON-friendly and can be fed to a dashboard or exported as CSV.
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from agent_platform.core.session import AgentSession


@dataclass
class UsageBucket:
    """Aggregated stats for one slice (team, project, model, etc.)."""

    key: str
    sessions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model_counts: dict[str, int] = field(default_factory=dict)
    harness_counts: dict[str, int] = field(default_factory=dict)

    def add(self, session: AgentSession) -> None:
        self.sessions += 1
        self.input_tokens += session.total_input_tokens
        self.output_tokens += session.total_output_tokens
        self.cost_usd += session.total_cost_usd
        self.model_counts[session.model_id] = self.model_counts.get(session.model_id, 0) + 1
        self.harness_counts[session.harness_id] = (
            self.harness_counts.get(session.harness_id, 0) + 1
        )

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "sessions": self.sessions,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "model_counts": dict(self.model_counts),
            "harness_counts": dict(self.harness_counts),
        }


@dataclass
class UsageReport:
    generated_at: str
    group_by: str
    buckets: list[UsageBucket]

    @property
    def total_sessions(self) -> int:
        return sum(b.sessions for b in self.buckets)

    @property
    def total_cost_usd(self) -> float:
        return sum(b.cost_usd for b in self.buckets)

    def as_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "group_by": self.group_by,
            "total_sessions": self.total_sessions,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "buckets": [b.as_dict() for b in self.buckets],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, ensure_ascii=False)

    def to_csv(self) -> str:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "key", "sessions", "input_tokens", "output_tokens",
            "total_tokens", "cost_usd",
        ])
        for b in self.buckets:
            writer.writerow([
                b.key,
                b.sessions,
                b.input_tokens,
                b.output_tokens,
                b.input_tokens + b.output_tokens,
                round(b.cost_usd, 6),
            ])
        return buf.getvalue()


# Valid group_by keys
_GROUP_KEYS = {"tenant", "team", "project", "model", "harness", "user"}


def _extract_key(session: AgentSession, group_by: str) -> str:
    if group_by == "model":
        return session.model_id or "unknown"
    if group_by == "harness":
        return session.harness_id or "unknown"
    # For identity keys, look in metadata
    return str(session.metadata.get(f"{group_by}_id", "unknown"))


def generate_usage_report(
    sessions: Iterable[AgentSession],
    group_by: str = "team",
) -> UsageReport:
    """Aggregate a batch of sessions into a usage report.

    Args:
        sessions: iterable of AgentSession objects to aggregate
        group_by: one of "tenant", "team", "project", "model", "harness", "user"
    """
    if group_by not in _GROUP_KEYS:
        raise ValueError(f"group_by must be one of {sorted(_GROUP_KEYS)}")

    buckets: dict[str, UsageBucket] = defaultdict(lambda: UsageBucket(key=""))
    for session in sessions:
        key = _extract_key(session, group_by)
        bucket = buckets[key]
        if not bucket.key:
            bucket.key = key
        bucket.add(session)

    sorted_buckets = sorted(
        buckets.values(), key=lambda b: b.cost_usd, reverse=True
    )

    return UsageReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        group_by=group_by,
        buckets=sorted_buckets,
    )
