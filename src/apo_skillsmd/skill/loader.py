"""Load a skill package from disk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from apo_skillsmd.skill.model import Skill, SkillFrontmatter, SkillProvenance, SkillResource, ScriptFile


def _split_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter from markdown.

    The loader avoids a hard runtime dependency on `python-frontmatter` so the
    repository can still be inspected in constrained environments.
    """

    if not content.startswith("---\n"):
        return {}, content

    _, remainder = content.split("---\n", 1)
    header, body = remainder.split("\n---\n", 1)
    metadata = yaml.safe_load(header) or {}
    if not isinstance(metadata, dict):
        raise ValueError("Frontmatter must be a mapping.")
    return metadata, body.lstrip("\n")


def _load_resources(root: Path) -> dict[str, SkillResource]:
    resources: dict[str, SkillResource] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if "__pycache__" in path.parts:
            continue
        if relative == "SKILL.md" or relative.startswith("scripts/"):
            continue
        content = path.read_text(encoding="utf-8")
        resources[relative] = SkillResource(
            relative_path=relative,
            content=content,
            content_hash=ScriptFile.from_path(path, root).content_hash,
        )
    return resources


def load_skill(path: str | Path) -> Skill:
    """Load a skill from either a directory or a direct `SKILL.md` path."""

    input_path = Path(path)
    root = input_path if input_path.is_dir() else input_path.parent
    skill_md = root / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"Missing SKILL.md under {root}")

    metadata, md_body = _split_frontmatter(skill_md.read_text(encoding="utf-8"))
    skill_id = metadata.get("id") or root.name
    provenance_dict = metadata.pop("provenance", {}) if isinstance(metadata, dict) else {}
    frontmatter = SkillFrontmatter.model_validate(metadata)
    scripts_root = root / "scripts"
    scripts: dict[str, ScriptFile] = {}
    if scripts_root.exists():
        for script_path in scripts_root.rglob("*"):
            if "__pycache__" in script_path.parts:
                continue
            if script_path.is_file() and script_path.suffix in {".py", ".sh", ".txt", ".json", ".yaml", ".yml"}:
                script = ScriptFile.from_path(script_path, root)
                scripts[script.relative_path] = script

    skill = Skill(
        id=skill_id,
        path=str(root.resolve()),
        frontmatter=frontmatter,
        md_body=md_body,
        scripts=scripts,
        resources=_load_resources(root),
        provenance=SkillProvenance.model_validate(provenance_dict or {}),
    )
    skill.refresh_content_hash()
    return skill
