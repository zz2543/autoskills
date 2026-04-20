"""Initial population builders."""

from __future__ import annotations

import json
import re
from hashlib import sha256
from typing import TYPE_CHECKING

from apo_skillsmd.evolution.retrieval import retrieve_skills
from apo_skillsmd.safety.filter import SafetyFilter
from apo_skillsmd.skill.model import ScriptFile, Skill, SkillFrontmatter, SkillProvenance
from apo_skillsmd.types import MessageRole, TaskSpec

if TYPE_CHECKING:
    from apo_skillsmd.llm.base import LLMClient


def _seed_skill_id(task_id: str, index: int) -> str:
    digest = sha256(f"{task_id}:{index}".encode("utf-8")).hexdigest()[:8]
    return f"synthetic-{task_id.replace('/', '-')}-{digest}"


def build_synthetic_seed_skill(task: TaskSpec, index: int) -> Skill:
    """Create a minimal fallback skill when the LLM is unavailable."""

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
            metadata={"origin": "synthetic-seed"},
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


_LLM_GEN_PROMPT_TEMPLATE = """\
You are designing an agent skill for an AI coding assistant.

Task ID: {task_id}
Domain: {domain}
Description: {description}

Generate skill variant #{index} that will guide an AI agent to complete this task.
Return ONLY a JSON object with exactly these fields — no prose before or after:
{{
  "name": "concise skill name (< 8 words)",
  "description": "one sentence: what this skill does",
  "workflow": "numbered markdown steps (e.g. 1. ... 2. ...)",
  "script_content": "valid Python code for scripts/main.py"
}}

Requirements:
- The workflow must be concrete and task-specific.
- The Python script must define at least one helper function.
- Make variant #{index} distinct by using a different approach or strategy from the default.
"""


def llm_generate_skill(task: TaskSpec, index: int, llm: "LLMClient") -> Skill:
    """Use the LLM to generate a meaningful skill for the given task."""

    from apo_skillsmd.llm.base import LLMMessage

    prompt = _LLM_GEN_PROMPT_TEMPLATE.format(
        task_id=task.task_id,
        domain=task.domain,
        description=task.description,
        index=index,
    )
    try:
        response = llm.complete(
            [LLMMessage(role=MessageRole.USER, content=prompt)],
            temperature=0.4,
            max_tokens=1024,
        )
        text = response.message
        json_match = re.search(r"\{[\s\S]*\}", text)
        data: dict = json.loads(json_match.group(0)) if json_match else {}
    except Exception:
        data = {}

    name = str(data.get("name", f"LLM-Generated Skill {index}"))[:80]
    description = str(data.get("description", f"LLM-generated skill for {task.task_id}"))[:200]
    workflow = str(data.get("workflow", "1. Analyse workspace\n2. Produce required outputs\n3. Return DONE"))
    script_content = str(
        data.get(
            "script_content",
            '"""LLM-generated skill."""\n\n\ndef main() -> None:\n    pass\n',
        )
    )

    # Validate Python syntax; fall back to stub on failure.
    try:
        compile(script_content, "scripts/main.py", "exec")
    except SyntaxError:
        script_content = '"""LLM-generated skill (syntax-repaired fallback)."""\n\n\ndef main() -> None:\n    pass\n'

    body = f"## Goal\n{task.description}\n\n## Workflow\n{workflow}\n"
    skill = Skill(
        id=_seed_skill_id(task.task_id, index),
        frontmatter=SkillFrontmatter(
            name=name,
            description=description,
            tags=["llm-generated", task.domain],
            metadata={"origin": "llm-generated"},
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
        provenance=SkillProvenance(source="llm_generated", generation=0),
    )
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
    llm: "LLMClient | None" = None,
) -> list[Skill]:
    """Construct the initial population from a redundant market pool.

    When the retrieved market skills fall short of *target_size*, the gap is
    filled by LLM-generated skills (if *llm* is provided) or synthetic stubs.
    The number of generated skills is capped at *max_generated_ratio* × target_size.
    """

    retrieved = retrieve_skills(task, market_skills, top_k=top_k)
    safe_skills: list[Skill] = [skill for skill in retrieved if safety_filter.scan(skill).allowed]

    generated_cap = max(1, int(target_size * max_generated_ratio))
    generated_count = 0
    while len(safe_skills) < target_size and generated_count < generated_cap:
        index = len(safe_skills) + 1
        if llm is not None:
            generated = llm_generate_skill(task, index, llm)
        else:
            generated = build_synthetic_seed_skill(task, index)
        safe_skills.append(generated)
        generated_count += 1

    return safe_skills[:target_size]
