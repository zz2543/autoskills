"""MiniMax client.

MiniMax is handled as an OpenAI-compatible endpoint. The actual base URL and
model are intentionally configurable because provider-side conventions may
change over time.
"""

from __future__ import annotations

from apo_skillsmd.llm.openai import OpenAICompatibleLLMClient
from apo_skillsmd.types import ProviderName


class MiniMaxLLMClient(OpenAICompatibleLLMClient):
    """Default MiniMax backend used by Phase 1 smoke tests and experiments."""

    def __init__(self, *, model: str, api_key: str, base_url: str, timeout_sec: int = 60) -> None:
        super().__init__(
            provider=ProviderName.MINIMAX,
            model=model,
            api_key=api_key,
            base_url=base_url,
            timeout_sec=timeout_sec,
        )
