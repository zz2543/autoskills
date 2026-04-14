"""CLI entrypoint for experiment execution."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from apo_skillsmd.agent.loop import AgentLoop
from apo_skillsmd.bench.pool_sources import iter_skill_dirs
from apo_skillsmd.bench.skillsbench import SkillsBenchEvaluator
from apo_skillsmd.config import load_settings
from apo_skillsmd.experiments.base import ExperimentRunner
from apo_skillsmd.experiments.exp1_main import build_runner as build_main_runner
from apo_skillsmd.experiments.exp2_ablation import build_runner as build_ablation_runner
from apo_skillsmd.experiments.exp3_init import build_runner as build_init_runner
from apo_skillsmd.experiments.exp4_qualitative import build_runner as build_qual_runner
from apo_skillsmd.llm.factory import build_llm
from apo_skillsmd.types import TaskSpec


def resolve_task_paths(base_dir: Path, task_id: str | None, task_path: str | None) -> list[Path]:
    if task_path:
        return [Path(task_path)]
    if task_id is None:
        return sorted(base_dir.rglob("*.json"))
    normalized = task_id.replace("/", "_")
    for path in base_dir.rglob("*.json"):
        if path.stem == normalized or normalized in path.as_posix():
            return [path]
    raise FileNotFoundError(f"Unable to resolve task_id: {task_id}")


def select_runner(name: str, settings) -> ExperimentRunner:
    if name == "exp2_ablation":
        return build_ablation_runner(settings)
    if name == "exp3_init":
        return build_init_runner(settings)
    if name == "exp4_qualitative":
        return build_qual_runner(settings)
    return build_main_runner(settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run APO-SkillsMD experiments.")
    parser.add_argument("--config", required=True, help="Path to the YAML config file.")
    parser.add_argument("--task-id", help="Optional task identifier.")
    parser.add_argument("--task-path", help="Optional explicit task file path.")
    parser.add_argument("--out", help="Override output directory.")
    parser.add_argument("--population-size", type=int, help="Override initial population size.")
    parser.add_argument("--generations", type=int, help="Override generation count.")
    parser.add_argument(
        "--experiment",
        choices=["exp1_main", "exp2_ablation", "exp3_init", "exp4_qualitative"],
        help="Explicit experiment runner to use.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = load_settings(args.config)
    if args.out:
        settings.experiments.default_output_dir = args.out
    if args.population_size:
        settings.evolution.population_size = args.population_size
    if args.generations:
        settings.evolution.generations = args.generations

    task_paths = resolve_task_paths(
        Path(settings.paths.skillsbench_dir),
        task_id=args.task_id,
        task_path=args.task_path,
    )
    llm = build_llm(settings)
    loop = AgentLoop(
        llm,
        max_steps=settings.sandbox.max_steps,
        command_timeout_sec=settings.sandbox.command_timeout_sec,
        sandbox_profile=settings.sandbox.profile,
    )
    evaluator = SkillsBenchEvaluator(loop, sandbox_profile=settings.sandbox.profile)
    runner = select_runner(args.experiment or settings.experiment_name, settings)
    tasks = runner.load_task_specs(task_paths)
    market_skills = runner.load_skill_pool(iter_skill_dirs(settings.paths.pool_dir))
    runner.run(tasks=tasks, market_skills=market_skills, evaluator=evaluator)


if __name__ == "__main__":
    main()
