"""Experiment 2: component ablations."""

from __future__ import annotations

from apo_skillsmd.config import AppSettings
from apo_skillsmd.evolution.loop import EvolutionAblation
from apo_skillsmd.experiments.base import ExperimentRunner


def build_runner(
    settings: AppSettings,
    *,
    use_trace: bool = True,
    use_crossover: bool = True,
    use_pareto: bool = True,
    use_escape: bool = True,
) -> ExperimentRunner:
    return ExperimentRunner(
        settings,
        ablation=EvolutionAblation(
            use_trace=use_trace,
            use_crossover=use_crossover,
            use_pareto=use_pareto,
            use_escape=use_escape,
        ),
    )
