"""Run a condensed pilot for the SkillsBench software-dependency-audit task.

This script keeps the repository's default experiment flow intact and adds a
task-specific runner for the first formal pilot described in
`第一次实验数据设计-software-dependency-audit-20260413.md`.

Why a dedicated script?
- The official task depends on Trivy plus an offline vulnerability database.
- The repository's default `SubprocessSandbox` does not mount the task
  environment.
- The pilot needs a stronger, task-grounded execution environment than the
  synthetic JSON fixtures used by smoke tests.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
from hashlib import sha256
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from apo_skillsmd.agent.loop import AgentLoop
from apo_skillsmd.bench.skillsbench import EvaluationResult, SkillsBenchEvaluator
from apo_skillsmd.config import load_settings
from apo_skillsmd.evolution.loop import EvolutionDriver
from apo_skillsmd.safety.filter import SafetyFilter
from apo_skillsmd.sandbox.base import CommandResult, Sandbox
from apo_skillsmd.skill.loader import load_skill
from apo_skillsmd.skill.model import (
    ScriptFile,
    Skill,
    SkillFrontmatter,
    SkillProvenance,
    SkillResource,
)
from apo_skillsmd.skill.serializer import dump_skill
from apo_skillsmd.types import SandboxProfileName, TaskSpec, TaskTestCase, VerifierSpec


EXPECTED_CSV_CONTENT = """Package,Version,CVE_ID,Severity,CVSS_Score,Fixed_Version,Title,Url
ip,2.0.0,CVE-2024-29415,HIGH,8.1,N/A,node-ip: Incomplete fix for CVE-2023-42282,https://avd.aquasec.com/nvd/cve-2024-29415
semver,7.3.7,CVE-2022-25883,HIGH,7.5,"7.5.2, 6.3.1, 5.7.2",nodejs-semver: Regular expression denial of service,https://avd.aquasec.com/nvd/cve-2022-25883
tar,6.1.11,CVE-2026-23745,HIGH,8.2,7.5.3,node-tar: tar: node-tar: Arbitrary file overwrite and symlink poisoning via unsanitized linkpaths in archives,https://avd.aquasec.com/nvd/cve-2026-23745"""

CSV_HEADERS = [
    "Package",
    "Version",
    "CVE_ID",
    "Severity",
    "CVSS_Score",
    "Fixed_Version",
    "Title",
    "Url",
]


