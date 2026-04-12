"""Prometheus-compatible metrics collector.

Pure-stdlib implementation that supports Counter, Gauge, and Histogram
and renders to the Prometheus text exposition format. No prometheus_client
dependency — keeps the platform portable while still letting Prometheus /
Grafana scrape the `/metrics` endpoint.

Usage:
    metrics = MetricsRegistry()
    agent_runs = metrics.counter(
        "agent_runs_total", "Total agent runs", labelnames=["harness", "status"]
    )
    agent_runs.inc(labels={"harness": "react", "status": "success"})

    latency = metrics.histogram(
        "agent_iteration_seconds", "Latency per iteration",
        buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
    )
    latency.observe(0.42)

    print(metrics.render())  # Prometheus text format
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Iterable


_DEFAULT_BUCKETS = (0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)


def _format_labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    parts = [f'{k}="{_escape(str(v))}"' for k, v in sorted(labels.items())]
    return "{" + ",".join(parts) + "}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class _Metric:
    """Base for all metric types."""

    kind = "untyped"

    def __init__(
        self,
        name: str,
        help_text: str,
        labelnames: Iterable[str] = (),
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.labelnames = tuple(labelnames)
        self._lock = threading.Lock()

    def _check_labels(self, labels: dict[str, str] | None) -> dict[str, str]:
        labels = labels or {}
        missing = set(self.labelnames) - set(labels)
        extra = set(labels) - set(self.labelnames)
        if missing or extra:
            raise ValueError(
                f"{self.name}: expected labels={self.labelnames}, got {sorted(labels)}"
            )
        return labels

    def render(self) -> str:
        raise NotImplementedError


class Counter(_Metric):
    kind = "counter"

    def __init__(self, name: str, help_text: str, labelnames: Iterable[str] = ()) -> None:
        super().__init__(name, help_text, labelnames)
        self._values: dict[tuple[tuple[str, str], ...], float] = {}

    def inc(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        if amount < 0:
            raise ValueError("counter increment must be >= 0")
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def value(self, labels: dict[str, str] | None = None) -> float:
        return self._values.get(self._key(labels), 0.0)

    def _key(self, labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        labels = self._check_labels(labels)
        return tuple(sorted(labels.items()))

    def render(self) -> str:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} counter",
        ]
        for key, val in sorted(self._values.items()):
            labels = dict(key)
            lines.append(f"{self.name}{_format_labels(labels)} {val}")
        return "\n".join(lines)


class Gauge(_Metric):
    kind = "gauge"

    def __init__(self, name: str, help_text: str, labelnames: Iterable[str] = ()) -> None:
        super().__init__(name, help_text, labelnames)
        self._values: dict[tuple[tuple[str, str], ...], float] = {}

    def set(self, value: float, labels: dict[str, str] | None = None) -> None:
        with self._lock:
            self._values[self._key(labels)] = float(value)

    def inc(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        key = self._key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        self.inc(-amount, labels)

    def value(self, labels: dict[str, str] | None = None) -> float:
        return self._values.get(self._key(labels), 0.0)

    def _key(self, labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        labels = self._check_labels(labels)
        return tuple(sorted(labels.items()))

    def render(self) -> str:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} gauge",
        ]
        for key, val in sorted(self._values.items()):
            labels = dict(key)
            lines.append(f"{self.name}{_format_labels(labels)} {val}")
        return "\n".join(lines)


@dataclass
class _HistogramState:
    bucket_counts: list[int] = field(default_factory=list)
    sum_value: float = 0.0
    count: int = 0


class Histogram(_Metric):
    kind = "histogram"

    def __init__(
        self,
        name: str,
        help_text: str,
        labelnames: Iterable[str] = (),
        buckets: Iterable[float] = _DEFAULT_BUCKETS,
    ) -> None:
        super().__init__(name, help_text, labelnames)
        sorted_buckets = sorted(float(b) for b in buckets)
        if not sorted_buckets or sorted_buckets[-1] != float("inf"):
            sorted_buckets.append(float("inf"))
        self._buckets = tuple(sorted_buckets)
        self._states: dict[tuple[tuple[str, str], ...], _HistogramState] = {}

    def observe(self, value: float, labels: dict[str, str] | None = None) -> None:
        key = self._key(labels)
        with self._lock:
            state = self._states.get(key)
            if state is None:
                state = _HistogramState(bucket_counts=[0] * len(self._buckets))
                self._states[key] = state
            state.count += 1
            state.sum_value += value
            for i, upper in enumerate(self._buckets):
                if value <= upper:
                    state.bucket_counts[i] += 1

    def _key(self, labels: dict[str, str] | None) -> tuple[tuple[str, str], ...]:
        labels = self._check_labels(labels)
        return tuple(sorted(labels.items()))

    def snapshot(
        self, labels: dict[str, str] | None = None
    ) -> tuple[int, float, list[int]]:
        state = self._states.get(self._key(labels))
        if state is None:
            return 0, 0.0, [0] * len(self._buckets)
        return state.count, state.sum_value, list(state.bucket_counts)

    def render(self) -> str:
        lines = [
            f"# HELP {self.name} {self.help_text}",
            f"# TYPE {self.name} histogram",
        ]
        for key, state in sorted(self._states.items()):
            base_labels = dict(key)
            cumulative = 0
            for upper, count in zip(self._buckets, state.bucket_counts):
                cumulative = count  # bucket_counts are already cumulative via observe
                le = "+Inf" if upper == float("inf") else repr(upper)
                labels = {**base_labels, "le": le}
                lines.append(f"{self.name}_bucket{_format_labels(labels)} {cumulative}")
            lines.append(f"{self.name}_sum{_format_labels(base_labels)} {state.sum_value}")
            lines.append(f"{self.name}_count{_format_labels(base_labels)} {state.count}")
        return "\n".join(lines)


class MetricsRegistry:
    """Central registry that exposes all metrics via Prometheus text format."""

    def __init__(self) -> None:
        self._metrics: dict[str, _Metric] = {}
        self._lock = threading.Lock()

    def counter(
        self, name: str, help_text: str, labelnames: Iterable[str] = ()
    ) -> Counter:
        return self._register(Counter(name, help_text, labelnames))

    def gauge(
        self, name: str, help_text: str, labelnames: Iterable[str] = ()
    ) -> Gauge:
        return self._register(Gauge(name, help_text, labelnames))

    def histogram(
        self,
        name: str,
        help_text: str,
        labelnames: Iterable[str] = (),
        buckets: Iterable[float] = _DEFAULT_BUCKETS,
    ) -> Histogram:
        return self._register(Histogram(name, help_text, labelnames, buckets))

    def _register(self, metric: _Metric) -> _Metric:
        with self._lock:
            if metric.name in self._metrics:
                existing = self._metrics[metric.name]
                if type(existing) is not type(metric):
                    raise ValueError(
                        f"metric {metric.name!r} already registered as {existing.kind}"
                    )
                return existing
            self._metrics[metric.name] = metric
            return metric

    def get(self, name: str) -> _Metric | None:
        return self._metrics.get(name)

    def render(self) -> str:
        parts = [m.render() for _, m in sorted(self._metrics.items())]
        return "\n".join(parts) + ("\n" if parts else "")


# Global default registry (wire to /metrics endpoint)
DEFAULT_REGISTRY = MetricsRegistry()
