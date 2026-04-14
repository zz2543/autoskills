"""Trace-guided mutation operators."""

from __future__ import annotations

from apo_skillsmd.evolution.mutation_agent import MutationAgentRunner
from apo_skillsmd.skill.model import Skill
from apo_skillsmd.trace.schema import Trace


def trace_guided_mutation(
    skill: Skill,
    trace: Trace,
    *,
    generation: int,
    mutation_runner: MutationAgentRunner,
) -> Skill:
    """Create a child skill through the fixed mutation meta-skill."""

    return mutation_runner.mutate(skill, trace, generation=generation)


def lineage_guided_mutation(skill: Skill, *, generation: int) -> Skill:
    """Ablation-friendly mutation variant used when trace guidance is disabled.

    This branch intentionally stays lightweight for now. The same mutation
    agent runner can be reused later with a lineage-only input bundle.
    """

    mutant = skill.clone(new_id=f"{skill.id}-lin-g{generation}")
    mutant.provenance.parents = [skill.id]
    mutant.provenance.generation = generation
    mutant.provenance.source = "lineage_mutation"
    mutant.provenance.notes.append("Lineage-only mutation applied.")
    mutant.refresh_content_hash()
    return mutant
