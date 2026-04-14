"""Validation helpers for the child skill package emitted by the meta-skill."""

from __future__ import annotations

from pathlib import Path


def child_skill_missing_items(skill_dir: str | Path) -> list[str]:
    """Return missing required files or directories for a child skill package."""

    root = Path(skill_dir)
    missing: list[str] = []
    if not (root / "SKILL.md").exists():
        missing.append("SKILL.md")
    scripts_dir = root / "scripts"
    if root.exists() and not scripts_dir.exists():
        missing.append("scripts/")
    return missing


def has_non_portable_import_examples(markdown_text: str) -> bool:
    """Detect package-style import examples that assume importable skill package names."""

    return "from evo_" in markdown_text or ".scripts." in markdown_text
