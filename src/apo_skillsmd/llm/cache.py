"""Disk-backed LLM cache wrapper."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

try:
    import diskcache
except ImportError:  # pragma: no cover - handled gracefully at runtime
    diskcache = None

from apo_skillsmd.llm.base import LLMClient, LLMMessage, LLMResponse, ToolSchema


def _freeze_messages(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    return [message.model_dump() for message in messages]


class CachedLLMClient(LLMClient):
    """Cache completion results on disk to save repeated experiment cost."""

    def __init__(self, backend: LLMClient, cache_dir: str) -> None:
        self.backend = backend
        self.provider = backend.provider
        self.model = backend.model
        self.cache = diskcache.Cache(cache_dir) if diskcache else None

    def _build_key(
        self,
        messages: list[LLMMessage],
        tools: list[ToolSchema] | None,
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = {
            "provider": self.provider.value,
            "model": self.model,
            "messages": _freeze_messages(messages),
            "tools": [tool.model_dump() for tool in tools or []],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        return sha256(repr(payload).encode("utf-8")).hexdigest()

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        if self.cache is None:
            return self.backend.complete(
                messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )

        key = self._build_key(messages, tools, temperature, max_tokens)
        cached = self.cache.get(key)
        if cached is not None:
            return LLMResponse.model_validate(cached)

        response = self.backend.complete(
            messages,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self.cache.set(key, response.model_dump())
        return response
