"""Complete APO-SkillsMD pilot for the SkillsBench parallel-tfidf-search task.

Runs the full loop:
  P0 initialization → multi-trial baseline evaluation
  → APO-Full evolution (mutation + crossover)
  → multi-trial report evaluation
  → narrative summary of evolution lineage and pass rates.
"""

from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import time
from hashlib import sha256
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from apo_skillsmd.agent.loop import AgentLoop
from apo_skillsmd.bench.skillsbench import EvaluationResult, SkillsBenchEvaluator
from apo_skillsmd.config import load_settings
from apo_skillsmd.evolution.loop import EvolutionDriver, EvolutionRunResult
from apo_skillsmd.safety.filter import SafetyFilter
from apo_skillsmd.sandbox.base import CommandResult, Sandbox
from apo_skillsmd.skill.loader import load_skill
from apo_skillsmd.skill.model import Skill, SkillFrontmatter, SkillProvenance, ScriptFile
from apo_skillsmd.skill.serializer import dump_skill
from apo_skillsmd.types import SandboxProfileName, TaskSpec, TaskTestCase, VerifierSpec

TASK_ID = "skillsbench/parallel-tfidf-search"
IMAGE_NAME = "apo-skillsmd/parallel-tfidf-search:local"
REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_DIR = REPO_ROOT / "data/skillsbench/tasks/parallel-tfidf-search"


# ---------------------------------------------------------------------------
# Docker sandbox
# ---------------------------------------------------------------------------

