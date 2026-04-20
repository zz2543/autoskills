"""Main evolution driver."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from apo_skillsmd.bench.skillsbench import EvaluationResult, SkillsBenchEvaluator
from apo_skillsmd.evolution.crossover import crossover
from apo_skillsmd.evolution.escape import inject_escape_skills, stagnant_for_k_generations
from apo_skillsmd.evolution.mutation_agent import MutationAgentRunner
from apo_skillsmd.evolution.mutation import lineage_guided_mutation, trace_guided_mutation
from apo_skillsmd.evolution.pareto import ParetoCandidate, current_pareto_front, nsga2_select
from apo_skillsmd.safety.filter import SafetyFilter
from apo_skillsmd.skill.model import Skill
from apo_skillsmd.types import SkillEvaluation, TaskSpec


class EvolutionAblation(BaseModel):
    """Feature flags for controlled ablations."""

    use_trace: bool = True
    use_crossover: bool = True
    use_pareto: bool = True
    use_escape: bool = True


class EvolutionGenerationRecord(BaseModel):
    """Serializable snapshot for one generation."""

    generation: int
    population: list[ParetoCandidate] = Field(default_factory=list)
    mutants: list[ParetoCandidate] = Field(default_factory=list)
    offspring: list[ParetoCandidate] = Field(default_factory=list)
    selected: list[ParetoCandidate] = Field(default_factory=list)


class EvolutionRunResult(BaseModel):
    """Final outputs from one evolution run."""

    task_id: str
    generations: list[EvolutionGenerationRecord] = Field(default_factory=list)
    final_population: list[ParetoCandidate] = Field(default_factory=list)
    best_skill_id: str | None = None
    best_pass_rate: float = 0.0
    final_pareto_front: list[ParetoCandidate] = Field(default_factory=list)


class EvolutionDriver:
    """Orchestrate initialization, evaluation, variation, and selection."""

    def __init__(
        self,
        evaluator: SkillsBenchEvaluator,
        safety_filter: SafetyFilter,
        *,
        population_size: int,
        generations: int,
        ablation: EvolutionAblation | None = None,
        mutation_meta_skill_dir: str | Path = "meta_skills/skill_mutator",
        mutation_workspace_root: str | Path | None = None,
    ) -> None:
        self.evaluator = evaluator
        self.safety_filter = safety_filter
        self.population_size = population_size
        self.generations = generations
        self.ablation = ablation or EvolutionAblation()
        self.mutation_runner = MutationAgentRunner(
            self.evaluator.agent_loop.llm,
            meta_skill_dir=mutation_meta_skill_dir,
            max_steps=self.evaluator.agent_loop.max_steps,
            command_timeout_sec=self.evaluator.agent_loop.command_timeout_sec,
            sandbox_profile=self.evaluator.sandbox_profile,
            workspace_root=mutation_workspace_root,
            llm_temperature=self.evaluator.agent_loop.llm_temperature,
            llm_max_tokens=self.evaluator.agent_loop.llm_max_tokens,
        )

    def _evaluate(self, skill: Skill, task: TaskSpec) -> tuple[ParetoCandidate, EvaluationResult]:
        result = self.evaluator.evaluate(skill, task)
        trace = result.case_results[0].agent_result.trace if result.case_results else None
        candidate = ParetoCandidate(
            skill=skill,
            evaluation=result.as_skill_evaluation(),
            trace=trace,
        )
        return candidate, result

    def _pair_front(self, front: list[ParetoCandidate]) -> list[tuple[ParetoCandidate, ParetoCandidate]]:
        if len(front) < 2:
            return []
        ordered = sorted(
            front,
            key=lambda candidate: (candidate.evaluation.pass_rate, -candidate.evaluation.execution_tokens),
        )
        pairs: list[tuple[ParetoCandidate, ParetoCandidate]] = []
        left = 0
        right = len(ordered) - 1
        while left < right:
            pairs.append((ordered[left], ordered[right]))
            left += 1
            right -= 1
        return pairs

    def _greedy_select(self, candidates: list[ParetoCandidate]) -> list[ParetoCandidate]:
        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.evaluation.pass_rate,
                -candidate.evaluation.execution_tokens,
            ),
            reverse=True,
        )[: self.population_size]

    def _serialize_candidate(self, candidate: ParetoCandidate) -> dict:
        payload = {
            "skill_id": candidate.skill.id,
            "pass_rate": candidate.evaluation.pass_rate,
            "execution_tokens": candidate.evaluation.execution_tokens,
            "success": candidate.evaluation.success,
            "rank": candidate.rank,
            "crowding": candidate.crowding,
            "provenance": candidate.skill.provenance.model_dump(),
            "trace_modules": [event.module for event in candidate.trace.module_events] if candidate.trace else [],
        }
        return payload

    def _write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _persist_generation(
        self,
        output_dir: Path | None,
        *,
        generation: int,
        population: list[ParetoCandidate],
        mutants: list[ParetoCandidate],
        offspring: list[ParetoCandidate],
        selected: list[ParetoCandidate],
    ) -> None:
        if output_dir is None:
            return
        generation_dir = output_dir / f"generation_{generation}"
        self._write_jsonl(generation_dir / "population.jsonl", [self._serialize_candidate(item) for item in population])
        self._write_jsonl(generation_dir / "mutants.jsonl", [self._serialize_candidate(item) for item in mutants])
        self._write_jsonl(generation_dir / "offspring.jsonl", [self._serialize_candidate(item) for item in offspring])
        self._write_jsonl(generation_dir / "selected.jsonl", [self._serialize_candidate(item) for item in selected])
        self._write_jsonl(generation_dir / "evaluations.jsonl", [self._serialize_candidate(item) for item in selected])

    def run(
        self,
        task: TaskSpec,
        initial_population: list[Skill],
        *,
        output_dir: str | Path | None = None,
    ) -> EvolutionRunResult:
        """Run the full evolution loop for one task."""

        if not initial_population:
            raise ValueError("Initial population must not be empty.")

        out_path = Path(output_dir) if output_dir is not None else None
        population: list[ParetoCandidate] = []
        records: list[EvolutionGenerationRecord] = []
        best_history: list[float] = []
        safety_rejects: list[dict] = []

        for skill in initial_population[: self.population_size]:
            candidate, _ = self._evaluate(skill, task)
            population.append(candidate)

        records.append(EvolutionGenerationRecord(generation=0, population=population, selected=population))
        self._persist_generation(out_path, generation=0, population=population, mutants=[], offspring=[], selected=population)
        best_history.append(max(candidate.evaluation.pass_rate for candidate in population))

        for generation in range(1, self.generations + 1):
            mutants: list[ParetoCandidate] = []
            offspring: list[ParetoCandidate] = []

            for candidate in population:
                if self.ablation.use_trace and candidate.trace is not None:
                    mutated = trace_guided_mutation(
                        candidate.skill,
                        candidate.trace,
                        generation=generation,
                        mutation_runner=self.mutation_runner,
                    )
                else:
                    mutated = lineage_guided_mutation(candidate.skill, generation=generation)
                verdict = self.safety_filter.scan(mutated)
                if not verdict.allowed:
                    safety_rejects.append(
                        {"generation": generation, "skill_id": mutated.id, "findings": [finding.model_dump() for finding in verdict.findings]}
                    )
                    continue
                mutated_candidate, _ = self._evaluate(mutated, task)
                mutants.append(mutated_candidate)

            if self.ablation.use_crossover:
                front = current_pareto_front(population) if self.ablation.use_pareto else population[:]
                _crossover_llm = getattr(self.evaluator.agent_loop, "llm", None)
                for left, right in self._pair_front(front):
                    if left.trace is None or right.trace is None:
                        continue
                    child = crossover(
                        left.skill,
                        right.skill,
                        left.trace,
                        right.trace,
                        generation=generation,
                        llm=_crossover_llm,
                    )
                    if child is None:
                        continue
                    verdict = self.safety_filter.scan(child)
                    if not verdict.allowed:
                        safety_rejects.append(
                            {"generation": generation, "skill_id": child.id, "findings": [finding.model_dump() for finding in verdict.findings]}
                        )
                        continue
                    child_candidate, _ = self._evaluate(child, task)
                    offspring.append(child_candidate)

            if self.ablation.use_escape and stagnant_for_k_generations(best_history, window=3):
                for skill in inject_escape_skills(task, count=2, generation=generation):
                    injected_candidate, _ = self._evaluate(skill, task)
                    offspring.append(injected_candidate)

            candidate_pool = population + mutants + offspring
            if self.ablation.use_pareto:
                selected = nsga2_select(candidate_pool, size=self.population_size)
            else:
                selected = self._greedy_select(candidate_pool)

            population = selected
            best_history.append(max(candidate.evaluation.pass_rate for candidate in population))
            records.append(
                EvolutionGenerationRecord(
                    generation=generation,
                    population=population,
                    mutants=mutants,
                    offspring=offspring,
                    selected=selected,
                )
            )
            self._persist_generation(
                out_path,
                generation=generation,
                population=population,
                mutants=mutants,
                offspring=offspring,
                selected=selected,
            )

        final_front = current_pareto_front(population) if population else []
        best_candidate = max(population, key=lambda candidate: candidate.evaluation.pass_rate)
        result = EvolutionRunResult(
            task_id=task.task_id,
            generations=records,
            final_population=population,
            best_skill_id=best_candidate.skill.id,
            best_pass_rate=best_candidate.evaluation.pass_rate,
            final_pareto_front=final_front,
        )

        if out_path is not None:
            out_path.mkdir(parents=True, exist_ok=True)
            (out_path / "final_pareto.json").write_text(
                json.dumps([self._serialize_candidate(candidate) for candidate in final_front], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (out_path / "safety_rejects.jsonl").write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in safety_rejects) + ("\n" if safety_rejects else ""),
                encoding="utf-8",
            )
            summary_lines = ["generation,best_pass_rate"]
            for index, value in enumerate(best_history):
                summary_lines.append(f"{index},{value}")
            (out_path / "summary.csv").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")

        return result
