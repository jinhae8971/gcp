"""Self-hosted LLM provider (vLLM / Ollama / LM Studio).

Any server exposing an OpenAI-compatible `/v1/chat/completions` endpoint
is usable through this adapter. Ships without a hard dependency on the
`openai` package — uses urllib under the hood so it works in minimal
environments (tests, edge deploys).

The cost is fixed at 0.0 (self-hosted = no per-token price).

Typical configs::

    vllm = LocalOpenAIProvider(
        base_url="http://vllm:8000",
        models=["meta-llama/Llama-3.1-70B-Instruct"],
        provider_name="vllm",
    )
    ollama = LocalOpenAIProvider(
        base_url="http://ollama:11434",
        models=["llama3.1:70b", "qwen2.5-coder:32b"],
        provider_name="ollama",
    )
"""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from typing import Any, AsyncIterator

from agent_platform.models.providers.base import (
    BaseProvider,
    ChatRequest,
    ChatResponse,
    StreamChunk,
    UsageInfo,
)


class LocalProviderError(RuntimeError):
    pass


class LocalOpenAIProvider(BaseProvider):
    """OpenAI-compatible HTTP client for self-hosted servers."""

    def __init__(
        self,
        base_url: str,
        models: list[str],
        provider_name: str = "local",
        api_key: str = "EMPTY",
        timeout: float = 120.0,
    ) -> None:
        if not base_url:
            raise ValueError("base_url must be provided")
        self.provider_name = provider_name
        self.supported_models = list(models)
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    async def chat(self, model: str, request: ChatRequest) -> ChatResponse:
        body: dict[str, Any] = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }
        if request.tools:
            body["tools"] = [
                {"type": "function", "function": t} for t in request.tools
            ]

        raw = await asyncio.to_thread(self._post, "/v1/chat/completions", body)
        data = json.loads(raw)

        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {}) or {}
        tool_calls: list[dict[str, Any]] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            tool_calls.append({
                "id": tc.get("id", ""),
                "name": fn.get("name", ""),
                "arguments": fn.get("arguments", ""),
            })

        usage = data.get("usage") or {}
        return ChatResponse(
            text=message.get("content") or "",
            tool_calls=tool_calls,
            usage=UsageInfo(
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                cost_usd=0.0,  # self-hosted
            ),
            model=model,
            raw=data,
        )

    async def stream_chat(
        self, model: str, request: ChatRequest
    ) -> AsyncIterator[StreamChunk]:
        # Minimal streaming: request non-streamed and yield once.
        # Real SSE parsing can be added when a concrete deployment needs it.
        response = await self.chat(model, request)
        yield StreamChunk(delta=response.text, finish_reason="stop")

    async def health_check(self) -> bool:
        try:
            raw = await asyncio.to_thread(self._get, "/v1/models")
            data = json.loads(raw)
            return "data" in data or "object" in data
        except Exception:
            return False

    # ── HTTP helpers ─────────────────────────────────────

    def _post(self, path: str, body: dict[str, Any]) -> str:
        req = urllib.request.Request(
            self._base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                if resp.status >= 400:
                    raise LocalProviderError(
                        f"{self.provider_name} returned HTTP {resp.status}"
                    )
                return resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise LocalProviderError(f"{self.provider_name} unreachable: {exc}") from exc

    def _get(self, path: str) -> str:
        req = urllib.request.Request(
            self._base_url + path,
            headers={"Authorization": f"Bearer {self._api_key}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            return resp.read().decode("utf-8")
