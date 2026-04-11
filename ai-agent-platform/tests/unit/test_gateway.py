"""Tests for model gateway."""

from agent_platform.models.gateway import CircuitBreaker


def test_circuit_breaker_closed_initially():
    cb = CircuitBreaker(failure_threshold=3)
    assert not cb.is_open("anthropic")


def test_circuit_breaker_opens_after_threshold():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
    cb.record_failure("anthropic")
    assert not cb.is_open("anthropic")
    cb.record_failure("anthropic")
    assert cb.is_open("anthropic")


def test_circuit_breaker_resets_on_success():
    cb = CircuitBreaker(failure_threshold=3)
    cb.record_failure("openai")
    cb.record_failure("openai")
    cb.record_success("openai")
    assert not cb.is_open("openai")
    # Need 3 fresh failures to open
    cb.record_failure("openai")
    assert not cb.is_open("openai")
