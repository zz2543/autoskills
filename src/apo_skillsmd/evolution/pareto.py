"""NSGA-II style selection in the two-objective plane."""

from __future__ import annotations

from math import inf

from pydantic import BaseModel, Field

from apo_skillsmd.skill.model import Skill
from apo_skillsmd.trace.schema import Trace
from apo_skillsmd.types import SkillEvaluation


class ParetoCandidate(BaseModel):
    """Candidate skill plus its evaluation metrics."""

    skill: Skill
    evaluation: SkillEvaluation
    trace: Trace | None = None
    rank: int = 0
    crowding: float = 0.0


def dominates(left: ParetoCandidate, right: ParetoCandidate) -> bool:
    """Return whether left dominates right."""

    left_pass = left.evaluation.pass_rate
    right_pass = right.evaluation.pass_rate
    left_cost = left.evaluation.execution_tokens
    right_cost = right.evaluation.execution_tokens

    no_worse = left_pass >= right_pass and left_cost <= right_cost
    strictly_better = left_pass > right_pass or left_cost < right_cost
    return no_worse and strictly_better


def non_dominated_sort(candidates: list[ParetoCandidate]) -> list[list[ParetoCandidate]]:
    """Partition candidates into Pareto fronts."""

    domination_sets: dict[int, list[int]] = {}
    domination_counts: dict[int, int] = {}
    fronts: list[list[int]] = [[]]

    for i, candidate in enumerate(candidates):
        domination_sets[i] = []
        domination_counts[i] = 0
        for j, other in enumerate(candidates):
            if i == j:
                continue
            if dominates(candidate, other):
                domination_sets[i].append(j)
            elif dominates(other, candidate):
                domination_counts[i] += 1
        if domination_counts[i] == 0:
            candidate.rank = 1
            fronts[0].append(i)

    current_front = 0
    while current_front < len(fronts) and fronts[current_front]:
        next_front: list[int] = []
        for i in fronts[current_front]:
            for dominated in domination_sets[i]:
                domination_counts[dominated] -= 1
                if domination_counts[dominated] == 0:
                    candidates[dominated].rank = current_front + 2
                    next_front.append(dominated)
        if next_front:
            fronts.append(next_front)
        current_front += 1

    materialized: list[list[ParetoCandidate]] = []
    for front in fronts:
        if front:
            materialized.append([candidates[i] for i in front])
    return materialized


def assign_crowding_distance(front: list[ParetoCandidate]) -> None:
    """Assign NSGA-II crowding distance for one Pareto front."""

    if not front:
        return
    if len(front) <= 2:
        for candidate in front:
            candidate.crowding = inf
        return

    for candidate in front:
        candidate.crowding = 0.0

    objectives = [
        ("pass_rate", True),
        ("execution_tokens", False),
    ]

    for attr, maximize in objectives:
        ordered = sorted(
            front,
            key=lambda candidate: getattr(candidate.evaluation, attr),
            reverse=maximize,
        )
        ordered[0].crowding = inf
        ordered[-1].crowding = inf
        min_value = getattr(ordered[-1].evaluation, attr)
        max_value = getattr(ordered[0].evaluation, attr)
        scale = max(max_value - min_value, 1e-9)
        for index in range(1, len(ordered) - 1):
            prev_value = getattr(ordered[index - 1].evaluation, attr)
            next_value = getattr(ordered[index + 1].evaluation, attr)
            ordered[index].crowding += abs(next_value - prev_value) / scale


def nsga2_select(candidates: list[ParetoCandidate], *, size: int) -> list[ParetoCandidate]:
    """Select the next population using front order and crowding distance."""

    fronts = non_dominated_sort(candidates)
    selected: list[ParetoCandidate] = []
    for front in fronts:
        assign_crowding_distance(front)
        if len(selected) + len(front) <= size:
            selected.extend(front)
            continue
        remaining = size - len(selected)
        selected.extend(sorted(front, key=lambda candidate: candidate.crowding, reverse=True)[:remaining])
        break
    return selected


def current_pareto_front(candidates: list[ParetoCandidate]) -> list[ParetoCandidate]:
    """Return the first Pareto front."""

    fronts = non_dominated_sort(candidates)
    return fronts[0] if fronts else []
