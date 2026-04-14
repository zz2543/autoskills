"""Integration-style test for the minimal evolution loop."""

from __future__ import annotations

from pathlib import Path

from apo_skillsmd.agent.loop import AgentLoop
from apo_skillsmd.bench.skillsbench import SkillsBenchEvaluator, load_task_spec
from apo_skillsmd.evolution.loop import EvolutionDriver
from apo_skillsmd.safety.filter import SafetyFilter
from apo_skillsmd.skill.loader import load_skill
from tests.test_agent_loop_mock import ScriptedTestLLM


def test_evolution_driver_runs_small_population(tmp_path: Path) -> None:
    root = Path("tests/fixtures")
    skills = [
        load_skill(root / "mock_skill"),
        load_skill(root / "mock_skill_variant"),
    ]
    task = load_task_spec(root / "mock_task.json")
    evaluator = SkillsBenchEvaluator(AgentLoop(ScriptedTestLLM(), max_steps=4))
    driver = EvolutionDriver(
        evaluator,
        SafetyFilter(),
        population_size=2,
        generations=1,
    )

    result = driver.run(task, skills, output_dir=tmp_path)

    assert result.best_skill_id is not None
    assert len(result.final_population) == 2
    assert any(
        candidate.skill.provenance.source == "trace_mutation_agent"
        for record in result.generations[1:]
        for candidate in record.mutants
    )
    assert (tmp_path / "final_pareto.json").exists()
    assert (tmp_path / "summary.csv").exists()
