"""Normalize provider-specific tool call payloads."""

from __future__ import annotations

import json
from typing import Any

from apo_skillsmd.llm.base import ToolCall, ToolResult, ToolSchema


def normalize_openai_tool_calls(raw_message: dict[str, Any]) -> list[ToolCall]:
    """Parse OpenAI-compatible `tool_calls` arrays into normalized objects."""

    tool_calls: list[ToolCall] = []
    for raw_call in raw_message.get("tool_calls", []) or []:
        arguments = raw_call.get("function", {}).get("arguments", "{}")
        parsed_arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
        tool_calls.append(
            ToolCall(
                id=raw_call["id"],
                name=raw_call["function"]["name"],
                args=parsed_arguments or {},
            )
        )
    return tool_calls


def normalize_anthropic_tool_blocks(content_blocks: list[dict[str, Any]]) -> list[ToolCall]:
    """Parse Anthropic `tool_use` blocks into normalized tool calls."""

    tool_calls: list[ToolCall] = []
    for block in content_blocks:
        if block.get("type") != "tool_use":
            continue
        tool_calls.append(
            ToolCall(
                id=block["id"],
                name=block["name"],
                args=block.get("input", {}) or {},
            )
        )
    return tool_calls


def normalize_gemini_function_calls(candidates: list[dict[str, Any]]) -> list[ToolCall]:
    """Parse Gemini `functionCall` payloads."""

    tool_calls: list[ToolCall] = []
    for candidate in candidates:
        parts = candidate.get("content", {}).get("parts", [])
        for part in parts:
            function_call = part.get("functionCall")
            if not function_call:
                continue
            tool_calls.append(
                ToolCall(
                    id=function_call.get("id", function_call["name"]),
                    name=function_call["name"],
                    args=function_call.get("args", {}) or {},
                )
            )
    return tool_calls


def encode_tool_result_for_openai(result: ToolResult) -> dict[str, Any]:
    """Encode a normalized tool result back into an OpenAI-compatible message."""

    return {
        "role": "tool",
        "tool_call_id": result.call_id,
        "name": result.name,
        "content": result.content,
    }


def encode_tool_result_for_anthropic(result: ToolResult) -> dict[str, Any]:
    """Encode a tool result into Anthropic's `tool_result` format."""

    return {
        "type": "tool_result",
        "tool_use_id": result.call_id,
        "content": result.content,
        "is_error": result.is_error,
    }


def schemas_to_openai_tools(schemas: list[ToolSchema]) -> list[dict[str, Any]]:
    """Render provider-agnostic tool schemas into OpenAI-compatible tools."""

    return [schema.as_openai_tool() for schema in schemas]
