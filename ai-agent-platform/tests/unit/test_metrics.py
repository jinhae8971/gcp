"""Tests for Prometheus metrics registry."""

from __future__ import annotations

import pytest

from agent_platform.observability.metrics import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
)


class TestCounter:
    def test_increment(self):
        c = Counter("http_requests", "total requests")
        c.inc()
        c.inc(2.0)
        assert c.value() == 3.0

    def test_labels(self):
        c = Counter("tool_calls", "tool calls", labelnames=["tool", "status"])
        c.inc(labels={"tool": "read_file", "status": "ok"})
        c.inc(labels={"tool": "read_file", "status": "ok"})
        c.inc(labels={"tool": "write_file", "status": "error"})
        assert c.value(labels={"tool": "read_file", "status": "ok"}) == 2
        assert c.value(labels={"tool": "write_file", "status": "error"}) == 1

    def test_negative_raises(self):
        c = Counter("x", "x")
        with pytest.raises(ValueError):
            c.inc(-1)

    def test_missing_label_raises(self):
        c = Counter("x", "x", labelnames=["a", "b"])
        with pytest.raises(ValueError):
            c.inc(labels={"a": "1"})

    def test_render(self):
        c = Counter("x_total", "desc", labelnames=["k"])
        c.inc(2, labels={"k": "v"})
        out = c.render()
        assert "# TYPE x_total counter" in out
        assert 'x_total{k="v"} 2' in out


class TestGauge:
    def test_set_and_update(self):
        g = Gauge("active_sessions", "current sessions")
        g.set(10)
        assert g.value() == 10
        g.inc(5)
        g.dec(2)
        assert g.value() == 13

    def test_labels(self):
        g = Gauge("queue_depth", "depth", labelnames=["queue"])
        g.set(5, labels={"queue": "eval"})
        g.set(3, labels={"queue": "chat"})
        assert g.value(labels={"queue": "eval"}) == 5
        assert g.value(labels={"queue": "chat"}) == 3


class TestHistogram:
    def test_observe_updates_buckets(self):
        h = Histogram("latency", "req latency", buckets=[0.1, 1, 10])
        h.observe(0.05)
        h.observe(0.5)
        h.observe(5.0)
        h.observe(20.0)
        count, total, buckets = h.snapshot()
        assert count == 4
        assert total == pytest.approx(25.55)
        # 0.05 → bucket 0.1 and all above
        # 0.5 → bucket 1 and above
        # 5.0 → bucket 10 and above
        # 20.0 → +Inf only
        # Cumulative counts per bucket (in order 0.1, 1, 10, +Inf)
        assert buckets[0] == 1
        assert buckets[1] == 2
        assert buckets[2] == 3
        assert buckets[3] == 4

    def test_render_has_sum_and_count(self):
        h = Histogram("latency", "req latency", buckets=[1])
        h.observe(0.5)
        out = h.render()
        assert "latency_sum" in out
        assert "latency_count" in out
        assert "latency_bucket" in out


class TestMetricsRegistry:
    def test_register_and_render_all(self):
        r = MetricsRegistry()
        c = r.counter("reqs_total", "requests")
        g = r.gauge("sessions", "active")
        c.inc()
        g.set(5)
        out = r.render()
        assert "# TYPE reqs_total counter" in out
        assert "# TYPE sessions gauge" in out

    def test_duplicate_type_mismatch(self):
        r = MetricsRegistry()
        r.counter("x", "x")
        with pytest.raises(ValueError):
            r.gauge("x", "x")

    def test_duplicate_same_type_returns_existing(self):
        r = MetricsRegistry()
        c1 = r.counter("x", "x")
        c2 = r.counter("x", "x")
        assert c1 is c2
