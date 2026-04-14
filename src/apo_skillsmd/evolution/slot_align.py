"""Functional slot alignment used by module-level crossover."""

from __future__ import annotations

import ast
import re
from collections import defaultdict

from pydantic import BaseModel

from apo_skillsmd.skill.model import Skill


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


def align_functional_slots(left_skill: Skill, right_skill: Skill) -> list[SlotPair]:
    """Align functions by normalized names, then by stable order as fallback."""

    left_slots = _extract_functions(left_skill)
    right_slots = _extract_functions(right_skill)

    if not left_slots and not right_slots:
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
