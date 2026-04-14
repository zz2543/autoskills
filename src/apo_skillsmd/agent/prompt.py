"""Prompt builders used by the provider-agnostic agent loop."""

from __future__ import annotations

import json

from apo_skillsmd.skill.model import Skill
from apo_skillsmd.types import TaskSpec


def build_system_prompt(skill: Skill) -> str:
    """Compose the system prompt from a skill package."""

    header = [
        "You are an execution agent operating with one mounted skill package.",
        "Follow the skill instructions carefully and use tools when needed.",
        "When the task is complete, respond with DONE plus a short summary.",
        "",
        f"Skill name: {skill.frontmatter.name}",
        f"Skill description: {skill.frontmatter.description}",
        "",
        "Skill content:",
        skill.md_body.strip(),
    ]
    return "\n".join(header).strip()


def build_task_prompt(task: TaskSpec) -> str:
    """Render one benchmark task for the user message."""

    payload = {
        "task_id": task.task_id,
        "domain": task.domain,
        "description": task.description,
        "inputs": task.inputs,
        "test_case_count": len(task.test_cases),
    }
    return "Solve the following task:\n" + json.dumps(payload, ensure_ascii=False, indent=2)
