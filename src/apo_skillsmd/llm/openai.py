"""OpenAI-compatible LLM client implementation."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from apo_skillsmd.llm.base import LLMClient, LLMMessage, LLMResponse, LLMUsage, ToolSchema
from apo_skillsmd.llm.tool_adapters import normalize_openai_tool_calls, schemas_to_openai_tools
from apo_skillsmd.types import MessageRole, ProviderName

_TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504, 529}


def _render_openai_message(message: LLMMessage) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.role == MessageRole.TOOL:
        payload["tool_call_id"] = message.tool_call_id
        payload["name"] = message.name
    elif message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": json.dumps(call.args, ensure_ascii=False)},
            }
            for call in message.tool_calls
        ]
    return payload


class OpenAICompatibleLLMClient(LLMClient):
    """Minimal HTTP client for OpenAI-style chat completion APIs."""

    def __init__(
        self,
        *,
        provider: ProviderName,
        model: str,
        api_key: str,
        base_url: str,
        timeout_sec: int = 60,
        max_retries: int = 4,
    ) -> None:
        self.provider = provider
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._max_retries = max_retries

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [_render_openai_message(message) for message in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = schemas_to_openai_tools(tools)

        response: httpx.Response | None = None
        for attempt in range(self._max_retries + 1):
            try:
                response = httpx.post(
                    f"{self._base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self._timeout_sec,
                )
            except httpx.TimeoutException:
                if attempt >= self._max_retries:
                    raise
                time.sleep(min(2**attempt, 8))
                continue
            except httpx.RequestError:
                if attempt >= self._max_retries:
                    raise
                time.sleep(min(2**attempt, 8))
                continue

            # MiniMax may occasionally return 529 when the cluster is busy.
            if response.status_code in _TRANSIENT_STATUS_CODES and attempt < self._max_retries:
                time.sleep(min(2**attempt, 8))
                continue
            response.raise_for_status()
            break

        if response is None:  # pragma: no cover - defensive fallback
            raise RuntimeError("OpenAI-compatible completion request did not return a response.")

        data = response.json()
        choice = data["choices"][0]
        message = choice.get("message", {})
        usage = data.get("usage", {})
        return LLMResponse(
            message=message.get("content") or "",
            tool_calls=normalize_openai_tool_calls(message),
            usage=LLMUsage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            ),
            raw_response=data,
        )
