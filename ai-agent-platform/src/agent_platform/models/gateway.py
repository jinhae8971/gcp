"""Model Gateway - unified routing layer across all LLM providers.

Responsibilities:
  - Route requests to the correct provider based on model ID
  - Automatic fallback on provider failure (circuit breaker pattern)
  - Cost tracking and rate limiting
  - Health monitoring
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import structlog

from agent_platform.models.providers.base import (
    BaseProvider,
    ChatRequest,
    ChatResponse,
    StreamChunk,
    UsageInfo,
)

logger = structlog.get_logger()

# Model ID -> provider name mapping
_MODEL_PROVIDER_MAP: dict[str, str] = {
    # Anthropic
    "claude-opus-4-20250514": "anthropic",
    "claude-sonnet-4-20250514": "anthropic",
    "claude-haiku-4-20250506": "anthropic",
    # OpenAI
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "o3": "openai",
    "o4-mini": "openai",
    # Google
    "gemini-2.5-pro": "google",
    "gemini-2.5-flash": "google",
}


class CircuitBreaker:
    """Simple circuit breaker to avoid hammering failing providers."""

    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 60.0) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def is_open(self, provider: str) -> bool:
        if provider not in self._open_until:
            return False
        import time
        if time.monotonic() > self._open_until[provider]:
            # Half-open: allow one attempt
            del self._open_until[provider]
            self._failures[provider] = 0
            return False
        return True

    def record_failure(self, provider: str) -> None:
        self._failures[provider] = self._failures.get(provider, 0) + 1
        if self._failures[provider] >= self.failure_threshold:
            import time
            self._open_until[provider] = time.monotonic() + self.recovery_timeout
            logger.warning("circuit_breaker.open", provider=provider)

    def record_success(self, provider: str) -> None:
        self._failures[provider] = 0


class ModelGateway:
    """Central gateway for all model interactions."""

    def __init__(
        self,
        providers: dict[str, BaseProvider],
        default_model: str = "claude-sonnet-4-20250514",
        fallback_models: list[str] | None = None,
        max_retries: int = 3,
    ) -> None:
        self._providers = providers
        self.default_model = default_model
        self._fallback_models = fallback_models or []
        self._max_retries = max_retries
        self._circuit_breaker = CircuitBreaker()
        self._stream_accumulator: ChatResponse | None = None

    def _resolve_provider(self, model: str) -> tuple[str, BaseProvider]:
        provider_name = _MODEL_PROVIDER_MAP.get(model)
        if not provider_name or provider_name not in self._providers:
            raise ValueError(f"No provider registered for model: {model}")
        return provider_name, self._providers[provider_name]

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Send chat request with automatic fallback."""
        models_to_try = [model] + [m for m in self._fallback_models if m != model]
        request = ChatRequest(
            messages=messages, tools=tools, temperature=temperature, max_tokens=max_tokens
        )

        last_error: Exception | None = None
        for candidate_model in models_to_try:
            provider_name, provider = self._resolve_provider(candidate_model)

            if self._circuit_breaker.is_open(provider_name):
                logger.info("gateway.skip_provider", provider=provider_name, reason="circuit_open")
                continue

            for attempt in range(1, self._max_retries + 1):
                try:
                    response = await provider.chat(candidate_model, request)
                    self._circuit_breaker.record_success(provider_name)
                    response.model = candidate_model
                    return response
                except Exception as exc:
                    last_error = exc
                    logger.warning(
                        "gateway.retry",
                        provider=provider_name,
                        model=candidate_model,
                        attempt=attempt,
                        error=str(exc),
                    )
                    if attempt < self._max_retries:
                        await asyncio.sleep(2**attempt)  # exponential backoff

            self._circuit_breaker.record_failure(provider_name)

        raise RuntimeError(f"All providers failed. Last error: {last_error}")

    async def stream_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.0,
    ) -> AsyncIterator[StreamChunk]:
        """Stream chat response tokens."""
        _, provider = self._resolve_provider(model)
        request = ChatRequest(messages=messages, tools=tools, temperature=temperature)
        async for chunk in provider.stream_chat(model, request):
            yield chunk

    async def collect_stream(self) -> ChatResponse:
        """After streaming, return the collected full response."""
        if self._stream_accumulator:
            return self._stream_accumulator
        return ChatResponse(usage=UsageInfo())

    async def health(self) -> dict[str, bool]:
        """Check health of all registered providers."""
        results: dict[str, bool] = {}
        for name, provider in self._providers.items():
            try:
                results[name] = await provider.health_check()
            except Exception:
                results[name] = False
        return results

    def list_models(self) -> list[dict[str, str]]:
        """Return all available models and their providers."""
        return [
            {"model": model, "provider": provider}
            for model, provider in _MODEL_PROVIDER_MAP.items()
            if provider in self._providers
        ]