class TaskDockerSandbox(Sandbox):
    def __init__(self, *, image_name: str, task_environment_dir: Path,
                 profile: SandboxProfileName = SandboxProfileName.OFFLINE_LOCAL,
                 max_output_chars: int = 8000) -> None:
        super().__init__(profile)
        self.image_name = image_name
        self.task_environment_dir = task_environment_dir
        self.max_output_chars = max_output_chars
        self._workspace: Path | None = None
        self._owned = True

    def setup(self, *, skill: Skill | None = None) -> None:
        ws = Path(tempfile.mkdtemp(prefix="apo_tfidf_"))
        self._workspace = ws
        # Pre-populate workspace with the Docker image's /root/workspace so
        # the agent can read the sequential baseline and write its solution
        # into the same mounted directory.
        subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{ws}:/out",
             self.image_name,
             "/bin/sh", "-c", "cp -r /root/workspace/. /out/ 2>/dev/null || true"],
            capture_output=True, timeout=30,
        )
        if skill is not None:
            dump_skill(skill, ws)

    def teardown(self) -> None:
        if self._workspace and self._owned:
            shutil.rmtree(self._workspace, ignore_errors=True)
            self._workspace = None

    def workspace_root(self) -> Path:
        if self._workspace is None:
            raise RuntimeError("Sandbox not set up")
        return self._workspace

    def _resolve(self, path: str) -> Path:
        root = self.workspace_root().resolve()
        candidate = (root / path).resolve()
        if not str(candidate).startswith(str(root)):
            raise ValueError(f"Path escapes sandbox: {path}")
        return candidate

    def run_bash(self, command: str, timeout_sec: int) -> CommandResult:
        before = self._snapshot()
        start = time.monotonic()
        # Mount the host workspace as /root/workspace so the agent reads the
        # sequential baseline and writes parallel_solution.py to the host.
        docker_cmd = [
            "docker", "run", "--rm", "--network", "none",
            "--cpus", "4", "--memory", "4g",
            "-v", f"{self.workspace_root()}:/root/workspace",
            "-w", "/root/workspace",
            self.image_name, "/bin/sh", "-lc", command,
        ]
        proc = subprocess.Popen(docker_cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        try:
            stdout, stderr = proc.communicate(timeout=timeout_sec)
            timed_out = False
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            timed_out = True

        after = self._snapshot()
        changed = sorted(p for p, h in after.items() if before.get(p) != h or p not in before)
        return CommandResult(
            command=command, exit_code=proc.returncode or 0,
            stdout=stdout[:self.max_output_chars], stderr=stderr[:self.max_output_chars],
            duration_ms=int((time.monotonic() - start) * 1000),
            timed_out=timed_out, changed_files=changed,
        )

    def _snapshot(self) -> dict[str, str]:
        root = self.workspace_root()
        out: dict[str, str] = {}
        for p in root.rglob("*"):
            if p.is_file():
                out[p.relative_to(root).as_posix()] = sha256(p.read_bytes()).hexdigest()
        return out

    def read_file(self, path: str) -> str:
        return self._resolve(path).read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> str:
        fp = self._resolve(path)
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(content, encoding="utf-8")
        return path

    def list_files(self, path: str = ".") -> list[str]:
        root = self._resolve(path)
        ws = self.workspace_root().resolve()
        if root.is_file():
            return [root.resolve().relative_to(ws).as_posix()]
        return sorted(c.resolve().relative_to(ws).as_posix()
                      for c in root.rglob("*") if c.is_file())


# ---------------------------------------------------------------------------
# Official verifier
# ---------------------------------------------------------------------------

def _run_official_verifier(workspace: Path, tests_dir: Path,
                            image_name: str, timeout_sec: int = 300) -> tuple[bool, list[str]]:
    """Run the official pytest verifier inside Docker; return (passed, notes)."""
    logs_dir = workspace / "_verifier_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Copy the agent's parallel_solution.py into a temp workspace that mirrors
    # /root/workspace so the verifier can import it.
    if not (workspace / "parallel_solution.py").exists():
        return False, ["parallel_solution.py not found in agent workspace"]

    # Mount the whole workspace as /root/workspace so tests can import both
    # the sequential baseline and the agent's parallel_solution.py.
    docker_cmd = [
        "docker", "run", "--rm",
        "--cpus", "4",
        "-v", f"{workspace}:/root/workspace:ro",
        "-v", f"{tests_dir}:/tests:ro",
        "-v", f"{logs_dir}:/logs/verifier",
        image_name,
        "/bin/sh", "-lc",
        (
            "pip3 install --quiet pytest 2>/dev/null; "
            "cd /root/workspace && "
            "pytest /tests/test_outputs.py -v "
            ">/logs/verifier/stdout.txt 2>/logs/verifier/stderr.txt; "
            "echo $? > /logs/verifier/reward.txt"
        ),
    ]
    subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout_sec)

    reward_file = logs_dir / "reward.txt"
    passed = reward_file.exists() and reward_file.read_text().strip() == "0"
    notes: list[str] = []
    if not passed:
        for fname in ("stdout.txt", "stderr.txt"):
            fpath = logs_dir / fname
            if fpath.exists():
                for line in fpath.read_text().splitlines():
                    if any(kw in line for kw in ("FAILED", "PASSED", "Error", "assert", "error")):
                        notes.append(line.strip())
        if not notes and not reward_file.exists():
            notes.append("verifier did not complete")
    return passed, notes


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class TFIDFEvaluator(SkillsBenchEvaluator):
    def __init__(self, agent_loop: AgentLoop, *,
                 task_environment_dir: Path,
                 sandbox_profile: SandboxProfileName = SandboxProfileName.OFFLINE_LOCAL) -> None:
        super().__init__(agent_loop, sandbox_profile=sandbox_profile)
        self.task_environment_dir = task_environment_dir
        self._tests_dir = task_environment_dir.parent / "tests"

    def evaluate(self, skill: Skill, task: TaskSpec) -> EvaluationResult:
        sandbox = TaskDockerSandbox(
            image_name=IMAGE_NAME,
            task_environment_dir=self.task_environment_dir,
            profile=self.sandbox_profile,
        )
        result = self.agent_loop.run(task, skill, sandbox=sandbox)
        passed, notes = _run_official_verifier(
            sandbox.workspace_root(), self._tests_dir, IMAGE_NAME
        )
        sandbox.teardown()

        from apo_skillsmd.bench.skillsbench import CaseResult
        case = CaseResult(
            case_id="official-verifier",
            passed=passed,
            notes=notes,
            agent_result=result,
        )
        return EvaluationResult(
            task_id=task.task_id,
            passed_cases=1 if passed else 0,
            total_cases=1,
            pass_rate=1.0 if passed else 0.0,
            execution_tokens=result.token_usage,
            case_results=[case],
        )


