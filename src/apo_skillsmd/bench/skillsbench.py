"""SkillsBench task loader and evaluator."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from apo_skillsmd.agent.loop import AgentLoop, AgentResult
from apo_skillsmd.safety.runtime_guard import detect_hardcoded_answer
from apo_skillsmd.sandbox.subprocess_backend import SubprocessSandbox
from apo_skillsmd.skill.model import Skill
from apo_skillsmd.types import SandboxProfileName, SkillEvaluation, TaskSpec, TaskTestCase, VerifierSpec


def load_task_spec(path: str | Path) -> TaskSpec:
    """Load a task spec from JSON or YAML."""

    file_path = Path(path)
    content = file_path.read_text(encoding="utf-8")
    if file_path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(content)
    else:
        data = json.loads(content)
    return TaskSpec.model_validate(data)


class CaseResult(BaseModel):
    """Verification result for one benchmark test case."""

    case_id: str
    passed: bool
    notes: list[str] = Field(default_factory=list)
    agent_result: AgentResult


class EvaluationResult(BaseModel):
    """Aggregated result over all test cases for one task."""

    task_id: str
    passed_cases: int
    total_cases: int
    pass_rate: float
    execution_tokens: int
    case_results: list[CaseResult] = Field(default_factory=list)

    def as_skill_evaluation(self) -> SkillEvaluation:
        return SkillEvaluation(
            pass_rate=self.pass_rate,
            execution_tokens=self.execution_tokens,
            success=self.passed_cases == self.total_cases,
            notes=[note for case in self.case_results for note in case.notes],
        )


class SkillsBenchEvaluator:
    """Evaluate one skill against a benchmark task."""

    def __init__(
        self,
        agent_loop: AgentLoop,
        *,
        sandbox_profile: SandboxProfileName = SandboxProfileName.OFFLINE_LOCAL,
        verifier_timeout_sec: int = 60,
    ) -> None:
        self.agent_loop = agent_loop
        self.sandbox_profile = sandbox_profile
        self.verifier_timeout_sec = verifier_timeout_sec

    def _check_hardcoded_answers(self, skill: Skill, test_case: TaskTestCase) -> list[str]:
        """Soft-detect whether skill scripts contain the expected answer verbatim."""
        warnings: list[str] = []
        for expected_val in test_case.expected_output.values():
            if not isinstance(expected_val, str):
                continue
            for script_path, script_file in skill.scripts.items():
                if detect_hardcoded_answer(expected_val, script_file.content):
                    warnings.append(f"[soft-warn] possible hardcoded answer in {script_path}")
        return warnings

    def _verify(
        self,
        task: TaskSpec,
        test_case: TaskTestCase,
        result: AgentResult,
        sandbox: SubprocessSandbox,
        skill: Skill,
    ) -> tuple[bool, list[str]]:
        notes: list[str] = []
        verifier: VerifierSpec = task.verifier
        passed = True

        # --- official command verifier ---
        if verifier.command:
            cmd_result = sandbox.run_bash(verifier.command, timeout_sec=self.verifier_timeout_sec)
            if cmd_result.exit_code != 0:
                passed = False
                notes.append(
                    f"official verifier exited {cmd_result.exit_code}: {cmd_result.stderr[:300]}"
                )

        # --- expected stdout substring check ---
        if verifier.expected_stdout_contains:
            matched = verifier.expected_stdout_contains in result.final_output
            passed &= matched
            if not matched:
                notes.append(
                    f"assistant output missing substring: {verifier.expected_stdout_contains!r}"
                )

        # --- expected file existence / content check ---
        if verifier.expected_file:
            target = Path(verifier.expected_file)
            if target.as_posix() not in result.workspace_files:
                passed = False
                notes.append(f"expected file missing: {verifier.expected_file}")
            elif test_case.expected_output:
                expected_content = test_case.expected_output.get("content")
                if expected_content is not None:
                    observed = sandbox.read_file(verifier.expected_file)
                    if observed != expected_content:
                        passed = False
                        notes.append(f"file content mismatch: {verifier.expected_file}")

        # --- soft runtime guard: hardcoded answer detection ---
        notes.extend(self._check_hardcoded_answers(skill, test_case))

        return passed, notes

    def evaluate(self, skill: Skill, task: TaskSpec) -> EvaluationResult:
        """Run all task cases and aggregate pass rate plus token usage."""

        cases = task.test_cases or [TaskTestCase(case_id="default")]
        case_results: list[CaseResult] = []
        total_tokens = 0

        for test_case in cases:
            case_task = task.model_copy(deep=True)
            case_task.inputs.update(test_case.input_payload)
            sandbox = SubprocessSandbox(self.sandbox_profile)
            result = self.agent_loop.run(case_task, skill, sandbox=sandbox)
            passed, notes = self._verify(case_task, test_case, result, sandbox, skill)
            total_tokens += result.token_usage
            case_results.append(
                CaseResult(
                    case_id=test_case.case_id,
                    passed=passed,
                    notes=notes,
                    agent_result=result,
                )
            )
            sandbox.teardown()

        passed_cases = sum(1 for case in case_results if case.passed)
        return EvaluationResult(
            task_id=task.task_id,
            passed_cases=passed_cases,
            total_cases=len(case_results),
            pass_rate=passed_cases / len(case_results) if case_results else 0.0,
            execution_tokens=total_tokens,
            case_results=case_results,
        )
