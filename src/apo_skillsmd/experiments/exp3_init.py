"""Experiment 3: initialization strategy comparison.

The runner currently reuses the common experiment pipeline. Specific
initialization policies can be injected by swapping the pool builder later.
"""

from __future__ import annotations

from apo_skillsmd.config import AppSettings
from apo_skillsmd.experiments.base import ExperimentRunner


def build_runner(settings: AppSettings) -> ExperimentRunner:
    return ExperimentRunner(settings)