# ---------------------------------------------------------------------------
# Multi-trial wrapper
# ---------------------------------------------------------------------------

def evaluate_n_trials(evaluator: TFIDFEvaluator, skill: Skill, task: TaskSpec,
                      n: int, label: str) -> dict:
    results = []
    for i in range(n):
        print(f"  [trial {i+1}/{n}] {label}: {skill.id}", flush=True)
        r = evaluator.evaluate(skill, task)
        results.append(r)
    pass_rate = mean(r.pass_rate for r in results)
    avg_tokens = int(mean(r.execution_tokens for r in results))
    notes = [note for r in results for case in r.case_results for note in case.notes]
    print(f"  → {label} avg pass_rate={pass_rate:.2f} avg_tokens={avg_tokens}", flush=True)
    return {
        "condition": label,
        "skill_id": skill.id,
        "skill_name": skill.frontmatter.name,
        "n_trials": n,
        "pass_rate": pass_rate,
        "trials": [{"passed": r.pass_rate == 1.0, "tokens": r.execution_tokens} for r in results],
        "avg_tokens": avg_tokens,
        "notes": list(dict.fromkeys(notes))[:3],
    }


# ---------------------------------------------------------------------------
# Task spec and skills
# ---------------------------------------------------------------------------

def build_task_spec() -> TaskSpec:
    instruction = (TASK_DIR / "instruction.md").read_text(encoding="utf-8")
    return TaskSpec(
        task_id=TASK_ID,
        domain="software-engineering",
        description=instruction,
        inputs={"workspace_dir": "/root/workspace"},
        verifier=VerifierSpec(kind="file", expected_file="parallel_solution.py"),
        test_cases=[TaskTestCase(case_id="official-verifier")],
    )


def build_no_skill() -> Skill:
    body = (
        "## Goal\nSolve the assigned programming task.\n\n"
        "## Workflow\n"
        "1. Read the task description carefully.\n"
        "2. Explore the workspace to understand the existing code.\n"
        "3. Write the required solution file.\n"
        "4. Return DONE with a summary.\n"
    )
    script_content = '"""No-skill baseline."""\ndef main(): return "baseline"\n'
    skill = Skill(
        id="baseline-no-skill",
        frontmatter=SkillFrontmatter(name="No Skill Baseline",
                                      description="Generic instructions only.",
                                      tags=["baseline"]),
        md_body=body,
        scripts={"scripts/main.py": ScriptFile(
            relative_path="scripts/main.py", content=script_content, language="python",
            content_hash=sha256(script_content.encode()).hexdigest())},
        provenance=SkillProvenance(source="baseline", generation=0),
    )
    skill.refresh_content_hash()
    return skill


def _find_skill(pool_root: Path, name: str) -> Path:
    matches = sorted(pool_root.rglob(f"*/{name}/SKILL.md"))
    if not matches:
        raise FileNotFoundError(f"Skill not found: {name}")
    return matches[0].parent


def load_p0_skills(pool_root: Path) -> list[Skill]:
    names = [
        "async-python-patterns",
        "dispatching-parallel-agents",
        "application-performance-performance-optimization",
        "context-optimization",
    ]
    skills = []
    for name in names:
        try:
            skills.append(load_skill(_find_skill(pool_root, name)))
        except FileNotFoundError:
            print(f"  [warn] P0 skill not found: {name}", flush=True)
    return skills


def load_curated_skills(curated_dir: Path) -> list[Skill]:
    skills = []
    for skill_dir in sorted(curated_dir.iterdir()):
        if (skill_dir / "SKILL.md").exists():
            skills.append(load_skill(skill_dir))
    return skills


