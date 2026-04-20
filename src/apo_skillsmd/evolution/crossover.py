"""Module-level crossover for mixed markdown + code skills."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from apo_skillsmd.evolution.slot_align import SlotPair, align_functional_slots, llm_align_functional_slots
from apo_skillsmd.skill.model import Skill, SkillFrontmatter
from apo_skillsmd.trace.attribution import module_score
from apo_skillsmd.trace.schema import Trace
from apo_skillsmd.types import MessageRole

if TYPE_CHECKING:
    from apo_skillsmd.llm.base import LLMClient


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


_LLM_STITCH_PROMPT = """\
You are merging two agent skills into one coherent skill.

Parent A — "{left_name}":
{left_md}

Parent B — "{right_name}":
{right_md}

Code winner decisions (which parent's implementation won per functional slot):
{winners_summary}

Write a unified SKILL.md body (markdown only, no frontmatter) that:
1. Has a brief ## Goal section describing the merged skill's purpose.
2. Has a ## Workflow section with clear numbered steps aligned with the winning code.
3. Is concise — shorter is better.

Return ONLY the markdown text, nothing else.
"""


def _llm_stitch_markdown(left: Skill, right: Skill, winners: dict[str, str], llm: "LLMClient") -> str:
    """Use the LLM to produce a coherent SKILL.md body for the child skill."""

    from apo_skillsmd.llm.base import LLMMessage

    winners_summary = "\n".join(f"- slot '{slot}': takes code from parent {side}" for slot, side in winners.items())
    prompt = _LLM_STITCH_PROMPT.format(
        left_name=left.frontmatter.name,
        left_md=left.md_body[:800],
        right_name=right.frontmatter.name,
        right_md=right.md_body[:800],
        winners_summary=winners_summary or "(no named slots)",
    )
    try:
        response = llm.complete(
            [LLMMessage(role=MessageRole.USER, content=prompt)],
            temperature=0.2,
            max_tokens=800,
        )
        md = response.message.strip()
        if md:
            return md + "\n"
    except Exception:
        pass
    return _merge_markdown(left, right)


def _build_child(
    left: Skill,
    right: Skill,
    *,
    script_owners: dict[str, str],
    merged_md: str,
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
    child.md_body = merged_md
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
    llm: "LLMClient | None" = None,
) -> Skill | None:
    """Five-step module-level crossover described in the design doc.

    When *llm* is provided:
    - Step 1 uses LLM-assisted functional slot alignment.
    - Step 4 uses LLM to generate a coherent merged SKILL.md.
    Without *llm*, both steps fall back to the heuristic implementations.
    """

    if not has_complementary_modifications(left, right):
        return None

    # Step 1: functional slot alignment
    if llm is not None:
        slot_pairs = llm_align_functional_slots(left, right, llm)
    else:
        slot_pairs = align_functional_slots(left, right)

    # Step 2: pick winner per slot using trace scores
    winners = _pick_slot_winners(slot_pairs, left_trace, right_trace)

    # Step 3: determine script file ownership
    script_owners = _pick_script_owners(slot_pairs, winners)

    # Step 4: generate coherent markdown
    if llm is not None:
        merged_md = _llm_stitch_markdown(left, right, winners, llm)
    else:
        merged_md = _merge_markdown(left, right)

    # Step 5: assemble child and syntax check
    child = _build_child(left, right, script_owners=script_owners, merged_md=merged_md, generation=generation)
    if not passes_syntax_check(child):
        return None
    return child
