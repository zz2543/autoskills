"""Write skill packages back to disk."""

from __future__ import annotations

from pathlib import Path

import yaml

from apo_skillsmd.skill.model import Skill


def _render_frontmatter(skill: Skill) -> str:
    metadata = skill.frontmatter.model_dump()
    metadata["id"] = skill.id
    metadata["provenance"] = skill.provenance.model_dump()
    header = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{header}\n---\n\n"


def dump_skill(skill: Skill, out_dir: str | Path) -> Path:
    """Persist a skill into a target directory."""

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)

    (root / "SKILL.md").write_text(
        _render_frontmatter(skill) + skill.md_body.rstrip() + "\n",
        encoding="utf-8",
    )

    for relative_path, script in skill.scripts.items():
        file_path = root / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(script.content, encoding="utf-8")
        if script.is_executable:
            file_path.chmod(file_path.stat().st_mode | 0o111)

    for relative_path, resource in skill.resources.items():
        file_path = root / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(resource.content, encoding="utf-8")

    return root
