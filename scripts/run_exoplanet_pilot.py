"""Complete APO-SkillsMD pilot for SkillsBench exoplanet-detection-period.

Flow:
  P0 pool (天文相关但不含 transit 检测算法)
  → APO-Full 进化 (mutation + crossover, 2 代)
  → 报告期 3 次 trial 平均
  → 叙述型进化报告
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
from apo_skillsmd.skill.model import (
    Skill, SkillFrontmatter, SkillProvenance, ScriptFile, SkillResource,
)
from apo_skillsmd.skill.serializer import dump_skill
from apo_skillsmd.types import SandboxProfileName, TaskSpec, TaskTestCase, VerifierSpec

TASK_ID = "skillsbench/exoplanet-detection-period"
IMAGE_NAME = "apo-skillsmd/exoplanet-detection-period:local"
REPO_ROOT = Path(__file__).resolve().parent.parent
TASK_DIR = REPO_ROOT / "data/skillsbench/tasks/exoplanet-detection-period"


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------

class ExoplanetSandbox(Sandbox):
    def __init__(self, *, profile: SandboxProfileName = SandboxProfileName.OFFLINE_LOCAL,
                 max_output_chars: int = 8000) -> None:
        super().__init__(profile)
        self.max_output_chars = max_output_chars
        self._workspace: Path | None = None

    def setup(self, *, skill: Skill | None = None) -> None:
        ws = Path(tempfile.mkdtemp(prefix="apo_exo_"))
        self._workspace = ws
        # Copy task data files from Docker image to host workspace
        subprocess.run(
            ["docker", "run", "--rm",
             "-v", f"{ws}:/out",
             IMAGE_NAME,
             "/bin/sh", "-c", "cp -r /root/. /out/ 2>/dev/null || true"],
            capture_output=True, timeout=30,
        )
        if skill is not None:
            dump_skill(skill, ws)

    def teardown(self) -> None:
        if self._workspace:
            shutil.rmtree(self._workspace, ignore_errors=True)
            self._workspace = None

    def workspace_root(self) -> Path:
        if not self._workspace:
            raise RuntimeError("Sandbox not set up")
        return self._workspace

    def _resolve(self, path: str) -> Path:
        root = self.workspace_root().resolve()
        candidate = (root / path).resolve()
        if not str(candidate).startswith(str(root)):
            raise ValueError(f"Path escapes sandbox: {path}")
        return candidate

    def _snapshot(self) -> dict[str, str]:
        root = self.workspace_root()
        out: dict[str, str] = {}
        for p in root.rglob("*"):
            if p.is_file():
                out[p.relative_to(root).as_posix()] = sha256(p.read_bytes()).hexdigest()
        return out

    def run_bash(self, command: str, timeout_sec: int) -> CommandResult:
        before = self._snapshot()
        start = time.monotonic()
        docker_cmd = [
            "docker", "run", "--rm", "--network", "none",
            "--cpus", "2", "--memory", "4g",
            "-v", f"{self.workspace_root()}:/root",
            "-w", "/root",
            IMAGE_NAME, "/bin/sh", "-lc", command,
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
                            timeout_sec: int = 180) -> tuple[bool, list[str]]:
    logs_dir = workspace / "_verifier_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{workspace}:/root:ro",
        "-v", f"{tests_dir}:/tests:ro",
        "-v", f"{logs_dir}:/logs",
        IMAGE_NAME,
        "/bin/sh", "-lc",
        (
            "pip3 install --quiet pytest 2>/dev/null; "
            "cd /root && pytest /tests/test_outputs.py -v "
            ">/logs/stdout.txt 2>/logs/stderr.txt; "
            "echo $? > /logs/reward.txt"
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
                    if any(kw in line for kw in ("FAILED", "PASSED", "assert", "Error", "error", "not found")):
                        notes.append(line.strip())
        if not notes and not reward_file.exists():
            notes.append("verifier did not complete")
    return passed, notes


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class ExoplanetEvaluator(SkillsBenchEvaluator):
    def __init__(self, agent_loop: AgentLoop, *,
                 sandbox_profile: SandboxProfileName = SandboxProfileName.OFFLINE_LOCAL) -> None:
        super().__init__(agent_loop, sandbox_profile=sandbox_profile)
        self._tests_dir = TASK_DIR / "tests"

    def evaluate(self, skill: Skill, task: TaskSpec) -> EvaluationResult:
        sandbox = ExoplanetSandbox(profile=self.sandbox_profile)
        result = self.agent_loop.run(task, skill, sandbox=sandbox)
        passed, notes = _run_official_verifier(sandbox.workspace_root(), self._tests_dir)
        sandbox.teardown()

        from apo_skillsmd.bench.skillsbench import CaseResult
        case = CaseResult(case_id="official-verifier", passed=passed,
                          notes=notes, agent_result=result)
        return EvaluationResult(
            task_id=task.task_id,
            passed_cases=1 if passed else 0, total_cases=1,
            pass_rate=1.0 if passed else 0.0,
            execution_tokens=result.token_usage,
            case_results=[case],
        )


# ---------------------------------------------------------------------------
# Multi-trial evaluator
# ---------------------------------------------------------------------------

def evaluate_n_trials(evaluator: ExoplanetEvaluator, skill: Skill,
                      task: TaskSpec, n: int, label: str) -> dict:
    results = []
    for i in range(n):
        print(f"  [trial {i+1}/{n}] {label}: {skill.id}", flush=True)
        r = evaluator.evaluate(skill, task)
        results.append(r)
        print(f"    → pass={r.pass_rate==1.0}  tokens={r.execution_tokens}", flush=True)
    pass_rate = mean(r.pass_rate for r in results)
    avg_tokens = int(mean(r.execution_tokens for r in results))
    notes = list(dict.fromkeys(
        n for r in results for c in r.case_results for n in c.notes
    ))
    print(f"  ✓ {label}: avg_pass_rate={pass_rate:.2f}", flush=True)
    return {
        "condition": label,
        "skill_id": skill.id,
        "skill_name": skill.frontmatter.name,
        "n_trials": n,
        "pass_rate": pass_rate,
        "trials": [{"passed": r.pass_rate == 1.0, "tokens": r.execution_tokens} for r in results],
        "avg_tokens": avg_tokens,
        "notes": notes[:4],
    }


# ---------------------------------------------------------------------------
# Task spec & skills
# ---------------------------------------------------------------------------

def build_task_spec() -> TaskSpec:
    instruction = (TASK_DIR / "instruction.md").read_text(encoding="utf-8")
    return TaskSpec(
        task_id=TASK_ID, domain="astronomy",
        description=instruction,
        inputs={"data_file": "/root/data/tess_lc.txt", "output_file": "/root/period.txt"},
        verifier=VerifierSpec(kind="file", expected_file="period.txt"),
        test_cases=[TaskTestCase(case_id="official-verifier")],
    )


def build_no_skill() -> Skill:
    body = (
        "## Goal\nSolve the assigned scientific data analysis task.\n\n"
        "## Workflow\n"
        "1. Read the task description carefully.\n"
        "2. Explore available data files.\n"
        "3. Write a Python script to analyze the data and produce the required output.\n"
        "4. Run the script and verify the output file was created.\n"
        "5. Return DONE with a summary.\n"
    )
    script = '"""No-skill baseline."""\ndef main(): return "baseline"\n'
    skill = Skill(
        id="baseline-no-skill",
        frontmatter=SkillFrontmatter(name="No Skill Baseline",
                                      description="Generic instructions only.", tags=["baseline"]),
        md_body=body,
        scripts={"scripts/main.py": ScriptFile(
            relative_path="scripts/main.py", content=script, language="python",
            content_hash=sha256(script.encode()).hexdigest())},
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
    # P0: 天文/科学相关但不含 transit 检测算法的技能
    names = ["astropy", "biopython", "deep-research", "matplotlib"]
    skills = []
    for name in names:
        try:
            skills.append(load_skill(_find_skill(pool_root, name)))
            print(f"  [P0] loaded: {name}", flush=True)
        except FileNotFoundError:
            print(f"  [P0] not found: {name}", flush=True)
    return skills


def merge_skills(skills: list[Skill], *, skill_id: str, name: str) -> Skill:
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
# Lineage extraction & narrative
# ---------------------------------------------------------------------------

def extract_lineage(result: EvolutionRunResult) -> dict:
    lineage: dict = {"generations": [], "crossover_events": [], "mutation_events": []}
    for gen in result.generations:
        ginfo: dict = {
            "generation": gen.generation,
            "population": [{"skill_id": c.skill.id, "pass_rate": c.evaluation.pass_rate,
                             "op": c.skill.provenance.source} for c in gen.population],
            "mutants": [], "offspring": [],
        }
        for m in gen.mutants:
            p = m.skill.provenance.parents
            ev = {"skill_id": m.skill.id, "parent": p[0] if p else "unknown",
                  "pass_rate": m.evaluation.pass_rate, "generation": gen.generation}
            ginfo["mutants"].append(ev)
            lineage["mutation_events"].append(ev)
        for o in gen.offspring:
            p = o.skill.provenance.parents
            ev = {"skill_id": o.skill.id,
                  "parent_a": p[0] if len(p) > 0 else "unknown",
                  "parent_b": p[1] if len(p) > 1 else "unknown",
                  "pass_rate": o.evaluation.pass_rate, "generation": gen.generation}
            ginfo["offspring"].append(ev)
            lineage["crossover_events"].append(ev)
        lineage["generations"].append(ginfo)
    return lineage


def build_narrative(p0_rows: list[dict], curated_row: dict, no_skill_row: dict,
                    p0_best_report: dict, apo_full_row: dict,
                    lineage: dict, info: dict) -> str:
    L = []
    L.append("=" * 65)
    L.append("  APO-SkillsMD 实验结果报告")
    L.append(f"  任务: exoplanet-detection-period  |  模型: {info['model']}")
    L.append(f"  报告期 trial 数: {info['n_trials']}  |  进化代数: {info['generations']}")
    L.append("=" * 65)

    L.append("\n▌ 基线结果（报告期平均）")
    L.append(f"  No-Skill  (无技能裸跑)   : {no_skill_row['pass_rate']:.0%}")
    L.append(f"  Curated-Skills (官方精选): {curated_row['pass_rate']:.0%}")

    L.append("\n▌ P0 初始冗余池（进化前，各 1 次 trial）")
    for row in p0_rows:
        bar = "✓" if row["pass_rate"] > 0 else "✗"
        L.append(f"  {bar} {row['skill_id']:<42}  通过率 {row['pass_rate']:.0%}")
    L.append(f"  → P0-Best: {p0_best_report['skill_id']}  通过率 {p0_best_report['pass_rate']:.0%}（报告期平均）")

    L.append("\n▌ APO-Full 进化过程")
    n_gens = len([g for g in lineage["generations"] if g["generation"] > 0])
    total_mut = len(lineage["mutation_events"])
    total_cross = len(lineage["crossover_events"])
    L.append(f"  进化代数: {n_gens}  |  Mutation 次数: {total_mut}  |  Crossover 次数: {total_cross}")

    for ev in lineage["mutation_events"]:
        L.append(f"  • [Mutation  Gen{ev['generation']}]  "
                 f"{ev['parent']}\n"
                 f"    → {ev['skill_id']}  (搜索期通过率 {ev['pass_rate']:.0%})")

    for ev in lineage["crossover_events"]:
        L.append(f"  • [Crossover Gen{ev['generation']}]  "
                 f"{ev['parent_a']}\n"
                 f"    ✕ {ev['parent_b']}\n"
                 f"    → {ev['skill_id']}  (搜索期通过率 {ev['pass_rate']:.0%})")

    L.append("\n▌ 最终结果对比（报告期平均）")
    for name, pr in [("No-Skill", no_skill_row["pass_rate"]),
                      ("Curated-Skills", curated_row["pass_rate"]),
                      ("P0-Best", p0_best_report["pass_rate"]),
                      ("APO-Full ★", apo_full_row["pass_rate"])]:
        L.append(f"  {name:<22} {pr:.0%}  ({pr*info['n_trials']:.0f}/{info['n_trials']} trials)")

    L.append("\n▌ 进化增益")
    L.append(f"  APO-Full vs P0-Best  : {apo_full_row['pass_rate'] - p0_best_report['pass_rate']:+.0%}")
    L.append(f"  APO-Full vs No-Skill : {apo_full_row['pass_rate'] - no_skill_row['pass_rate']:+.0%}")
    L.append(f"\n  搜索成本 (tokens): {info['search_tokens']:,}")
    L.append("=" * 65)
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--out", default="results/exoplanet_pilot")
    parser.add_argument("--report-trials", type=int, default=3,
                        help="每个报告期条件的 trial 数")
    parser.add_argument("--generations", type=int, default=2)
    parser.add_argument("--max-steps", type=int, default=20)
    args = parser.parse_args()

    out_dir = (REPO_ROOT / args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    pool_root = REPO_ROOT / "data/skill_pool"

    settings = load_settings(args.config)
    settings.llm.use_cache = False
    settings.evolution.population_size = 4
    settings.evolution.generations = args.generations
    settings.sandbox.max_steps = args.max_steps
    settings.sandbox.command_timeout_sec = 180

    from apo_skillsmd.llm.factory import build_llm
    llm = build_llm(settings)
    loop = AgentLoop(llm, max_steps=args.max_steps,
                     command_timeout_sec=settings.sandbox.command_timeout_sec,
                     sandbox_profile=settings.sandbox.profile,
                     llm_temperature=settings.llm.temperature,
                     llm_max_tokens=settings.llm.max_tokens)
    evaluator = ExoplanetEvaluator(loop, sandbox_profile=settings.sandbox.profile)
    task = build_task_spec()
    N = args.report_trials

    print(f"\n[pilot] task={TASK_ID}  model={settings.llm.model}  "
          f"trials={N}  gens={args.generations}  steps={args.max_steps}\n", flush=True)

    no_skill = build_no_skill()
    p0_skills = load_p0_skills(pool_root)
    curated_skills = [load_skill(TASK_DIR / "environment/skills" / d)
                      for d in sorted(p.name for p in
                                      (TASK_DIR / "environment/skills").iterdir()
                                      if p.is_dir())]
    curated_bundle = merge_skills(curated_skills, skill_id="curated-exoplanet-bundle",
                                   name="Curated Exoplanet Bundle")

    print(f"[pilot] P0 skills: {[s.id for s in p0_skills]}", flush=True)
    print(f"[pilot] Curated : {[s.id for s in curated_skills]}", flush=True)

    # P0 初始评估 (1 trial each)
    print("\n[pilot] ── P0 初始评估 ──", flush=True)
    p0_rows = [evaluate_n_trials(evaluator, sk, task, 1, "p0_candidate") for sk in p0_skills]
    p0_best = max(p0_rows, key=lambda r: (r["pass_rate"], -r["avg_tokens"]))
    p0_best_skill = next(s for s in p0_skills if s.id == p0_best["skill_id"])

    # APO-Full 进化
    print("\n[pilot] ── APO-Full 进化 ──", flush=True)
    driver = EvolutionDriver(
        evaluator, SafetyFilter(),
        population_size=settings.evolution.population_size,
        generations=args.generations,
        mutation_meta_skill_dir=settings.paths.mutation_meta_skill_dir,
        mutation_workspace_root=settings.sandbox.workspace_root,
    )
    evo_result = driver.run(task, p0_skills, output_dir=out_dir / "evolution")
    lineage = extract_lineage(evo_result)
    apo_best = max(evo_result.final_population,
                   key=lambda c: (c.evaluation.pass_rate, -c.evaluation.execution_tokens))
    search_tokens = sum(
        c.evaluation.execution_tokens
        for g in evo_result.generations
        for c in (g.population + g.mutants + g.offspring)
    )
    print(f"\n[pilot] 进化完成: best={apo_best.skill.id}  "
          f"search_pass_rate={apo_best.evaluation.pass_rate:.0%}", flush=True)

    # 报告期 (N trials)
    print(f"\n[pilot] ── 报告期 ({N} trials each) ──", flush=True)
    no_skill_row = evaluate_n_trials(evaluator, no_skill, task, N, "no_skill")
    curated_row = evaluate_n_trials(evaluator, curated_bundle, task, N, "curated_skills")
    p0_best_report = evaluate_n_trials(evaluator, p0_best_skill, task, N, "p0_best")
    apo_full_row = evaluate_n_trials(evaluator, apo_best.skill, task, N, "apo_full")

    # 保存结果
    csv_path = out_dir / "baseline_report.csv"
    all_rows = [no_skill_row, curated_row, p0_best_report, apo_full_row] + p0_rows
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["condition","skill_id","pass_rate","n_trials","avg_tokens","notes"])
        writer.writeheader()
        for row in all_rows:
            writer.writerow({k: row.get(k, "") for k in writer.fieldnames})

    info = {"model": settings.llm.model, "n_trials": N,
            "generations": args.generations, "search_tokens": search_tokens}
    narrative = build_narrative(p0_rows, curated_row, no_skill_row,
                                p0_best_report, apo_full_row, lineage, info)
    print("\n" + narrative)
    (out_dir / "narrative_report.txt").write_text(narrative, encoding="utf-8")

    (out_dir / "run_summary.json").write_text(json.dumps({
        "task_id": TASK_ID, "model": settings.llm.model,
        "report_trials": N, "generations": args.generations,
        "p0_skills": [s.id for s in p0_skills],
        "curated_skills": [s.id for s in curated_skills],
        "p0_initial_pass_rates": {r["skill_id"]: r["pass_rate"] for r in p0_rows},
        "p0_best_skill": p0_best_skill.id, "apo_full_best_skill": apo_best.skill.id,
        "results": {"no_skill": no_skill_row["pass_rate"],
                    "curated_skills": curated_row["pass_rate"],
                    "p0_best": p0_best_report["pass_rate"],
                    "apo_full": apo_full_row["pass_rate"]},
        "evolution_lineage": lineage, "search_tokens": search_tokens,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[pilot] 结果写入 {out_dir}", flush=True)


if __name__ == "__main__":
    main()
