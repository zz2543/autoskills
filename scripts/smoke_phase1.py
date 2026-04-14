"""Phase 1 smoke test for the provider-agnostic agent loop."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from apo_skillsmd.agent.loop import AgentLoop
from apo_skillsmd.bench.skillsbench import load_task_spec
from apo_skillsmd.llm.base import LLMClient, LLMResponse, LLMUsage, ToolCall
from apo_skillsmd.skill.loader import load_skill
from apo_skillsmd.types import ProviderName


class ScriptedSmokeLLM(LLMClient):
    """A deterministic LLM used to validate the loop without external API calls."""

    provider = ProviderName.MOCK

    def __init__(self) -> None:
        self.model = "scripted-smoke"

    def complete(self, messages, *, tools=None, temperature: float = 0.2, max_tokens: int = 2048):
        tool_messages = [message for message in messages if message.role.value == "tool"]
        if not tool_messages:
            return LLMResponse(
                message="Creating the requested file.",
                tool_calls=[ToolCall(id="call-1", name="bash", args={"cmd": "printf 'hello\\n' > out.txt"})],
                usage=LLMUsage(input_tokens=10, output_tokens=8),
            )
        return LLMResponse(
            message="DONE: created out.txt with the expected content.",
            tool_calls=[],
            usage=LLMUsage(input_tokens=6, output_tokens=6),
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Phase 1 smoke test.")
    parser.add_argument("--skill", required=True, help="Path to the skill directory.")
    parser.add_argument("--task", required=True, help="Path to the task JSON or YAML file.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    skill = load_skill(args.skill)
    task = load_task_spec(args.task)
    loop = AgentLoop(ScriptedSmokeLLM(), max_steps=4)
    result = loop.run(task, skill)
    summary = {
        "success": result.success,
        "final_output": result.final_output,
        "token_usage": result.token_usage,
        "workspace_files": result.workspace_files,
        "trace_modules": [event.module for event in result.trace.module_events],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
