"""Unit tests for the agent loop and evaluator."""

from __future__ import annotations

from pathlib import Path

from apo_skillsmd.agent.loop import AgentLoop
from apo_skillsmd.bench.skillsbench import SkillsBenchEvaluator, load_task_spec
from apo_skillsmd.llm.base import LLMClient, LLMResponse, LLMUsage, ToolCall
from apo_skillsmd.skill.loader import load_skill
from apo_skillsmd.types import ProviderName


class ScriptedTestLLM(LLMClient):
    """Stateless LLM stub that always writes the expected output file."""

    provider = ProviderName.MOCK

    def __init__(self) -> None:
        self.model = "scripted-test"
        self.last_temperature: float | None = None
        self.last_max_tokens: int | None = None

    def complete(self, messages, *, tools=None, temperature: float = 0.2, max_tokens: int = 2048):
        self.last_temperature = temperature
        self.last_max_tokens = max_tokens
        system_prompt = messages[0].content if messages else ""
        tool_messages = [message for message in messages if message.role.value == "tool"]
        if "Skill name: Skill Mutator" in system_prompt:
            if not tool_messages:
                return LLMResponse(
                    message="I will write the mutated child skill now.",
                    tool_calls=[
                        ToolCall(
                            id="mutation-call-1",
                            name="file_write",
                            args={
                                "path": "artifacts/child_skill/SKILL.md",
                                "content": (
                                    "---\n"
                                    "id: scripted-mutant\n"
                                    "name: Mock Mutated Skill\n"
                                    "description: Child skill emitted by the scripted mutation agent.\n"
                                    "version: 0.1.0\n"
                                    "tags:\n"
                                    "  - test\n"
                                    "  - mutation\n"
                                    "provenance:\n"
                                    "  source: scripted_meta_skill\n"
                                    "  parents: []\n"
                                    "  generation: 0\n"
                                    "---\n\n"
                                    "# Mock Mutated Skill\n\n"
                                    "## Goal\n"
                                    "Create the expected task outputs.\n\n"
                                    "## Workflow\n"
                                    "1. Read the task inputs.\n"
                                    "2. Write the required files.\n"
                                    "3. Finish with DONE.\n"
                                ),
                            },
                        ),
                        ToolCall(
                            id="mutation-call-2",
                            name="file_write",
                            args={
                                "path": "artifacts/child_skill/scripts/main.py",
                                "content": (
                                    '"""Mutation test child skill."""\n\n'
                                    "def main() -> str:\n"
                                    '    return "mutation"\n'
                                ),
                            },
                        ),
                    ],
                    usage=LLMUsage(input_tokens=12, output_tokens=10),
                )
            return LLMResponse(
                message="DONE: child skill written.",
                tool_calls=[],
                usage=LLMUsage(input_tokens=5, output_tokens=5),
            )
        if not tool_messages:
            return LLMResponse(
                message="I will create out.txt now.",
                tool_calls=[ToolCall(id="call-1", name="bash", args={"cmd": "printf 'hello\\n' > out.txt"})],
                usage=LLMUsage(input_tokens=10, output_tokens=8),
            )
        return LLMResponse(
            message="DONE: out.txt is ready.",
            tool_calls=[],
            usage=LLMUsage(input_tokens=4, output_tokens=5),
        )


def test_agent_loop_executes_tool_and_records_trace() -> None:
    root = Path("tests/fixtures")
    skill = load_skill(root / "mock_skill")
    task = load_task_spec(root / "mock_task.json")
    loop = AgentLoop(ScriptedTestLLM(), max_steps=4)

    result = loop.run(task, skill)

    assert result.success is True
    assert "DONE" in result.final_output
    assert "out.txt" in result.workspace_files
    assert result.trace.execution_tokens > 0
    assert any(event.module == "tool:bash" for event in result.trace.module_events)


def test_skillsbench_evaluator_computes_pass_rate() -> None:
    root = Path("tests/fixtures")
    skill = load_skill(root / "mock_skill")
    task = load_task_spec(root / "mock_task.json")
    evaluator = SkillsBenchEvaluator(AgentLoop(ScriptedTestLLM(), max_steps=4))

    evaluation = evaluator.evaluate(skill, task)

    assert evaluation.pass_rate == 1.0
    assert evaluation.execution_tokens > 0
    assert evaluation.case_results[0].passed is True


def test_agent_loop_uses_configured_llm_parameters() -> None:
    root = Path("tests/fixtures")
    skill = load_skill(root / "mock_skill")
    task = load_task_spec(root / "mock_task.json")
    llm = ScriptedTestLLM()
    loop = AgentLoop(llm, max_steps=4, llm_temperature=0.05, llm_max_tokens=512)

    result = loop.run(task, skill)

    assert result.success is True
    assert llm.last_temperature == 0.05
    assert llm.last_max_tokens == 512
