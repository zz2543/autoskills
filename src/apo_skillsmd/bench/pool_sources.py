"""Repository sources for redundant skill pools."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel


class PoolSource(BaseModel):
    """One external repository contributing skills to the initial population."""

    name: str
    url: str
    local_dir: str
    skill_glob: str = "**/SKILL.md"


DEFAULT_POOL_SOURCES: list[PoolSource] = [
    PoolSource(
        name="antigravity-awesome-skills",
        url="https://github.com/sickn33/antigravity-awesome-skills",
        local_dir="antigravity-awesome-skills",
    ),
    PoolSource(
        name="skillsmp",
        url="https://github.com/Skills-Marketplace/SkillsMP",
        local_dir="SkillsMP",
    ),
]


def iter_skill_dirs(root: str | Path, skill_glob: str = "**/SKILL.md") -> list[Path]:
    """Return directories that contain skill definitions."""

    return sorted({path.parent for path in Path(root).glob(skill_glob)})
