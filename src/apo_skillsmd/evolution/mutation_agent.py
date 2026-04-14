"""Mutation agent runner backed by a fixed meta-skill."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from apo_skillsmd.agent.loop import AgentLoop, AgentResult
from apo_skillsmd.sandbox.subprocess_backend import SubprocessSandbox
from apo_skillsmd.skill.loader import load_skill
from apo_skillsmd.skill.model import Skill
from apo_skillsmd.skill.serializer import dump_skill
from apo_skillsmd.trace.attribution import failing_modules
from apo_skillsmd.trace.schema import Trace
from apo_skillsmd.types import SandboxProfileName, TaskSpec


MUTATION_PARENT_SKILL_DIR = "inputs/parent_skill"
MUTATION_TRACE_PATH = "inputs/trace.json"
MUTATION_SPEC_PATH = "inputs/mutation_spec.json"
MUTATION_CHILD_SKILL_DIR = "artifacts/child_skill"


class MutationSpec(BaseModel):
    """Input bundle passed to the mutation agent."""

    parent_skill_id: str
    task_id: str
    generation: int
    failure_modules: list[str] = Field(default_factory=list)
    trace_path: str = MUTATION_TRACE_PATH
    parent_skill_dir: str = MUTATION_PARENT_SKILL_DIR
    output_dir: str = MUTATION_CHILD_SKILL_DIR
    mutation_goal: str = "Fix the observed failures while preserving unrelated behavior."

    def to_task_spec(self) -> TaskSpec:
        """Render the mutation request as a standard agent task."""

        description_lines = [
            "Mutate the parent skill based on the recorded execution trace.",
            "Follow a three-phase workflow: inspect inputs, write the child skill, then self-check before returning DONE.",
            "Read the parent skill and trace from the provided input paths.",
            "Keep unrelated behavior unchanged and write a full child skill package to the output directory.",
            "The child skill package is the only accepted output. Do not return a patch, partial snippet, or explanation-only answer.",
            "Any runtime workaround must be written back into the child skill package itself before returning DONE.",
            f"Parent skill id: {self.parent_skill_id}",
            f"Target generation: {self.generation}",
        ]
        if self.failure_modules:
            description_lines.append(
                "Failure modules: " + ", ".join(sorted(set(self.failure_modules)))
            )
        else:
            description_lines.append("No explicit failure module was recorded; make a conservative improvement.")
        description_lines.extend(
            [
                "Required self-check before DONE:",
                f"1. `{self.output_dir}/SKILL.md` exists.",
                f"2. `{self.output_dir}/scripts/` exists if the skill needs executable helpers.",
                "3. SKILL.md documents the updated workflow and does not rely on external reference docs.",
                "4. Import examples, if present, should prefer portable sys.path-based imports over package-style imports.",
            ]
        )

        return TaskSpec(
            task_id=f"mutation/{self.parent_skill_id}/g{self.generation}",
            domain="mutation",
            description="\n".join(description_lines),
            inputs={
                "parent_skill_dir": self.parent_skill_dir,
                "trace_path": self.trace_path,
                "mutation_spec_path": MUTATION_SPEC_PATH,
                "output_dir": self.output_dir,
                "mutation_goal": self.mutation_goal,
            },
        )


class MutationAgentRunner:
    """Run one meta-skill that rewrites another skill package."""

    def __init__(
        self,
        llm,
        *,
        meta_skill_dir: str | Path,
        max_steps: int = 8,
        command_timeout_sec: int = 30,
        sandbox_profile: SandboxProfileName = SandboxProfileName.OFFLINE_LOCAL,
        workspace_root: str | Path | None = None,
    ) -> None:
        self.meta_skill_dir = Path(meta_skill_dir)
        self.meta_skill = load_skill(self.meta_skill_dir)
        self.max_steps = max_steps
        self.command_timeout_sec = command_timeout_sec
        self.sandbox_profile = sandbox_profile
        self.workspace_root = Path(workspace_root) if workspace_root is not None else None
        self.agent_loop = AgentLoop(
            llm,
            max_steps=max_steps,
            command_timeout_sec=command_timeout_sec,
            sandbox_profile=sandbox_profile,
        )

    def _make_workspace_dir(self, parent_skill: Skill, generation: int) -> Path:
        if self.workspace_root is None:
            return Path(tempfile.mkdtemp(prefix="apo_skillsmd_mutation_"))

        root = self.workspace_root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        return Path(
            tempfile.mkdtemp(
                prefix=f"{parent_skill.id.replace('/', '_')}_g{generation}_",
                dir=root,
            )
        )

    def _prepare_workspace(self, workspace_dir: Path, parent_skill: Skill, spec: MutationSpec, trace: Trace) -> None:
        inputs_dir = workspace_dir / "inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        dump_skill(parent_skill, workspace_dir / spec.parent_skill_dir)
        (workspace_dir / spec.trace_path).write_text(
            trace.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (workspace_dir / MUTATION_SPEC_PATH).write_text(
            spec.model_dump_json(indent=2),
            encoding="utf-8",
        )
        (workspace_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    def _apply_success_metadata(
        self,
        child_skill: Skill,
        parent_skill: Skill,
        *,
        generation: int,
        agent_result: AgentResult,
    ) -> Skill:
        child_skill.id = f"{parent_skill.id}-mut-g{generation}"
        child_skill.provenance.parents = [parent_skill.id]
        child_skill.provenance.generation = generation
        child_skill.provenance.source = "trace_mutation_agent"
        child_skill.provenance.notes.append(
            f"Mutated via meta skill {self.meta_skill.id}."
        )
        if agent_result.final_output:
            child_skill.provenance.notes.append(agent_result.final_output)
        child_skill.refresh_content_hash()
        return child_skill

    def _build_fallback_mutant(
        self,
        parent_skill: Skill,
        *,
        generation: int,
        reason: str,
    ) -> Skill:
        fallback = parent_skill.clone(new_id=f"{parent_skill.id}-mut-g{generation}")
        fallback.provenance.parents = [parent_skill.id]
        fallback.provenance.generation = generation
        fallback.provenance.source = "trace_mutation_agent_fallback"
        fallback.provenance.notes.append(f"Mutation agent fallback: {reason}")
        fallback.provenance.notes.append(f"Meta skill: {self.meta_skill.id}")
        fallback.refresh_content_hash()
        return fallback

    def mutate(self, parent_skill: Skill, trace: Trace, *, generation: int) -> Skill:
        """Run the mutation agent and return a new child skill."""

        spec = MutationSpec(
            parent_skill_id=parent_skill.id,
            task_id=trace.task_id,
            generation=generation,
            failure_modules=failing_modules(trace),
        )
        workspace_dir = self._make_workspace_dir(parent_skill, generation)
        self._prepare_workspace(workspace_dir, parent_skill, spec, trace)
        sandbox = SubprocessSandbox(
            self.sandbox_profile,
            base_dir=workspace_dir,
            max_output_chars=6000,
        )
        try:
            result = self.agent_loop.run(spec.to_task_spec(), self.meta_skill, sandbox=sandbox)
            child_skill_dir = workspace_dir / MUTATION_CHILD_SKILL_DIR
            if not child_skill_dir.exists():
                sandbox.teardown()
                return self._build_fallback_mutant(
                    parent_skill,
                    generation=generation,
                    reason="missing child skill directory",
                )

            try:
                child_skill = load_skill(child_skill_dir)
            except Exception as exc:
                sandbox.teardown()
                return self._build_fallback_mutant(
                    parent_skill,
                    generation=generation,
                    reason=f"failed to load child skill: {exc}",
                )

            return self._apply_success_metadata(
                child_skill,
                parent_skill,
                generation=generation,
                agent_result=result,
            )
        except Exception as exc:
            sandbox.teardown()
            return self._build_fallback_mutant(
                parent_skill,
                generation=generation,
                reason=f"mutation agent execution failed: {exc}",
            )