def _hash_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class TaskDockerSandbox(Sandbox):
    """Ephemeral Docker-backed sandbox for one task workspace.

    The official task environment already contains Trivy and the offline
    vulnerability database. We bind-mount a host workspace to `/workspace`,
    copy the task input files there, and run each tool command in a fresh
    container for isolation while keeping the workspace persistent.
    """

    def __init__(
        self,
        *,
        image_name: str,
        task_environment_dir: str | Path,
        profile: SandboxProfileName = SandboxProfileName.OFFLINE_LOCAL,
        max_output_chars: int = 6000,
        base_dir: str | Path | None = None,
    ) -> None:
        super().__init__(profile)
        self.image_name = image_name
        self.task_environment_dir = Path(task_environment_dir).resolve()
        self.max_output_chars = max_output_chars
        self._base_dir = Path(base_dir).resolve() if base_dir else None
        self._workspace: Path | None = None

    def setup(self, *, skill: Skill | None = None) -> None:
        base_dir = self._base_dir or Path(tempfile.mkdtemp(prefix="apo_skillsmd_sda_"))
        base_dir.mkdir(parents=True, exist_ok=True)
        self._workspace = base_dir
        if skill is not None:
            dump_skill(skill, base_dir)
        self._copy_task_environment()

    def teardown(self) -> None:
        if self._workspace is None or self._base_dir is not None:
            return
        shutil.rmtree(self._workspace, ignore_errors=True)
        self._workspace = None

    def workspace_root(self) -> Path:
        if self._workspace is None:
            raise RuntimeError("Sandbox has not been set up.")
        return self._workspace

    def _resolve(self, relative_path: str) -> Path:
        root = self.workspace_root().resolve()
        candidate = (root / relative_path).resolve()
        if not str(candidate).startswith(str(root)):
            raise ValueError(f"Path escapes sandbox root: {relative_path}")
        return candidate

    def _copy_task_environment(self) -> None:
        root = self.workspace_root()
        for path in self.task_environment_dir.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(self.task_environment_dir)
            if relative.parts and relative.parts[0] == "skills":
                continue
            if relative.as_posix() == "Dockerfile":
                continue
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

    def _snapshot(self) -> dict[str, str]:
        root = self.workspace_root()
        snapshot: dict[str, str] = {}
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            snapshot[path.relative_to(root).as_posix()] = _hash_file(path)
        return snapshot

    def run_bash(self, command: str, timeout_sec: int) -> CommandResult:
        before = self._snapshot()
        start = time.monotonic()
        shell_command = (
            "ln -sfn /root/trivy-cache /workspace/trivy-cache >/dev/null 2>&1 || true; "
            + command
        )
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--cpus",
            "1",
            "--memory",
            "4g",
            "-v",
            f"{self.workspace_root()}:/workspace",
            "-w",
            "/workspace",
            self.image_name,
            "/bin/sh",
            "-lc",
            shell_command,
        ]
        process = subprocess.Popen(
            docker_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_sec)
            timed_out = False
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            timed_out = True

        after = self._snapshot()
        changed_files = sorted(
            path for path, digest in after.items() if before.get(path) != digest or path not in before
        )
        return CommandResult(
            command=command,
            exit_code=process.returncode or 0,
            stdout=stdout[: self.max_output_chars],
            stderr=stderr[: self.max_output_chars],
            duration_ms=int((time.monotonic() - start) * 1000),
            timed_out=timed_out,
            changed_files=changed_files,
        )

    def read_file(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> str:
        file_path = self._resolve(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return path

    def list_files(self, path: str = ".") -> list[str]:
        root = self._resolve(path)
        workspace_root = self.workspace_root().resolve()
        if root.is_file():
            return [root.resolve().relative_to(workspace_root).as_posix()]
        return sorted(
            child.resolve().relative_to(workspace_root).as_posix()
            for child in root.rglob("*")
            if child.is_file()
        )


def _run_official_verifier(
    workspace: Path,
    tests_dir: Path,
    image_name: str,
    timeout_sec: int = 300,
) -> tuple[bool, list[str]]:
    """Run the official SkillsBench test.sh verifier inside Docker.

    Mounts the agent workspace as /root (where the verifier looks for
    security_audit.csv) and reads the reward from /logs/verifier/reward.txt.
    The verifier container needs network access to install pytest via pip.
    """
    logs_dir = workspace / "_verifier_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{workspace}:/root",
        "-v", f"{tests_dir}:/tests:ro",
        "-v", f"{logs_dir}:/logs/verifier",
        "-w", "/root",
        image_name,
        "/bin/sh", "-lc",
        (
            "pip3 install --quiet pytest 2>/dev/null; "
            "pytest /tests/test_outputs.py -rA -v "
            ">/logs/verifier/stdout.txt 2>/logs/verifier/stderr.txt; "
            "echo $? > /logs/verifier/reward.txt"
        ),
    ]
    proc = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout_sec)
    reward_file = logs_dir / "reward.txt"
    passed = reward_file.exists() and reward_file.read_text().strip() == "0"
    notes: list[str] = []
    if not passed:
        for log_file in ["stdout.txt", "stderr.txt"]:
            f = logs_dir / log_file
            if f.exists():
                for line in f.read_text().splitlines():
                    if any(kw in line for kw in ("FAILED", "AssertionError", "assert ", "Error", "not found")):
                        notes.append(line.strip())
        if not notes and not reward_file.exists():
            notes.append("verifier did not complete (reward.txt missing)")
    return passed, notes


