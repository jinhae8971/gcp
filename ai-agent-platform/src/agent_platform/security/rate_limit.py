"""Token-bucket rate limiter.

Per-principal rate limiting with configurable capacity and refill rate.
Thread-safe via asyncio.Lock — callable from async request handlers.

Usage:
    limiter = RateLimiter(capacity=60, refill_per_second=1.0)  # 60 req/min
    if not await limiter.acquire("user:alice"):
        raise HTTPException(429)

Multi-tier support lets you set different quotas per role:
    limiter = TieredRateLimiter({
        "free":    BucketPolicy(capacity=10, refill_per_second=0.1),
        "pro":     BucketPolicy(capacity=100, refill_per_second=2.0),
        "admin":   BucketPolicy(capacity=1000, refill_per_second=50.0),
    })
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class BucketPolicy:
    """Defines how a single token bucket refills."""

    capacity: float
    refill_per_second: float


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class RateLimiter:
    """Single-policy token-bucket limiter keyed by arbitrary identifier."""

    def __init__(self, capacity: float, refill_per_second: float) -> None:
        if capacity <= 0 or refill_per_second < 0:
            raise ValueError("capacity must be > 0, refill_per_second >= 0")
        self._policy = BucketPolicy(capacity=capacity, refill_per_second=refill_per_second)
        self._buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, key: str, cost: float = 1.0) -> bool:
        """Try to consume `cost` tokens. Returns True if allowed, False if throttled."""
        async with self._lock:
            bucket = self._refill(key)
            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return True
            return False

    def acquire_sync(self, key: str, cost: float = 1.0) -> bool:
        """Synchronous variant for non-async callers / tests."""
        bucket = self._refill(key)
        if bucket.tokens >= cost:
            bucket.tokens -= cost
            return True
        return False

    def _refill(self, key: str) -> _Bucket:
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self._policy.capacity, last_refill=now)
            self._buckets[key] = bucket
            return bucket

        elapsed = now - bucket.last_refill
        bucket.tokens = min(
            self._policy.capacity,
            bucket.tokens + elapsed * self._policy.refill_per_second,
        )
        bucket.last_refill = now
        return bucket

    def peek(self, key: str) -> float:
        """Current token count (for observability/debug)."""
        return self._refill(key).tokens

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._buckets.clear()
        else:
            self._buckets.pop(key, None)


class TieredRateLimiter:
    """Routes each principal to a tier-specific bucket policy.

    Tiers are resolved by role — the first matching role wins. Falls back to
    a `default_tier` when no role matches.
    """

    def __init__(
        self,
        tiers: dict[str, BucketPolicy],
        default_tier: str = "free",
    ) -> None:
        if default_tier not in tiers:
            raise ValueError(f"default_tier {default_tier!r} not in tiers")
        self._tiers = tiers
        self._default = default_tier
        self._limiters: dict[str, RateLimiter] = {
            name: RateLimiter(p.capacity, p.refill_per_second)
            for name, p in tiers.items()
        }

    def tier_for_roles(self, roles: list[str]) -> str:
        for role in roles:
            if role in self._tiers:
                return role
        return self._default

    async def acquire(
        self, subject: str, roles: list[str], cost: float = 1.0
    ) -> bool:
        tier = self.tier_for_roles(roles)
        return await self._limiters[tier].acquire(subject, cost=cost)

    def tiers(self) -> list[str]:
        return list(self._tiers.keys())
