"""Module-level crossover for mixed markdown + code skills."""

from __future__ import annotations

from collections import Counter, defaultdict

from apo_skillsmd.evolution.slot_align import SlotPair, align_functional_slots
from apo_skillsmd.skill.model import Skill, SkillFrontmatter
from apo_skillsmd.trace.attribution import module_score
from apo_skillsmd.trace.schema import Trace


def pick_shorter(left: str, right: str) -> str:
    """Prefer the shorter non-empty description to control token cost."""

    if not left:
        return right
    if not right:
        return left
    return left if len(left) <= len(right) else right


def merge_union_lines(left: str, right: str) -> str:
    """Merge markdown fragments without duplicating identical lines."""

    seen: set[str] = set()
    merged: list[str] = []
    for line in (left.splitlines() + right.splitlines()):
        normalized = line.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        merged.append(line)
    return "\n".join(merged).strip()


def has_complementary_modifications(left: Skill, right: Skill) -> bool:
    """Return whether crossover is likely to provide new structure."""

    return (
        set(left.scripts) != set(right.scripts)
        or left.md_body != right.md_body
        or left.frontmatter.description != right.frontmatter.description
    )


def _pick_slot_winners(slot_pairs: list[SlotPair], left_trace: Trace, right_trace: Trace) -> dict[str, str]:
    winners: dict[str, str] = {}
    for pair in slot_pairs:
        left_score = (
            module_score(left_trace, f"{pair.left.script_path}:{pair.left.function_name}") if pair.left else -1
        )
        right_score = (
            module_score(right_trace, f"{pair.right.script_path}:{pair.right.function_name}") if pair.right else -1
        )
        winners[pair.slot_name] = "left" if left_score >= right_score else "right"
    return winners


def _pick_script_owners(slot_pairs: list[SlotPair], winners: dict[str, str]) -> dict[str, str]:
    ownership: dict[str, Counter[str]] = defaultdict(Counter)
    for pair in slot_pairs:
        winner = winners[pair.slot_name]
        if winner == "left" and pair.left:
            ownership[pair.left.script_path][winner] += 1
        elif winner == "right" and pair.right:
            ownership[pair.right.script_path][winner] += 1

    decided: dict[str, str] = {}
    for script_path, counter in ownership.items():
        decided[script_path] = counter.most_common(1)[0][0]
    return decided


def _merge_markdown(left: Skill, right: Skill) -> str:
    sections = [
        "# Crossover Skill",
        "",
        "## Combined Workflow",
        merge_union_lines(left.md_body, right.md_body),
    ]
    return "\n".join(section for section in sections if section).strip() + "\n"


def _build_child(
    left: Skill,
    right: Skill,
    *,
    script_owners: dict[str, str],
    generation: int,
) -> Skill:
    child = left.clone(new_id=f"{left.id}__x__{right.id}-g{generation}")
    child.frontmatter = SkillFrontmatter(
        name=f"{left.frontmatter.name} x {right.frontmatter.name}",
        description=pick_shorter(left.frontmatter.description, right.frontmatter.description),
        version="0.1.0",
        tags=sorted(set(left.frontmatter.tags + right.frontmatter.tags)),
        category=left.frontmatter.category or right.frontmatter.category,
        metadata={
            "parents": [left.id, right.id],
            "operator": "crossover",
        },
    )
    child.md_body = _merge_markdown(left, right)
    child.scripts = {}
    all_paths = sorted(set(left.scripts) | set(right.scripts))
    for path in all_paths:
        owner = script_owners.get(path)
        if owner == "right" and path in right.scripts:
            child.scripts[path] = right.scripts[path]
        elif path in left.scripts:
            child.scripts[path] = left.scripts[path]
        elif path in right.scripts:
            child.scripts[path] = right.scripts[path]

    child.resources = {**left.resources, **right.resources}
    child.provenance.parents = [left.id, right.id]
    child.provenance.generation = generation
    child.provenance.source = "crossover"
    child.provenance.notes.append("Module-level crossover applied.")
    child.refresh_content_hash()
    return child


def passes_syntax_check(skill: Skill) -> bool:
    """Fail fast when crossover produces invalid Python modules."""

    for path, script in skill.scripts.items():
        if not path.endswith(".py"):
            continue
        try:
            compile(script.content, path, "exec")
        except SyntaxError:
            return False
    return True


def crossover(
    left: Skill,
    right: Skill,
    left_trace: Trace,
    right_trace: Trace,
    *,
    generation: int,
) -> Skill | None:
    """Perform the five-step module-level crossover described in the design doc."""

    if not has_complementary_modifications(left, right):
        return None

    slot_pairs = align_functional_slots(left, right)
    winners = _pick_slot_winners(slot_pairs, left_trace, right_trace)
    script_owners = _pick_script_owners(slot_pairs, winners)
    child = _build_child(left, right, script_owners=script_owners, generation=generation)
    if not passes_syntax_check(child):
        return None
    return child