class TaskDockerEvaluator(SkillsBenchEvaluator):
    """Evaluator that runs each skill inside the task's Docker environment."""

    def __init__(
        self,
        agent_loop: AgentLoop,
        *,
        image_name: str,
        task_environment_dir: str | Path,
        sandbox_profile: SandboxProfileName = SandboxProfileName.OFFLINE_LOCAL,
    ) -> None:
        super().__init__(agent_loop, sandbox_profile=sandbox_profile)
        self.image_name = image_name
        self.task_environment_dir = Path(task_environment_dir).resolve()
        self._tests_dir = self.task_environment_dir.parent / "tests"

    def evaluate(self, skill: Skill, task: TaskSpec) -> EvaluationResult:
        cases = task.test_cases or [TaskTestCase(case_id="default")]
        case_results = []
        total_tokens = 0

        for test_case in cases:
            case_task = task.model_copy(deep=True)
            case_task.inputs.update(test_case.input_payload)
            sandbox = TaskDockerSandbox(
                image_name=self.image_name,
                task_environment_dir=self.task_environment_dir,
                profile=self.sandbox_profile,
            )
            result = self.agent_loop.run(case_task, skill, sandbox=sandbox)
            passed, notes = _run_official_verifier(
                sandbox.workspace_root(),
                self._tests_dir,
                self.image_name,
            )
            total_tokens += result.token_usage
            case_results.append(
                {
                    "case_id": test_case.case_id,
                    "passed": passed,
                    "notes": notes,
                    "agent_result": result,
                }
            )
            sandbox.teardown()

        from apo_skillsmd.bench.skillsbench import CaseResult  # local import to avoid circular typing noise

        normalized_case_results = [CaseResult(**payload) for payload in case_results]
        passed_cases = sum(1 for case in normalized_case_results if case.passed)
        return EvaluationResult(
            task_id=task.task_id,
            passed_cases=passed_cases,
            total_cases=len(normalized_case_results),
            pass_rate=passed_cases / len(normalized_case_results) if normalized_case_results else 0.0,
            execution_tokens=total_tokens,
            case_results=normalized_case_results,
        )


def build_task_spec() -> TaskSpec:
    description = (
        "You are a software security engineer. The dependency lock file is available at "
        "`package-lock.json` in the workspace root. The offline Trivy cache is available "
        "at `trivy-cache/`. Use offline tools only. Detect only HIGH and CRITICAL "
        "vulnerabilities. Write `security_audit.csv` in the workspace root with columns "
        "Package,Version,CVE_ID,Severity,CVSS_Score,Fixed_Version,Title,Url."
    )
    return TaskSpec(
        task_id="skillsbench/software-dependency-audit",
        domain="security",
        description=description,
        inputs={
            "input_file": "package-lock.json",
            "offline_cache_dir": "trivy-cache",
            "output_file": "security_audit.csv",
            "allowed_severities": ["HIGH", "CRITICAL"],
            "required_columns": CSV_HEADERS,
        },
        verifier=VerifierSpec(kind="file", expected_file="security_audit.csv"),
        test_cases=[TaskTestCase(case_id="official-verifier")],
    )


def build_no_skill_baseline(task: TaskSpec) -> Skill:
    script_content = (
        '"""Minimal no-skill baseline placeholder."""\n\n'
        "def main() -> str:\n"
        '    return "baseline"\n'
    )
    skill = Skill(
        id="baseline-no-skill",
        frontmatter=SkillFrontmatter(
            name="No Skill Baseline",
            description="Minimal generic instructions without task-specific guidance.",
            tags=["baseline", "no-skill"],
        ),
        md_body=(
            "## Goal\n"
            "Solve the task using only the provided tools.\n\n"
            "## Workflow\n"
            "1. Inspect the workspace.\n"
            "2. Use available offline tools if present.\n"
            "3. Write the required output file.\n"
            "4. Return DONE with a concise summary.\n"
        ),
        scripts={
            "scripts/main.py": ScriptFile(
                relative_path="scripts/main.py",
                content=script_content,
                language="python",
            )
        },
        provenance=SkillProvenance(source="baseline_no_skill", generation=0),
    )
    skill.scripts["scripts/main.py"].content_hash = sha256(script_content.encode("utf-8")).hexdigest()
    skill.refresh_content_hash()
    return skill


