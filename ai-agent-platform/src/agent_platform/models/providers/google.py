"""Google Gemini provider adapter."""

from __future__ import annotations

from typing import Any, AsyncIterator

from google import genai

from agent_platform.models.providers.base import (
    BaseProvider,
    ChatRequest,
    ChatResponse,
    StreamChunk,
    UsageInfo,
)

_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-pro": (1.25, 10.0),
    "gemini-2.5-flash": (0.15, 0.60),
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp_rate, out_rate = _PRICING.get(model, (1.25, 10.0))
    return (input_tokens * inp_rate + output_tokens * out_rate) / 1_000_000


class GoogleProvider(BaseProvider):
    provider_name = "google"
    supported_models = list(_PRICING.keys())

    def __init__(self, api_key: str) -> None:
        self._client = genai.Client(api_key=api_key)

    async def chat(self, model: str, request: ChatRequest) -> ChatResponse:
        contents: list[dict[str, Any]] = []
        system_instruction = None

        for msg in request.messages:
            if msg["role"] == "system":
                system_instruction = msg["content"]
            else:
                role = "model" if msg["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        config: dict[str, Any] = {
            "temperature": request.temperature,
            "max_output_tokens": request.max_tokens,
        }
        if system_instruction:
            config["system_instruction"] = system_instruction

        resp = await self._client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )

        input_tokens = getattr(resp.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(resp.usage_metadata, "candidates_token_count", 0) or 0

        return ChatResponse(
            text=resp.text or "",
            tool_calls=[],
            usage=UsageInfo(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=_estimate_cost(model, input_tokens, output_tokens),
            ),
            model=model,
        )

    async def stream_chat(self, model: str, request: ChatRequest) -> AsyncIterator[StreamChunk]:
        contents: list[dict[str, Any]] = []
        for msg in request.messages:
            if msg["role"] != "system":
                role = "model" if msg["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        async for chunk in await self._client.aio.models.generate_content_stream(
            model=model,
            contents=contents,
        ):
            if chunk.text:
                yield StreamChunk(delta=chunk.text)

    async def health_check(self) -> bool:
        try:
            await self._client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents="ping",
                config={"max_output_tokens": 10},
            )
            return True
        except Exception:
            return False
