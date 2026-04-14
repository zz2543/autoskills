"""Default tool schemas and executor implementations."""

from __future__ import annotations

import json

from apo_skillsmd.llm.base import ToolCall, ToolResult, ToolSchema
from apo_skillsmd.sandbox.base import Sandbox


DEFAULT_TOOL_SCHEMAS: list[ToolSchema] = [
    ToolSchema(
        name="bash",
        description="Execute a shell command inside the sandbox workspace.",
        input_schema={
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "timeout": {"type": "integer", "minimum": 1, "default": 30},
            },
            "required": ["cmd"],
        },
    ),
    ToolSchema(
        name="file_read",
        description="Read one file from the sandbox workspace.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    ToolSchema(
        name="file_write",
        description="Write one file into the sandbox workspace.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    ),
    ToolSchema(
        name="file_list",
        description="List files inside the sandbox workspace.",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
        },
    ),
]


class ToolExecutor:
    """Route tool calls into the active sandbox backend."""

    def __init__(self, sandbox: Sandbox, default_timeout_sec: int = 30) -> None:
        self.sandbox = sandbox
        self.default_timeout_sec = default_timeout_sec

    def execute(self, call: ToolCall) -> tuple[ToolResult, int, list[str]]:
        """Execute one tool call and return the normalized result plus metadata."""

        try:
            if call.name == "bash":
                command = str(call.args["cmd"])
                timeout = int(call.args.get("timeout", self.default_timeout_sec))
                result = self.sandbox.run_bash(command, timeout_sec=timeout)
                payload = {
                    "exit_code": result.exit_code,
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                    "timed_out": result.timed_out,
                    "changed_files": result.changed_files,
                }
                return (
                    ToolResult(
                        call_id=call.id,
                        name=call.name,
                        content=json.dumps(payload, ensure_ascii=False),
                        is_error=result.exit_code != 0 or result.timed_out,
                    ),
                    result.duration_ms,
                    result.changed_files,
                )

            if call.name == "file_read":
                content = self.sandbox.read_file(str(call.args["path"]))
                return (
                    ToolResult(call_id=call.id, name=call.name, content=content),
                    0,
                    [],
                )

            if call.name == "file_write":
                path = self.sandbox.write_file(str(call.args["path"]), str(call.args["content"]))
                return (
                    ToolResult(
                        call_id=call.id,
                        name=call.name,
                        content=json.dumps({"written": path}, ensure_ascii=False),
                    ),
                    0,
                    [path],
                )

            if call.name == "file_list":
                files = self.sandbox.list_files(str(call.args.get("path", ".")))
                return (
                    ToolResult(
                        call_id=call.id,
                        name=call.name,
                        content=json.dumps({"files": files}, ensure_ascii=False),
                    ),
                    0,
                    [],
                )
        except Exception as exc:  # pragma: no cover - exercised through runtime failures
            return (
                ToolResult(call_id=call.id, name=call.name, content=str(exc), is_error=True),
                0,
                [],
            )

        return (
            ToolResult(
                call_id=call.id,
                name=call.name,
                content=f"Unknown tool: {call.name}",
                is_error=True,
            ),
            0,
            [],
        )
