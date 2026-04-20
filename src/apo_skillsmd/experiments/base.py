"""Experiment orchestration and result storage."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, Field

from apo_skillsmd.bench.skillsbench import SkillsBenchEvaluator, load_task_spec
from apo_skillsmd.config import AppSettings
from apo_skillsmd.evolution.init_pool import initialize_redundant_pool
from apo_skillsmd.evolution.loop import EvolutionAblation, EvolutionDriver, EvolutionRunResult
from apo_skillsmd.safety.filter import SafetyFilter
from apo_skillsmd.skill.loader import load_skill
from apo_skillsmd.skill.model import Skill
from apo_skillsmd.types import TaskSpec


class ResultStore:
    """Small helper for writing JSON, JSONL, and CSV outputs."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_json(self, relative_path: str, payload: object) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def write_jsonl(self, relative_path: str, rows: Iterable[dict]) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def write_csv(self, relative_path: str, rows: list[dict]) -> None:
        if not rows:
            return
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)


class ExperimentSummary(BaseModel):
    """High-level experiment summary across tasks."""

    experiment_name: str
    task_count: int
    runs: list[dict] = Field(default_factory=list)


class ExperimentRunner:
    """Run an experiment configuration over one or more tasks."""

    def __init__(self, settings: AppSettings, *, ablation: EvolutionAblation | None = None) -> None:
        self.settings = settings
        self.ablation = ablation or EvolutionAblation()
        self.result_store = ResultStore(settings.experiments.default_output_dir)
        self.safety_filter = SafetyFilter()

    def load_task_specs(self, paths: list[str | Path]) -> list[TaskSpec]:
        return [load_task_spec(path) for path in paths]

    def load_skill_pool(self, skill_dirs: list[str | Path]) -> list[Skill]:
        return [load_skill(path) for path in skill_dirs]

    def build_driver(self, evaluator: SkillsBenchEvaluator) -> EvolutionDriver:
        # When no explicit ablation override is given, derive from config flags.
        ablation = self.ablation if self.ablation is not None else EvolutionAblation(
            use_trace=self.settings.evolution.enable_trace,
            use_crossover=self.settings.evolution.enable_crossover,
            use_pareto=self.settings.evolution.enable_pareto,
            use_escape=self.settings.evolution.enable_escape,
        )
        return EvolutionDriver(
            evaluator,
            self.safety_filter,
            population_size=self.settings.evolution.population_size,
            generations=self.settings.evolution.generations,
            ablation=ablation,
            mutation_meta_skill_dir=self.settings.paths.mutation_meta_skill_dir,
            mutation_workspace_root=self.settings.sandbox.workspace_root,
        )

    def run(
        self,
        *,
        tasks: list[TaskSpec],
        market_skills: list[Skill],
        evaluator: SkillsBenchEvaluator,
    ) -> ExperimentSummary:
        driver = self.build_driver(evaluator)
        runs: list[dict] = []

        for task in tasks:
            initial_population = initialize_redundant_pool(
                task,
                market_skills,
                safety_filter=self.safety_filter,
                top_k=self.settings.evolution.retrieval_top_k,
                target_size=self.settings.evolution.population_size,
                max_generated_ratio=self.settings.evolution.max_llm_generated_ratio,
                llm=evaluator.agent_loop.llm,
            )
            task_dir = Path(self.settings.experiments.default_output_dir) / task.task_id.replace("/", "_")
            result = driver.run(task, initial_population, output_dir=task_dir)
            runs.append(
                {
                    "task_id": task.task_id,
                    "best_skill_id": result.best_skill_id,
                    "best_pass_rate": result.best_pass_rate,
                    "pareto_size": len(result.final_pareto_front),
                }
            )

        summary = ExperimentSummary(
            experiment_name=self.settings.experiment_name,
            task_count=len(tasks),
            runs=runs,
        )
        self.result_store.write_json("experiment_summary.json", summary.model_dump())
        self.result_store.write_csv("experiment_summary.csv", runs)
        return summary
