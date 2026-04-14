"""Core data models for mixed-format skills."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


def _hash_text(content: str) -> str:
    return sha256(content.encode("utf-8")).hexdigest()


class SkillFrontmatter(BaseModel):
    """Structured metadata parsed from the frontmatter block in `SKILL.md`."""

    name: str = "Unnamed Skill"
    description: str = ""
    version: str = "0.1.0"
    tags: list[str] = Field(default_factory=list)
    category: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScriptFile(BaseModel):
    """A script file that belongs to a skill package."""

    relative_path: str
    content: str
    language: str = "python"
    is_executable: bool = False
    content_hash: str = ""

    @classmethod
    def from_path(cls, path: Path, root: Path) -> "ScriptFile":
        """Build a script model from a file on disk."""

        content = path.read_text(encoding="utf-8")
        return cls(
            relative_path=path.relative_to(root).as_posix(),
            content=content,
            language=path.suffix.lstrip(".") or "text",
            is_executable=path.stat().st_mode & 0o111 > 0,
            content_hash=_hash_text(content),
        )


class SkillProvenance(BaseModel):
    """Lineage information tracked across mutation and crossover."""

    source: str = "unknown"
    parents: list[str] = Field(default_factory=list)
    generation: int = 0
    notes: list[str] = Field(default_factory=list)


class SkillResource(BaseModel):
    """Non-script files packaged with the skill."""

    relative_path: str
    content: str
    content_hash: str


class Skill(BaseModel):
    """A full skill package containing markdown, code, and resource files."""

    id: str
    path: str | None = None
    frontmatter: SkillFrontmatter = Field(default_factory=SkillFrontmatter)
    md_body: str = ""
    scripts: dict[str, ScriptFile] = Field(default_factory=dict)
    resources: dict[str, SkillResource] = Field(default_factory=dict)
    content_hash: str = ""
    provenance: SkillProvenance = Field(default_factory=SkillProvenance)

    def refresh_content_hash(self) -> str:
        """Recompute the overall content hash after any mutation."""

        digest = sha256()
        digest.update(self.md_body.encode("utf-8"))
        digest.update(repr(self.frontmatter.model_dump()).encode("utf-8"))
        for key in sorted(self.scripts):
            digest.update(key.encode("utf-8"))
            digest.update(self.scripts[key].content_hash.encode("utf-8"))
        for key in sorted(self.resources):
            digest.update(key.encode("utf-8"))
            digest.update(self.resources[key].content_hash.encode("utf-8"))
        self.content_hash = digest.hexdigest()
        return self.content_hash

    def clone(self, *, new_id: str | None = None) -> "Skill":
        """Create a detached copy used by mutation and crossover operators."""

        cloned = self.model_copy(deep=True)
        if new_id is not None:
            cloned.id = new_id
        cloned.refresh_content_hash()
        return cloned
