"""Anthropic client placeholder.

The provider abstraction is wired so this file can later host a verified
Anthropic implementation without changing the rest of the framework.
"""

from __future__ import annotations

from apo_skillsmd.llm.base import LLMClient, LLMMessage, LLMResponse, ToolSchema
from apo_skillsmd.types import ProviderName


class AnthropicLLMClient(LLMClient):
    """Structured placeholder for Anthropic integration."""

    provider = ProviderName.ANTHROPIC

    def __init__(self, *, model: str, api_key: str, base_url: str | None = None) -> None:
        self.model = model
        self._api_key = api_key
        self._base_url = base_url

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        raise NotImplementedError(
            "Anthropic tool-use wiring is intentionally isolated here and can be implemented "
            "without touching the agent loop."
        )
