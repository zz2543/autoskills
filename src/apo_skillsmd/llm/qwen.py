"""Qwen client placeholder."""

from __future__ import annotations

from apo_skillsmd.llm.base import LLMClient, LLMMessage, LLMResponse, ToolSchema
from apo_skillsmd.types import ProviderName


class QwenLLMClient(LLMClient):
    """Structured placeholder for Qwen integration."""

    provider = ProviderName.QWEN

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
            "Qwen integration should be implemented here once the deployment endpoint is fixed."
        )
