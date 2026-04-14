"""Diversity injection helpers."""

from __future__ import annotations

from apo_skillsmd.evolution.init_pool import build_synthetic_seed_skill
from apo_skillsmd.skill.model import Skill
from apo_skillsmd.types import TaskSpec


def stagnant_for_k_generations(history: list[float], window: int) -> bool:
    """Whether the best pass rate has not improved within the given window."""

    if len(history) < window + 1:
        return False
    recent = history[-(window + 1) :]
    return max(recent[1:]) <= recent[0]


def inject_escape_skills(task: TaskSpec, *, count: int, generation: int) -> list[Skill]:
    """Create diversity injections used when the population collapses."""

    skills: list[Skill] = []
    for offset in range(count):
        skill = build_synthetic_seed_skill(task, generation * 100 + offset)
        skill.provenance.source = "escape_injection"
        skill.provenance.generation = generation
        skill.provenance.notes.append("Injected to escape stagnation.")
        skill.refresh_content_hash()
        skills.append(skill)
    return skills