def merge_skills(skills: list[Skill], *, skill_id: str, name: str) -> Skill:
    from apo_skillsmd.skill.model import SkillResource
    body_parts, scripts, resources = [], {}, {}
    for i, sk in enumerate(skills, 1):
        body_parts.append(f"## Module {i}: {sk.frontmatter.name}\n{sk.md_body.strip()}\n")
        for rp, sf in sk.scripts.items():
            mp = f"scripts/m{i}_{Path(rp).name}"
            scripts[mp] = ScriptFile(relative_path=mp, content=sf.content,
                                      language=sf.language, content_hash=sf.content_hash)
        for rp, res in sk.resources.items():
            mp = f"resources/m{i}_{Path(rp).name}"
            resources[mp] = SkillResource(relative_path=mp, content=res.content,
                                           content_hash=res.content_hash)
    merged = Skill(
        id=skill_id,
        frontmatter=SkillFrontmatter(name=name, description="Merged curated skills.",
                                      tags=["curated"]),
        md_body="\n".join(body_parts),
        scripts=scripts, resources=resources,
        provenance=SkillProvenance(source="curated_bundle",
                                    parents=[sk.id for sk in skills], generation=0),
    )
    merged.refresh_content_hash()
    return merged


# ---------------------------------------------------------------------------
# Evolution lineage extractor
# ---------------------------------------------------------------------------

def extract_lineage(result: EvolutionRunResult) -> dict:
    """Extract human-readable evolution lineage from the run result."""
    lineage: dict = {
        "generations": [],
        "crossover_events": [],
        "mutation_events": [],
    }
    for gen_record in result.generations:
        gen_info: dict = {
            "generation": gen_record.generation,
            "population": [
                {"skill_id": c.skill.id, "pass_rate": c.evaluation.pass_rate,
                 "op": c.skill.provenance.source}
                for c in gen_record.population
            ],
            "mutants": [],
            "offspring": [],
        }
        for m in gen_record.mutants:
            parents = m.skill.provenance.parents
            event = {
                "skill_id": m.skill.id,
                "parent": parents[0] if parents else "unknown",
                "pass_rate": m.evaluation.pass_rate,
                "generation": gen_record.generation,
            }
            gen_info["mutants"].append(event)
            lineage["mutation_events"].append(event)

        for o in gen_record.offspring:
            parents = o.skill.provenance.parents
            event = {
                "skill_id": o.skill.id,
                "parent_a": parents[0] if len(parents) > 0 else "unknown",
                "parent_b": parents[1] if len(parents) > 1 else "unknown",
                "pass_rate": o.evaluation.pass_rate,
                "generation": gen_record.generation,
            }
            gen_info["offspring"].append(event)
            lineage["crossover_events"].append(event)

        lineage["generations"].append(gen_info)
    return lineage


