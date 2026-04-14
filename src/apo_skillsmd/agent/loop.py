"""Provider-agnostic agent loop."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from apo_skillsmd.agent.prompt import build_system_prompt, build_task_prompt
from apo_skillsmd.agent.tools import DEFAULT_TOOL_SCHEMAS, ToolExecutor
from apo_skillsmd.llm.base import LLMClient, LLMMessage
from apo_skillsmd.sandbox.base import Sandbox
from apo_skillsmd.sandbox.subprocess_backend import SubprocessSandbox
from apo_skillsmd.skill.model import Skill
from apo_skillsmd.trace.recorder import TraceRecorder
from apo_skillsmd.trace.schema import Trace
from apo_skillsmd.types import MessageRole, SandboxProfileName, TaskSpec


class AgentResult(BaseModel):
    """Result returned by one agent run on one task."""

    success: bool
    final_output: str
    token_usage: int
    steps: int
    trace: Trace
    workspace_files: list[str] = Field(default_factory=list)
    workspace_root: str | None = None


class AgentLoop:
    """Run a skill against a task through repeated LLM + tool turns."""

    def __init__(
        self,
        llm: LLMClient,
        *,
        max_steps: int = 8,
        command_timeout_sec: int = 30,
        sandbox_profile: SandboxProfileName = SandboxProfileName.OFFLINE_LOCAL,
    ) -> None:
        self.llm = llm
        self.max_steps = max_steps
        self.command_timeout_sec = command_timeout_sec
        self.sandbox_profile = sandbox_profile

    def _build_default_sandbox(self) -> SubprocessSandbox:
        return SubprocessSandbox(
            self.sandbox_profile,
            max_output_chars=6000,
        )

    def run(self, task: TaskSpec, skill: Skill, *, sandbox: Sandbox | None = None) -> AgentResult:
        """Execute the skill on one task and return the resulting trace."""

        active_sandbox = sandbox or self._build_default_sandbox()
        owns_sandbox = sandbox is None
        final_message = ""
        try:
            active_sandbox.setup(skill=skill)
            recorder = TraceRecorder(skill_id=skill.id, task_id=task.task_id)
            executor = ToolExecutor(active_sandbox, default_timeout_sec=self.command_timeout_sec)
            messages = [
                LLMMessage(role=MessageRole.SYSTEM, content=build_system_prompt(skill)),
                LLMMessage(role=MessageRole.USER, content=build_task_prompt(task)),
            ]

            for step in range(1, self.max_steps + 1):
                response = self.llm.complete(
                    messages,
                    tools=DEFAULT_TOOL_SCHEMAS,
                    temperature=0.2,
                    max_tokens=2048,
                )
                recorder.record_llm_usage(response.usage)
                messages.append(
                    LLMMessage(
                        role=MessageRole.ASSISTANT,
                        content=response.message,
                        tool_calls=response.tool_calls,
                    )
                )

                if response.tool_calls:
                    for call in response.tool_calls:
                        tool_result, duration_ms, changed_files = executor.execute(call)
                        recorder.record_tool_result(
                            call,
                            tool_result,
                            duration_ms=duration_ms,
                            changed_files=changed_files,
                        )
                        messages.append(
                            LLMMessage(
                                role=MessageRole.TOOL,
                                content=tool_result.content,
                                name=tool_result.name,
                                tool_call_id=tool_result.call_id,
                            )
                        )
                    continue

                final_message = response.message.strip()
                if not response.tool_calls:
                    break

            workspace_files = active_sandbox.list_files(".")
            trace = recorder.finalize(
                success=bool(final_message),
                assistant_message=final_message,
                files_created=workspace_files,
            )
            return AgentResult(
                success=trace.success,
                final_output=final_message,
                token_usage=trace.execution_tokens,
                steps=step,
                trace=trace,
                workspace_files=workspace_files,
                workspace_root=str(active_sandbox.workspace_root()),
            )
        finally:
            if owns_sandbox:
                active_sandbox.teardown()