def merge_skills(skills: list[Skill], *, skill_id: str, name: str, description: str) -> Skill:
    body_parts = []
    scripts: dict[str, ScriptFile] = {}
    resources: dict[str, SkillResource] = {}

    for index, skill in enumerate(skills, start=1):
        body_parts.append(f"## Module {index}: {skill.frontmatter.name}\n")
        body_parts.append(skill.md_body.strip())
        body_parts.append("")
        for relative_path, script in skill.scripts.items():
            merged_path = f"scripts/module_{index}_{Path(relative_path).name}"
            scripts[merged_path] = ScriptFile(
                relative_path=merged_path,
                content=script.content,
                language=script.language,
                is_executable=script.is_executable,
                content_hash=script.content_hash,
            )
        for relative_path, resource in skill.resources.items():
            merged_path = f"resources/module_{index}_{Path(relative_path).name}"
            resources[merged_path] = SkillResource(
                relative_path=merged_path,
                content=resource.content,
                content_hash=resource.content_hash,
            )

    merged = Skill(
        id=skill_id,
        frontmatter=SkillFrontmatter(
            name=name,
            description=description,
            tags=["baseline", "curated", "merged"],
        ),
        md_body="\n".join(body_parts).strip() + "\n",
        scripts=scripts,
        resources=resources,
        provenance=SkillProvenance(
            source="curated_bundle",
            parents=[skill.id for skill in skills],
            generation=0,
        ),
    )
    merged.refresh_content_hash()
    return merged


def _find_skill_by_name(root: Path, skill_name: str) -> Path:
    matches = sorted(root.rglob(f"*/{skill_name}/SKILL.md"))
    if not matches:
        raise FileNotFoundError(f"Unable to resolve skill {skill_name!r} under {root}")
    return matches[0].parent


def load_p0_skills(pool_root: Path, limit: int) -> list[Skill]:
    selected_names = [
        "dependency-management-deps-audit",
        "scanning-tools",
        "dependency-upgrade",
        "codebase-audit-pre-push",
        "audit-skills",
        "codebase-cleanup-deps-audit",
    ]
    loaded: list[Skill] = []
    seen_ids: set[str] = set()
    for skill_name in selected_names:
        try:
            skill = load_skill(_find_skill_by_name(pool_root, skill_name))
        except FileNotFoundError:
            continue
        if skill.id in seen_ids:
            continue
        loaded.append(skill)
        seen_ids.add(skill.id)
        if len(loaded) >= limit:
            break
    return loaded