def build_narrative(
    p0_rows: list[dict],
    curated_row: dict,
    no_skill_row: dict,
    p0_best_row: dict,
    apo_full_row: dict,
    lineage: dict,
    settings_info: dict,
) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("APO-SkillsMD 实验结果报告")
    lines.append(f"任务: parallel-tfidf-search  模型: {settings_info['model']}")
    lines.append("=" * 60)

    lines.append("\n【基线结果】")
    lines.append(f"  No-Skill (无技能裸跑):    通过率 {no_skill_row['pass_rate']:.0%}  "
                 f"(平均 {no_skill_row['n_trials']} 次 trial)")
    lines.append(f"  Curated-Skills (官方精选): 通过率 {curated_row['pass_rate']:.0%}  "
                 f"(平均 {curated_row['n_trials']} 次 trial)")

    lines.append("\n【P0 初始冗余池（进化前，各跑 1 次）】")
    for row in p0_rows:
        lines.append(f"  {row['skill_id']:<45} 通过率 {row['pass_rate']:.0%}")
    lines.append(f"  → P0-Best: {p0_best_row['skill_id']}  通过率 {p0_best_row['pass_rate']:.0%}")

    lines.append("\n【APO-Full 进化过程】")
    total_mutations = len(lineage["mutation_events"])
    total_crossovers = len(lineage["crossover_events"])
    n_gens = len([g for g in lineage["generations"] if g["generation"] > 0])
    lines.append(f"  进化代数: {n_gens} 代")
    lines.append(f"  Mutation 次数: {total_mutations}")
    lines.append(f"  Crossover 次数: {total_crossovers}")

    for event in lineage["mutation_events"]:
        lines.append(f"  • [Mutation  Gen{event['generation']}] "
                     f"{event['parent']} → {event['skill_id']}  "
                     f"通过率 {event['pass_rate']:.0%}")

    for event in lineage["crossover_events"]:
        lines.append(f"  • [Crossover Gen{event['generation']}] "
                     f"{event['parent_a']} ✕ {event['parent_b']} → {event['skill_id']}  "
                     f"通过率 {event['pass_rate']:.0%}")

    lines.append("\n【最终结果对比（报告期 3 次 trial 平均）】")
    rows_cmp = [
        ("No-Skill",       no_skill_row["pass_rate"]),
        ("Curated-Skills", curated_row["pass_rate"]),
        ("P0-Best",        p0_best_row["pass_rate"]),
        ("APO-Full",       apo_full_row["pass_rate"]),
    ]
    for name, pr in rows_cmp:
        marker = " ★" if name == "APO-Full" else ""
        lines.append(f"  {name:<18} {pr:.0%}{marker}")

    lines.append("\n【进化增益】")
    gain = apo_full_row["pass_rate"] - p0_best_row["pass_rate"]
    lines.append(f"  APO-Full vs P0-Best:        {gain:+.0%}")
    gain2 = apo_full_row["pass_rate"] - no_skill_row["pass_rate"]
    lines.append(f"  APO-Full vs No-Skill:       {gain2:+.0%}")

    lines.append(f"\n【搜索成本】  APO-Full tokens (search): {settings_info.get('search_tokens', 'N/A')}")
    lines.append("=" * 60)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--out", default="results/parallel_tfidf_pilot")
    parser.add_argument("--report-trials", type=int, default=3)
    parser.add_argument("--generations", type=int, default=2)
    parser.add_argument("--max-steps", type=int, default=20)
    args = parser.parse_args()

    out_dir = (REPO_ROOT / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    task_env_dir = TASK_DIR / "environment"
    curated_dir = task_env_dir / "skills"
    pool_root = REPO_ROOT / "data/skill_pool"

    settings = load_settings(args.config)
    settings.llm.use_cache = False
    settings.evolution.population_size = 4
    settings.evolution.generations = args.generations
    settings.sandbox.max_steps = args.max_steps
    settings.sandbox.command_timeout_sec = 180

    from apo_skillsmd.llm.factory import build_llm
    llm = build_llm(settings)
    loop = AgentLoop(llm, max_steps=settings.sandbox.max_steps,
                     command_timeout_sec=settings.sandbox.command_timeout_sec,
                     sandbox_profile=settings.sandbox.profile,
                     llm_temperature=settings.llm.temperature,
                     llm_max_tokens=settings.llm.max_tokens)
    evaluator = TFIDFEvaluator(loop, task_environment_dir=task_env_dir,
                               sandbox_profile=settings.sandbox.profile)
    task = build_task_spec()

    N = args.report_trials
    print(f"\n[pilot] task={TASK_ID}  model={settings.llm.model}  "
          f"report_trials={N}  generations={args.generations}  max_steps={args.max_steps}", flush=True)

    # --- Load skills ---
    no_skill = build_no_skill()
    curated_skills = load_curated_skills(curated_dir)
    curated_bundle = merge_skills(curated_skills, skill_id="curated-tfidf-bundle",
                                   name="Curated TF-IDF Bundle")
    p0_skills = load_p0_skills(pool_root)
    print(f"[pilot] P0: {[s.id for s in p0_skills]}", flush=True)
    print(f"[pilot] Curated: {[s.id for s in curated_skills]}", flush=True)

    # --- P0 evaluation (1 trial each, for initial pass rates) ---
    print("\n[pilot] === P0 初始评估（每个 1 次 trial）===", flush=True)
    p0_rows = [evaluate_n_trials(evaluator, sk, task, 1, "p0_candidate") for sk in p0_skills]
    p0_best = max(p0_rows, key=lambda r: (r["pass_rate"], -r["avg_tokens"]))
    p0_best_skill = next(s for s in p0_skills if s.id == p0_best["skill_id"])

    # --- APO-Full evolution ---
    print("\n[pilot] === APO-Full 进化阶段 ===", flush=True)
    driver = EvolutionDriver(
        evaluator, SafetyFilter(),
        population_size=settings.evolution.population_size,
        generations=settings.evolution.generations,
        mutation_meta_skill_dir=settings.paths.mutation_meta_skill_dir,
        mutation_workspace_root=settings.sandbox.workspace_root,
    )
    evo_out = out_dir / "evolution"
    evo_result = driver.run(task, p0_skills, output_dir=evo_out)
    lineage = extract_lineage(evo_result)
    apo_best_candidate = max(evo_result.final_population,
                              key=lambda c: (c.evaluation.pass_rate, -c.evaluation.execution_tokens))
    apo_best_skill = apo_best_candidate.skill
    search_tokens = sum(
        c.evaluation.execution_tokens
        for gen in evo_result.generations
        for c in (gen.population + gen.mutants + gen.offspring)
    )
    print(f"[pilot] 进化完成: best={apo_best_skill.id}  "
          f"search_pass_rate={apo_best_candidate.evaluation.pass_rate:.0%}  "
          f"search_tokens={search_tokens}", flush=True)

    # --- Report period: N trials each ---
    print(f"\n[pilot] === 报告期（每个条件 {N} 次 trial）===", flush=True)
    no_skill_row = evaluate_n_trials(evaluator, no_skill, task, N, "no_skill")
    curated_row = evaluate_n_trials(evaluator, curated_bundle, task, N, "curated_skills")
    p0_best_report = evaluate_n_trials(evaluator, p0_best_skill, task, N, "p0_best")
    apo_full_row = evaluate_n_trials(evaluator, apo_best_skill, task, N, "apo_full")

    # --- Save CSVs ---
    all_rows = [no_skill_row, curated_row, p0_best_report, apo_full_row] + p0_rows
    csv_path = out_dir / "baseline_report.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["condition","skill_id","pass_rate","n_trials","avg_tokens","notes"])
        writer.writeheader()
        for row in all_rows:
            writer.writerow({k: row[k] for k in writer.fieldnames})

    # --- Narrative report ---
    settings_info = {
        "model": settings.llm.model,
        "max_steps": settings.sandbox.max_steps,
        "search_tokens": search_tokens,
    }
    narrative = build_narrative(
        p0_rows, curated_row, no_skill_row, p0_best_report, apo_full_row,
        lineage, settings_info
    )
    print("\n" + narrative)
    (out_dir / "narrative_report.txt").write_text(narrative, encoding="utf-8")

    summary = {
        "task_id": TASK_ID,
        "model": settings.llm.model,
        "report_trials": N,
        "generations": args.generations,
        "p0_skills": [s.id for s in p0_skills],
        "curated_skills": [s.id for s in curated_skills],
        "p0_initial_pass_rates": {r["skill_id"]: r["pass_rate"] for r in p0_rows},
        "p0_best_skill": p0_best_skill.id,
        "apo_full_best_skill": apo_best_skill.id,
        "results": {
            "no_skill": no_skill_row["pass_rate"],
            "curated_skills": curated_row["pass_rate"],
            "p0_best": p0_best_report["pass_rate"],
            "apo_full": apo_full_row["pass_rate"],
        },
        "evolution_lineage": lineage,
        "search_tokens": search_tokens,
    }
    (out_dir / "run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[pilot] 结果已写入 {out_dir}", flush=True)


if __name__ == "__main__":
    main()
