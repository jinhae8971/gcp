"""Anthropic Claude provider adapter."""

from __future__ import annotations

from typing import Any, AsyncIterator

import anthropic

from agent_platform.models.providers.base import (
    BaseProvider,
    ChatRequest,
    ChatResponse,
    StreamChunk,
    UsageInfo,
)

# Approximate pricing per 1M tokens (USD) - update as pricing changes
_PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-20250514": (15.0, 75.0),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "claude-haiku-4-20250506": (0.80, 4.0),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp_rate, out_rate = _PRICING.get(model, (3.0, 15.0))
    return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000


class AnthropicProvider(BaseProvider):
    provider_name = "anthropic"
    supported_models = list(_PRICING.keys())

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def chat(self, model: str, request: ChatRequest) -> ChatResponse:
        # Separate system message from conversation
        system_text = ""
        messages: list[dict[str, Any]] = []
        for msg in request.messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                messages.append(msg)

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": messages,
            "temperature": request.temperature,
        }
        if system_text:
            kwargs["system"] = system_text
        if request.tools:
            kwargs["tools"] = request.tools

        resp = await self._client.messages.create(**kwargs)

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                })

        return ChatResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            usage=UsageInfo(
                input_tokens=resp.usage.input_tokens,
                output_tokens=resp.usage.output_tokens,
                cost_usd=_estimate_cost(model, resp.usage.input_tokens, resp.usage.output_tokens),
            ),
            model=model,
        )

    async def stream_chat(self, model: str, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        system_text = ""
        messages: list[dict[str, Any]] = []
        for msg in request.messages:
            if msg["role"] == "system":
                system_text = msg["content"]
            else:
                messages.append(msg)

        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "messages": messages,
            "temperature": request.temperature,
        }
        if system_text:
            kwargs["system"] = system_text
        if request.tools:
            kwargs["tools"] = request.tools

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if hasattr(event, "delta") and hasattr(event.delta, "text"):
                    yield StreamChunk(delta=event.delta.text)

    async def health_check(self) -> bool:
        try:
            await self._client.messages.create(
                model="claude-haiku-4-20250506",
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False
