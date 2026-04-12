"""Tests for self-hosted (vLLM/Ollama) provider adapter."""

from __future__ import annotations

import json

import pytest

from agent_platform.models.providers.base import ChatRequest
from agent_platform.models.providers.local import (
    LocalOpenAIProvider,
    LocalProviderError,
)


class TestLocalOpenAIProvider:
    def test_rejects_empty_base_url(self):
        with pytest.raises(ValueError):
            LocalOpenAIProvider(base_url="", models=["x"])

    def test_supported_models(self):
        p = LocalOpenAIProvider(
            base_url="http://vllm:8000",
            models=["llama-3.1-70b", "qwen2.5"],
            provider_name="vllm",
        )
        assert p.provider_name == "vllm"
        assert p.supports_model("llama-3.1-70b")
        assert not p.supports_model("gpt-4o")

    @pytest.mark.asyncio
    async def test_chat_parses_openai_response(self, monkeypatch):
        fake_response = {
            "choices": [{
                "message": {
                    "content": "Hello!",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path": "a.py"}',
                            },
                        }
                    ],
                }
            }],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 17,
            },
        }

        p = LocalOpenAIProvider(
            base_url="http://vllm:8000",
            models=["llama-3.1-70b"],
        )

        # Patch _post so no real network call happens
        def fake_post(path: str, body: dict) -> str:
            assert path == "/v1/chat/completions"
            assert body["model"] == "llama-3.1-70b"
            return json.dumps(fake_response)

        monkeypatch.setattr(p, "_post", fake_post)

        resp = await p.chat(
            "llama-3.1-70b",
            ChatRequest(messages=[{"role": "user", "content": "hi"}]),
        )
        assert resp.text == "Hello!"
        assert resp.usage.input_tokens == 42
        assert resp.usage.output_tokens == 17
        assert resp.usage.cost_usd == 0.0  # self-hosted
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0]["name"] == "read_file"

    @pytest.mark.asyncio
    async def test_chat_with_tools_in_body(self, monkeypatch):
        captured: dict = {}

        def fake_post(path: str, body: dict) -> str:
            captured.update(body)
            return json.dumps({"choices": [{"message": {"content": ""}}]})

        p = LocalOpenAIProvider(base_url="http://vllm:8000", models=["m"])
        monkeypatch.setattr(p, "_post", fake_post)

        await p.chat(
            "m",
            ChatRequest(
                messages=[{"role": "user", "content": "x"}],
                tools=[{"name": "read_file", "description": "read", "parameters": {}}],
            ),
        )
        assert "tools" in captured
        assert captured["tools"][0]["type"] == "function"

    @pytest.mark.asyncio
    async def test_stream_chat_yields_single_chunk(self, monkeypatch):
        p = LocalOpenAIProvider(base_url="http://vllm:8000", models=["m"])
        monkeypatch.setattr(
            p, "_post",
            lambda path, body: json.dumps(
                {"choices": [{"message": {"content": "streamed"}}], "usage": {}}
            ),
        )

        chunks = []
        async for chunk in p.stream_chat("m", ChatRequest(messages=[])):
            chunks.append(chunk)
        assert len(chunks) == 1
        assert chunks[0].delta == "streamed"

    @pytest.mark.asyncio
    async def test_health_check_success(self, monkeypatch):
        p = LocalOpenAIProvider(base_url="http://vllm:8000", models=["m"])
        monkeypatch.setattr(
            p, "_get", lambda path: json.dumps({"data": [{"id": "m"}]})
        )
        assert await p.health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, monkeypatch):
        p = LocalOpenAIProvider(base_url="http://vllm:8000", models=["m"])
        def broken(path: str) -> str:
            raise LocalProviderError("down")
        monkeypatch.setattr(p, "_get", broken)
        assert await p.health_check() is False
