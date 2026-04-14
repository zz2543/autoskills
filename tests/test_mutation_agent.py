"""Unit tests for the mutation agent runner."""

from __future__ import annotations

from pathlib import Path

from apo_skillsmd.evolution.mutation_agent import MutationAgentRunner
from apo_skillsmd.llm.base import LLMClient, LLMResponse, LLMUsage
from apo_skillsmd.skill.loader import load_skill
from apo_skillsmd.trace.schema import ModuleEvent, Trace
from apo_skillsmd.types import ProviderName
from meta_skills.skill_mutator.scripts.skill_checks import (
    child_skill_missing_items,
    has_non_portable_import_examples,
)
from meta_skills.skill_mutator.scripts.trace_tools import failing_modules, summarize_trace
from tests.test_agent_loop_mock import ScriptedTestLLM


class EmptyMutationLLM(LLMClient):
    """Mutation stub that never writes the child skill directory."""

    provider = ProviderName.MOCK

    def __init__(self) -> None:
        self.model = "empty-mutation"

    def complete(self, messages, *, tools=None, temperature: float = 0.2, max_tokens: int = 2048):
        return LLMResponse(
            message="DONE: no child skill written.",
            tool_calls=[],
            usage=LLMUsage(input_tokens=2, output_tokens=2),
        )


def build_failure_trace() -> Trace:
    return Trace(
        skill_id="mock-skill",
        task_id="tests/mock-task",
        success=False,
        execution_tokens=17,
        module_events=[
            ModuleEvent(
                module="scripts/formatter.py:format_output",
                entered=True,
                exceptions=["ValueError: bad output"],
                duration_ms=3,
                output_summary="format failure",
            )
        ],
    )


def test_mutation_agent_runner_loads_child_skill_from_agent_output(tmp_path: Path) -> None:
    runner = MutationAgentRunner(
        ScriptedTestLLM(),
        meta_skill_dir=Path("meta_skills/skill_mutator"),
        max_steps=4,
        workspace_root=tmp_path,
    )
    parent_skill = load_skill(Path("tests/fixtures/mock_skill"))

    child_skill = runner.mutate(parent_skill, build_failure_trace(), generation=1)

    assert child_skill.id == "mock-skill-mut-g1"
    assert child_skill.frontmatter.name == "Mock Mutated Skill"
    assert child_skill.provenance.source == "trace_mutation_agent"
    assert child_skill.provenance.parents == ["mock-skill"]
    assert child_skill.path is not None
    assert Path(child_skill.path).exists()


def test_mutation_agent_runner_falls_back_when_child_skill_is_missing(tmp_path: Path) -> None:
    runner = MutationAgentRunner(
        EmptyMutationLLM(),
        meta_skill_dir=Path("meta_skills/skill_mutator"),
        max_steps=2,
        workspace_root=tmp_path,
    )
    parent_skill = load_skill(Path("tests/fixtures/mock_skill"))

    child_skill = runner.mutate(parent_skill, build_failure_trace(), generation=2)

    assert child_skill.id == "mock-skill-mut-g2"
    assert child_skill.md_body == parent_skill.md_body
    assert child_skill.provenance.source == "trace_mutation_agent_fallback"
    assert any("missing child skill directory" in note for note in child_skill.provenance.notes)


def test_meta_skill_helper_scripts_cover_trace_and_child_skill_checks(tmp_path: Path) -> None:
    trace = build_failure_trace().model_dump()
    assert failing_modules(trace) == ["scripts/formatter.py:format_output"]
    assert "Observed failures in:" in summarize_trace(trace)

    child_dir = tmp_path / "child_skill"
    child_dir.mkdir()
    assert child_skill_missing_items(child_dir) == ["SKILL.md", "scripts/"]
    assert has_non_portable_import_examples("from evo_example.scripts.utils import main") is True
