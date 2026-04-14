"""Initial population builders."""

from __future__ import annotations

from hashlib import sha256

from apo_skillsmd.evolution.retrieval import retrieve_skills
from apo_skillsmd.safety.filter import SafetyFilter
from apo_skillsmd.skill.model import ScriptFile, Skill, SkillFrontmatter, SkillProvenance
from apo_skillsmd.types import TaskSpec


def _seed_skill_id(task_id: str, index: int) -> str:
    digest = sha256(f"{task_id}:{index}".encode("utf-8")).hexdigest()[:8]
    return f"synthetic-{task_id.replace('/', '-')}-{digest}"


def build_synthetic_seed_skill(task: TaskSpec, index: int) -> Skill:
    """Create a minimal fallback skill when the redundant pool is too small."""

    body = "\n".join(
        [
            f"# Task-Specific Seed {index}",
            "",
            "## Goal",
            task.description,
            "",
            "## Workflow",
            "1. Inspect the workspace.",
            "2. Create or update the required files.",
            "3. Return DONE with a concise summary.",
        ]
    )
    script_content = (
        '"""Utility entry point for synthetic seed skills."""\n\n'
        "def main() -> str:\n"
        '    return "seed"\n'
    )
    skill = Skill(
        id=_seed_skill_id(task.task_id, index),
        frontmatter=SkillFrontmatter(
            name=f"Synthetic Seed {index}",
            description=f"Fallback seed skill for task {task.task_id}",
            tags=["synthetic", task.domain],
            metadata={"origin": "llm-fallback-placeholder"},
        ),
        md_body=body,
        scripts={
            "scripts/main.py": ScriptFile(
                relative_path="scripts/main.py",
                content=script_content,
                language="python",
                is_executable=False,
            )
        },
        provenance=SkillProvenance(source="synthetic_seed", generation=0),
    )
    skill.scripts["scripts/main.py"].content_hash = sha256(script_content.encode("utf-8")).hexdigest()
    skill.refresh_content_hash()
    return skill


def initialize_redundant_pool(
    task: TaskSpec,
    market_skills: list[Skill],
    *,
    safety_filter: SafetyFilter,
    top_k: int,
    target_size: int,
    max_generated_ratio: float = 0.3,
) -> list[Skill]:
    """Construct the initial population from a redundant market pool."""

    retrieved = retrieve_skills(task, market_skills, top_k=top_k)
    safe_skills = [skill for skill in retrieved if safety_filter.scan(skill).allowed]

    generated_cap = max(1, int(target_size * max_generated_ratio))
    while len(safe_skills) < target_size and len(safe_skills) - len(retrieved) < generated_cap:
        safe_skills.append(build_synthetic_seed_skill(task, len(safe_skills) + 1))

    return safe_skills[:target_size]
