"""Retrieve relevant seed skills from a redundant pool."""

from __future__ import annotations

import re
from collections import Counter

try:
    from rank_bm25 import BM25Okapi
except ImportError:  # pragma: no cover - optional dependency
    BM25Okapi = None

from apo_skillsmd.skill.model import Skill
from apo_skillsmd.types import TaskSpec


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", text.lower())


def _skill_document(skill: Skill) -> str:
    metadata = " ".join(skill.frontmatter.tags)
    return f"{skill.frontmatter.name} {skill.frontmatter.description} {metadata} {skill.md_body}"


def _fallback_scores(query_tokens: list[str], skills: list[Skill]) -> list[tuple[Skill, float]]:
    query_counter = Counter(query_tokens)
    scored: list[tuple[Skill, float]] = []
    for skill in skills:
        tokens = _tokenize(_skill_document(skill))
        overlap = sum((Counter(tokens) & query_counter).values())
        scored.append((skill, float(overlap)))
    return scored


def retrieve_skills(task: TaskSpec, skills: list[Skill], *, top_k: int) -> list[Skill]:
    """Retrieve the most relevant skills for a task description."""

    if not skills:
        return []

    query_tokens = _tokenize(task.description)
    if BM25Okapi is None:
        ranked = sorted(_fallback_scores(query_tokens, skills), key=lambda item: item[1], reverse=True)
        return [skill for skill, _ in ranked[:top_k]]

    corpus = [_tokenize(_skill_document(skill)) for skill in skills]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(query_tokens)
    ranked = sorted(zip(skills, scores, strict=False), key=lambda item: item[1], reverse=True)
    return [skill for skill, _ in ranked[:top_k]]
