"""Small helpers that keep agent trace bookkeeping readable."""

from __future__ import annotations

import json

from apo_skillsmd.llm.base import ToolResult


def serialize_tool_payload(payload: dict) -> str:
    """Serialize tool payloads consistently for trace and conversation history."""

    return json.dumps(payload, ensure_ascii=False, indent=2)


def tool_result_to_text(result: ToolResult) -> str:
    """Render a tool result as plain text for the next LLM turn."""

    prefix = "ERROR" if result.is_error else "OK"
    return f"{prefix}: {result.content}"
