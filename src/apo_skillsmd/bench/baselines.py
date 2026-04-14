"""Load baseline skill packages from local mirrors."""

from __future__ import annotations

from pathlib import Path

from apo_skillsmd.bench.pool_sources import iter_skill_dirs
from apo_skillsmd.skill.loader import load_skill
from apo_skillsmd.skill.model import Skill


def load_baseline_skills(root: str | Path) -> list[Skill]:
    """Load all baseline skills from a local repository mirror."""

    return [load_skill(path) for path in iter_skill_dirs(root)]
