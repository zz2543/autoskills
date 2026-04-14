"""Gemini client placeholder."""

from __future__ import annotations

from apo_skillsmd.llm.base import LLMClient, LLMMessage, LLMResponse, ToolSchema
from apo_skillsmd.types import ProviderName


class GeminiLLMClient(LLMClient):
    """Structured placeholder for Gemini integration."""

    provider = ProviderName.GEMINI

    def __init__(self, *, model: str, api_key: str) -> None:
        self.model = model
        self._api_key = api_key

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        raise NotImplementedError(
            "Gemini function-call normalization should be implemented in this module."
        )
