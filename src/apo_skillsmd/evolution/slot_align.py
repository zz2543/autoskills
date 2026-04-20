"""Functional slot alignment used by module-level crossover."""

from __future__ import annotations

import ast
import json
import re
from collections import defaultdict
from typing import TYPE_CHECKING

from pydantic import BaseModel

from apo_skillsmd.skill.model import Skill
from apo_skillsmd.types import MessageRole

if TYPE_CHECKING:
    from apo_skillsmd.llm.base import LLMClient


class SlotImplementation(BaseModel):
    """One parent-side implementation of a functional slot."""

    script_path: str
    function_name: str


class SlotPair(BaseModel):
    """Aligned slot implementations across both parents."""

    slot_name: str
    left: SlotImplementation | None = None
    right: SlotImplementation | None = None


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _extract_functions(skill: Skill) -> list[SlotImplementation]:
    slots: list[SlotImplementation] = []
    for path, script in skill.scripts.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(script.content)
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                slots.append(SlotImplementation(script_path=path, function_name=node.name))
    return slots


def _extract_function_signatures(skill: Skill) -> list[dict]:
    """Extract function name + first docstring line for LLM prompting."""
    sigs: list[dict] = []
    for path, script in skill.scripts.items():
        if not path.endswith(".py"):
            continue
        try:
            tree = ast.parse(script.content)
        except SyntaxError:
            continue
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            docstring = ""
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                docstring = node.body[0].value.value.split("\n")[0].strip()
            sigs.append(
                {
                    "script_path": path,
                    "function_name": node.name,
                    "docstring": docstring,
                }
            )
    return sigs


_LLM_ALIGN_PROMPT = """\
You are aligning functions from two agent skills into semantic functional slots.

Skill A functions:
{left_sigs}

Skill B functions:
{right_sigs}

Group functions that serve the same semantic purpose into slots.
Return ONLY a JSON array — no prose before or after:
[
  {{
    "slot_name": "semantic_purpose_name",
    "left": {{"script_path": "...", "function_name": "..."}} or null,
    "right": {{"script_path": "...", "function_name": "..."}} or null
  }},
  ...
]

Rules:
- Use snake_case slot names that describe the function's purpose (e.g. "parse_input", "format_output").
- Unmatched functions get null on the other side.
- Every function from A and B must appear exactly once.
"""


def llm_align_functional_slots(left_skill: Skill, right_skill: Skill, llm: "LLMClient") -> list[SlotPair]:
    """Use the LLM to align functions from two skills by semantic purpose."""

    from apo_skillsmd.llm.base import LLMMessage

    left_sigs = _extract_function_signatures(left_skill)
    right_sigs = _extract_function_signatures(right_skill)

    if not left_sigs and not right_sigs:
        return _fallback_slot(left_skill, right_skill)

    prompt = _LLM_ALIGN_PROMPT.format(
        left_sigs=json.dumps(left_sigs, indent=2),
        right_sigs=json.dumps(right_sigs, indent=2),
    )
    try:
        response = llm.complete(
            [LLMMessage(role=MessageRole.USER, content=prompt)],
            temperature=0.1,
            max_tokens=1024,
        )
        text = response.message
        array_match = re.search(r"\[[\s\S]*\]", text)
        raw: list[dict] = json.loads(array_match.group(0)) if array_match else []
    except Exception:
        return align_functional_slots(left_skill, right_skill)

    pairs: list[SlotPair] = []
    for item in raw:
        left_impl = None
        right_impl = None
        if item.get("left"):
            left_impl = SlotImplementation(
                script_path=item["left"]["script_path"],
                function_name=item["left"]["function_name"],
            )
        if item.get("right"):
            right_impl = SlotImplementation(
                script_path=item["right"]["script_path"],
                function_name=item["right"]["function_name"],
            )
        pairs.append(SlotPair(slot_name=str(item.get("slot_name", "unknown")), left=left_impl, right=right_impl))

    return pairs or align_functional_slots(left_skill, right_skill)


def _fallback_slot(left_skill: Skill, right_skill: Skill) -> list[SlotPair]:
    return [
        SlotPair(
            slot_name="main",
            left=SlotImplementation(script_path=next(iter(left_skill.scripts), "scripts/main.py"), function_name="main")
            if left_skill.scripts
            else None,
            right=SlotImplementation(script_path=next(iter(right_skill.scripts), "scripts/main.py"), function_name="main")
            if right_skill.scripts
            else None,
        )
    ]


def align_functional_slots(left_skill: Skill, right_skill: Skill) -> list[SlotPair]:
    """Align functions by normalized names, then by stable order as fallback."""

    left_slots = _extract_functions(left_skill)
    right_slots = _extract_functions(right_skill)

    if not left_slots and not right_slots:
        return _fallback_slot(left_skill, right_skill)

    grouped: dict[str, SlotPair] = defaultdict(lambda: SlotPair(slot_name=""))
    for slot in left_slots:
        key = _normalize_name(slot.function_name)
        grouped[key].slot_name = key
        grouped[key].left = slot
    for slot in right_slots:
        key = _normalize_name(slot.function_name)
        grouped[key].slot_name = key
        grouped[key].right = slot

    aligned = list(grouped.values())
    aligned.sort(key=lambda pair: pair.slot_name)
    return aligned