def ensure_docker_image(task_environment_dir: Path, image_name: str) -> None:
    inspect = subprocess.run(
        ["docker", "image", "inspect", image_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if inspect.returncode == 0:
        return
    subprocess.run(
        ["docker", "build", "-t", image_name, str(task_environment_dir)],
        check=True,
    )


def evaluate_skill(
    evaluator: SkillsBenchEvaluator,
    skill: Skill,
    task: TaskSpec,
    *,
    label: str,
) -> dict[str, object]:
    print(f"[pilot] START {label}: {skill.id}", flush=True)
    started = time.monotonic()
    result = evaluator.evaluate(skill, task)
    duration_sec = time.monotonic() - started
    notes: list[str] = []
    for case in result.case_results:
        notes.extend(case.notes)
    row = {
        "condition": label,
        "skill_id": skill.id,
        "skill_name": skill.frontmatter.name,
        "passed": result.passed_cases == result.total_cases,
        "pass_rate": result.pass_rate,
        "runtime_tokens": result.execution_tokens,
        "runtime_seconds": round(duration_sec, 3),
        "notes": " | ".join(notes),
    }
    print(
        f"[pilot] DONE {label}: pass_rate={row['pass_rate']} tokens={row['runtime_tokens']} seconds={row['runtime_seconds']}",
        flush=True,
    )
    return row


def collect_search_token_cost(result) -> int:
    seen: set[str] = set()
    total = 0
    for record in result.generations:
        if record.generation == 0:
            for candidate in record.population:
                if candidate.skill.id not in seen:
                    seen.add(candidate.skill.id)
                    total += candidate.evaluation.execution_tokens
        for candidate in record.mutants + record.offspring:
            if candidate.skill.id not in seen:
                seen.add(candidate.skill.id)
                total += candidate.evaluation.execution_tokens
    return total


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the software-dependency-audit pilot.")
    parser.add_argument("--config", default="configs/default.yaml", help="Settings YAML file.")
    parser.add_argument(
        "--out",
        default="results/software_dependency_audit_pilot",
        help="Output directory for the pilot results.",
    )
    parser.add_argument(
        "--image-name",
        default="apo-skillsmd/software-dependency-audit:local",
        help="Docker image tag for the official task environment.",
    )
    parser.add_argument(
        "--max-p0",
        type=int,
        default=4,
        help="Maximum number of external pool skills to include in P0.",
    )
    parser.add_argument(
        "--population-size",
        type=int,
        default=3,
        help="Population size for the condensed APO-Full run.",
    )
    parser.add_argument(
        "--generations",
        type=int,
        default=1,
        help="Generation count for the condensed APO-Full run.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=4,
        help="Maximum agent steps per evaluation in the condensed pilot.",
    )
    parser.add_argument(
        "--skip-image-build",
        action="store_true",
        help="Assume the Docker image already exists.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    repo_root = Path(__file__).resolve().parent.parent
    out_dir = (repo_root / args.out).resolve()
    task_dir = repo_root / "data/skillsbench/tasks/software-dependency-audit"
    task_environment_dir = task_dir / "environment"
    curated_skills_dir = task_environment_dir / "skills"
    pool_root = repo_root / "data/skill_pool"

    if not args.skip_image_build:
        ensure_docker_image(task_environment_dir, args.image_name)

    settings = load_settings(args.config)
    settings.experiments.default_output_dir = str(out_dir)
    settings.evolution.population_size = args.population_size
    settings.evolution.generations = args.generations
    settings.llm.use_cache = False
    settings.llm.max_tokens = settings.llm.max_tokens  # use config value, no cap
    settings.llm.timeout_sec = max(settings.llm.timeout_sec, 180)
    settings.sandbox.command_timeout_sec = max(settings.sandbox.command_timeout_sec, 120)
    settings.sandbox.max_steps = args.max_steps

    from apo_skillsmd.llm.factory import build_llm

    llm = build_llm(settings)
    loop = AgentLoop(
        llm,
        max_steps=settings.sandbox.max_steps,
        command_timeout_sec=settings.sandbox.command_timeout_sec,
        sandbox_profile=settings.sandbox.profile,
        llm_temperature=settings.llm.temperature,
        llm_max_tokens=settings.llm.max_tokens,
    )
    evaluator = TaskDockerEvaluator(
        loop,
        image_name=args.image_name,
        task_environment_dir=task_environment_dir,
        sandbox_profile=settings.sandbox.profile,
    )
    task = build_task_spec()
    print(
        f"[pilot] task={task.task_id} provider={settings.llm.provider.value} model={settings.llm.model} "
        f"max_tokens={settings.llm.max_tokens} max_steps={settings.sandbox.max_steps}",
        flush=True,
    )

    curated_skills = [
        load_skill(curated_skills_dir / "trivy-offline-vulnerability-scanning"),
        load_skill(curated_skills_dir / "cvss-score-extraction"),
        load_skill(curated_skills_dir / "vulnerability-csv-reporting"),
    ]
    curated_bundle = merge_skills(
        curated_skills,
        skill_id="curated-software-dependency-audit-bundle",
        name="Curated Software Dependency Audit Bundle",
        description="Merged official SkillsBench curated skills for software-dependency-audit.",
    )
    no_skill = build_no_skill_baseline(task)

    p0_skills = load_p0_skills(pool_root, limit=args.max_p0)
    if not p0_skills:
        raise RuntimeError("Unable to construct P0 from the local external skill pool.")
    print(f"[pilot] P0 skill ids: {[skill.id for skill in p0_skills]}", flush=True)

    baseline_rows = [evaluate_skill(evaluator, no_skill, task, label="no_skill")]
    baseline_rows.append(evaluate_skill(evaluator, curated_bundle, task, label="curated_skills"))

    p0_rows = [evaluate_skill(evaluator, skill, task, label="p0_candidate") for skill in p0_skills]
    baseline_rows.extend(p0_rows)
    p0_best_row = max(p0_rows, key=lambda row: (float(row["pass_rate"]), -float(row["runtime_tokens"])))
    p0_best_skill = next(skill for skill in p0_skills if skill.id == p0_best_row["skill_id"])

    driver = EvolutionDriver(
        evaluator,
        SafetyFilter(),
        population_size=min(args.population_size, len(p0_skills)),
        generations=args.generations,
        mutation_meta_skill_dir=settings.paths.mutation_meta_skill_dir,
        mutation_workspace_root=settings.sandbox.workspace_root,
    )
    evolution_dir = out_dir / task.task_id.replace("/", "_")
    print(
        f"[pilot] START apo_full evolution: population={min(args.population_size, len(p0_skills))} "
        f"generations={args.generations}",
        flush=True,
    )
    evolution_result = driver.run(task, p0_skills, output_dir=evolution_dir)
    print(
        f"[pilot] DONE apo_full evolution: best_skill={evolution_result.best_skill_id} "
        f"best_pass_rate={evolution_result.best_pass_rate}",
        flush=True,
    )
    final_best_candidate = max(
        evolution_result.final_population,
        key=lambda candidate: (candidate.evaluation.pass_rate, -candidate.evaluation.execution_tokens),
    )
    final_best_skill = final_best_candidate.skill
    apo_full_row = evaluate_skill(evaluator, final_best_skill, task, label="apo_full")

    baseline_rows.append(
        {
            "condition": "p0_best",
            "skill_id": p0_best_skill.id,
            "skill_name": p0_best_skill.frontmatter.name,
            "passed": p0_best_row["passed"],
            "pass_rate": p0_best_row["pass_rate"],
            "runtime_tokens": p0_best_row["runtime_tokens"],
            "runtime_seconds": p0_best_row["runtime_seconds"],
            "notes": p0_best_row["notes"],
        }
    )
    baseline_rows.append(apo_full_row)

    write_csv(out_dir / "baseline_report.csv", baseline_rows)

    summary = {
        "task_id": task.task_id,
        "task_case": "software-dependency-audit",
        "task_source_doc": "第一次实验数据设计-software-dependency-audit-20260413.md",
        "provider": settings.llm.provider.value,
        "model": settings.llm.model,
        "max_tokens": settings.llm.max_tokens,
        "population_size": min(args.population_size, len(p0_skills)),
        "generations": args.generations,
        "p0_skill_ids": [skill.id for skill in p0_skills],
        "curated_skill_ids": [skill.id for skill in curated_skills],
        "search_token_cost": collect_search_token_cost(evolution_result),
        "p0_best_skill_id": p0_best_skill.id,
        "apo_full_best_skill_id": final_best_skill.id,
        "apo_full_best_pass_rate": final_best_candidate.evaluation.pass_rate,
        "baseline_rows": baseline_rows,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
