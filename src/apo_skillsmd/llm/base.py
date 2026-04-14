"""Provider-agnostic LLM abstractions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from apo_skillsmd.types import MessageRole, ProviderName


class ToolSchema(BaseModel):
    """JSON schema description of a callable tool."""

    name: str
    description: str
    input_schema: dict[str, Any]

    def as_openai_tool(self) -> dict[str, Any]:
        """Convert to the OpenAI-compatible `tools` payload."""

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }


class ToolCall(BaseModel):
    """A normalized tool invocation emitted by any provider."""

    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Normalized tool execution result pushed back into the conversation."""

    call_id: str
    name: str
    content: str
    is_error: bool = False


class LLMMessage(BaseModel):
    """Conversation message stored in the agent loop."""

    role: MessageRole
    content: str = ""
    name: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None


class LLMUsage(BaseModel):
    """Token usage reported by the provider."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMResponse(BaseModel):
    """Unified LLM completion result used by the agent loop."""

    message: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: LLMUsage = Field(default_factory=LLMUsage)
    raw_response: dict[str, Any] = Field(default_factory=dict)


class LLMClient(ABC):
    """Abstract provider client."""

    provider: ProviderName
    model: str

    @abstractmethod
    def complete(
        self,
        messages: list[LLMMessage],
        *,
        tools: list[ToolSchema] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """Execute a chat completion request."""

    def supports_tools(self) -> bool:
        """Whether the backend can natively return structured tool calls."""

        return True
