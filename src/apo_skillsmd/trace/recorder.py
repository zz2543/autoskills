"""Trace recorder used by the agent loop."""

from __future__ import annotations

from apo_skillsmd.llm.base import LLMUsage, ToolCall, ToolResult
from apo_skillsmd.trace.schema import FinalOutput, ModuleEvent, Trace


def _summarize_output(result: ToolResult) -> str:
    return result.content.replace("\n", " ")[:200]


class TraceRecorder:
    """Collect trace events incrementally while the agent loop runs."""

    def __init__(self, *, skill_id: str, task_id: str) -> None:
        self.skill_id = skill_id
        self.task_id = task_id
        self.module_events: list[ModuleEvent] = []
        self.execution_tokens = 0

    def record_llm_usage(self, usage: LLMUsage) -> None:
        self.execution_tokens += usage.total_tokens

    def record_tool_result(
        self,
        call: ToolCall,
        result: ToolResult,
        *,
        duration_ms: int,
        changed_files: list[str] | None = None,
    ) -> None:
        exceptions = [result.content] if result.is_error else []
        self.module_events.append(
            ModuleEvent(
                module=f"tool:{call.name}",
                entered=True,
                exceptions=exceptions,
                duration_ms=duration_ms,
                output_summary=_summarize_output(result),
                metadata={
                    "tool_call_id": call.id,
                    "changed_files": changed_files or [],
                },
            )
        )

    def finalize(
        self,
        *,
        success: bool,
        assistant_message: str,
        files_created: list[str],
        stdout: str = "",
    ) -> Trace:
        return Trace(
            skill_id=self.skill_id,
            task_id=self.task_id,
            success=success,
            execution_tokens=self.execution_tokens,
            module_events=self.module_events,
            final_output=FinalOutput(
                files_created=files_created,
                stdout=stdout,
                assistant_message=assistant_message,
            ),
        )
