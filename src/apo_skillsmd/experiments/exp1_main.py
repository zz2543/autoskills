"""Experiment 1: overall performance comparison runner."""

from __future__ import annotations

from apo_skillsmd.config import AppSettings
from apo_skillsmd.experiments.base import ExperimentRunner


def build_runner(settings: AppSettings) -> ExperimentRunner:
    return ExperimentRunner(settings)
