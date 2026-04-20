"""Tests for transient retry handling in the OpenAI-compatible client."""

from __future__ import annotations

import httpx

from apo_skillsmd.llm.base import LLMMessage
from apo_skillsmd.llm.openai import OpenAICompatibleLLMClient
from apo_skillsmd.types import MessageRole, ProviderName


def _success_response() -> httpx.Response:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    return httpx.Response(
        200,
        request=request,
        json={
            "choices": [{"message": {"content": "DONE"}, "finish_reason": "stop", "index": 0}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )


def test_openai_compatible_client_retries_transient_529(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_post(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            request = httpx.Request("POST", "https://example.com/v1/chat/completions")
            return httpx.Response(
                529,
                request=request,
                json={"error": {"type": "overloaded_error", "message": "busy"}},
            )
        return _success_response()

    monkeypatch.setattr("apo_skillsmd.llm.openai.httpx.post", fake_post)
    monkeypatch.setattr("apo_skillsmd.llm.openai.time.sleep", lambda *_args, **_kwargs: None)

    client = OpenAICompatibleLLMClient(
        provider=ProviderName.MINIMAX,
        model="MiniMax-M2.1",
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    response = client.complete([LLMMessage(role=MessageRole.USER, content="ping")])

    assert response.message == "DONE"
    assert calls["count"] == 2


def test_openai_compatible_client_retries_timeout(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_post(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise httpx.ReadTimeout("timed out")
        return _success_response()

    monkeypatch.setattr("apo_skillsmd.llm.openai.httpx.post", fake_post)
    monkeypatch.setattr("apo_skillsmd.llm.openai.time.sleep", lambda *_args, **_kwargs: None)

    client = OpenAICompatibleLLMClient(
        provider=ProviderName.MINIMAX,
        model="MiniMax-M2.1",
        api_key="test-key",
        base_url="https://example.com/v1",
    )
    response = client.complete([LLMMessage(role=MessageRole.USER, content="ping")])

    assert response.message == "DONE"
    assert calls["count"] == 2
