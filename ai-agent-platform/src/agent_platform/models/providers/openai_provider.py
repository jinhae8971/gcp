"""OpenAI provider adapter."""

from __future__ import annotations

from typing import Any, AsyncIterator

import openai

from agent_platform.models.providers.base import (
    BaseProvider,
    ChatRequest,
    ChatResponse,
    StreamChunk,
    UsageInfo,
)

_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "o3": (10.0, 40.0),
    "o4-mini": (1.10, 4.40),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp_rate, out_rate = _PRICING.get(model, (2.50, 10.0))
    return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000


class OpenAIProvider(BaseProvider):
    provider_name = "openai"
    supported_models = list(_PRICING.keys())

    def __init__(self, api_key: str) -> None:
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def chat(self, model: str, request: ChatRequest) -> ChatResponse:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_completion_tokens": request.max_tokens,
        }
        if request.tools:
            kwargs["tools"] = [
                {"type": "function", "function": t} for t in request.tools
            ]

        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]

        tool_calls: list[dict[str, Any]] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                })

        usage = resp.usage
        return ChatResponse(
            text=choice.message.content or "",
            tool_calls=tool_calls,
            usage=UsageInfo(
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                cost_usd=_estimate_cost(
                    model,
                    usage.prompt_tokens if usage else 0,
                    usage.completion_tokens if usage else 0,
                ),
            ),
            model=model,
        )

    async def stream_chat(self, model: str, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "stream": True,
        }
        if request.tools:
            kwargs["tools"] = [{"type": "function", "function": t} for t in request.tools]

        stream = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                yield StreamChunk(delta=delta.content)

    async def health_check(self) -> bool:
        try:
            await self._client.chat.completions.create(
                model="gpt-4o-mini",
                max_completion_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False
