"""Cost budget tracking with alert thresholds.

Tracks LLM spend per (tenant, project) bucket with configurable alert
and hard-stop thresholds. Designed to plug in alongside the ModelGateway
so cost is deducted as soon as it's observed.

Example:
    tracker = BudgetTracker()
    tracker.set_budget("team-a", monthly_limit_usd=100.0, alert_ratio=0.8)
    event = tracker.record_spend("team-a", amount_usd=2.35)
    if event.state == BudgetState.EXCEEDED:
        raise RuntimeError("monthly budget exhausted")
    elif event.state == BudgetState.ALERT:
        notifier.warn(f"team-a at {event.ratio:.0%} of budget")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class BudgetState(str, Enum):
    HEALTHY = "healthy"    # below alert ratio
    ALERT = "alert"        # above alert ratio, below limit
    EXCEEDED = "exceeded"  # at or above limit


@dataclass
class BudgetConfig:
    monthly_limit_usd: float
    alert_ratio: float = 0.8  # warn at 80%
    hard_stop: bool = True    # block further spend once exceeded


@dataclass
class BudgetStatus:
    key: str
    spent_usd: float
    limit_usd: float
    ratio: float
    state: BudgetState
    period: str  # "YYYY-MM"


@dataclass
class BudgetEvent:
    key: str
    amount_usd: float
    total_usd: float
    ratio: float
    state: BudgetState
    period: str
    threshold_crossed: bool = False


class BudgetExceeded(Exception):
    """Raised when hard_stop=True and a spend would exceed the budget."""


def _current_period() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}"


class BudgetTracker:
    """In-process budget store. Swap backend for persistence in production."""

    def __init__(self) -> None:
        self._configs: dict[str, BudgetConfig] = {}
        # (key, period) → spent
        self._spend: dict[tuple[str, str], float] = {}
        # Track the highest state we've seen to detect first-crossing
        self._last_state: dict[tuple[str, str], BudgetState] = {}

    def set_budget(
        self,
        key: str,
        monthly_limit_usd: float,
        alert_ratio: float = 0.8,
        hard_stop: bool = True,
    ) -> None:
        if monthly_limit_usd <= 0:
            raise ValueError("monthly_limit_usd must be > 0")
        if not 0 < alert_ratio <= 1:
            raise ValueError("alert_ratio must be in (0, 1]")
        self._configs[key] = BudgetConfig(
            monthly_limit_usd=monthly_limit_usd,
            alert_ratio=alert_ratio,
            hard_stop=hard_stop,
        )

    def get_status(self, key: str, period: str | None = None) -> BudgetStatus:
        period = period or _current_period()
        cfg = self._configs.get(key)
        limit = cfg.monthly_limit_usd if cfg else 0.0
        spent = self._spend.get((key, period), 0.0)
        ratio = (spent / limit) if limit > 0 else 0.0
        state = self._classify(ratio, cfg)
        return BudgetStatus(
            key=key,
            spent_usd=spent,
            limit_usd=limit,
            ratio=ratio,
            state=state,
            period=period,
        )

    def record_spend(
        self,
        key: str,
        amount_usd: float,
        period: str | None = None,
    ) -> BudgetEvent:
        if amount_usd < 0:
            raise ValueError("amount_usd must be >= 0")
        period = period or _current_period()
        cfg = self._configs.get(key)
        prev_spent = self._spend.get((key, period), 0.0)
        new_spent = prev_spent + amount_usd

        if cfg and cfg.hard_stop and new_spent > cfg.monthly_limit_usd:
            raise BudgetExceeded(
                f"budget {key!r} exceeded: ${new_spent:.2f} > ${cfg.monthly_limit_usd:.2f}"
            )

        self._spend[(key, period)] = new_spent
        ratio = (new_spent / cfg.monthly_limit_usd) if cfg else 0.0
        state = self._classify(ratio, cfg)

        prev_state = self._last_state.get((key, period), BudgetState.HEALTHY)
        threshold_crossed = _state_rank(state) > _state_rank(prev_state)
        self._last_state[(key, period)] = state

        return BudgetEvent(
            key=key,
            amount_usd=amount_usd,
            total_usd=new_spent,
            ratio=ratio,
            state=state,
            period=period,
            threshold_crossed=threshold_crossed,
        )

    def reset(self, key: str, period: str | None = None) -> None:
        period = period or _current_period()
        self._spend.pop((key, period), None)
        self._last_state.pop((key, period), None)

    def _classify(
        self, ratio: float, cfg: BudgetConfig | None
    ) -> BudgetState:
        if cfg is None:
            return BudgetState.HEALTHY
        if ratio >= 1.0:
            return BudgetState.EXCEEDED
        if ratio >= cfg.alert_ratio:
            return BudgetState.ALERT
        return BudgetState.HEALTHY


def _state_rank(state: BudgetState) -> int:
    return {BudgetState.HEALTHY: 0, BudgetState.ALERT: 1, BudgetState.EXCEEDED: 2}[state]
