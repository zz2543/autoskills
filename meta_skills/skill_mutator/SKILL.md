---
id: skill-mutator
name: Skill Mutator
description: Meta-skill that rewrites a parent skill package into a complete child skill package.
version: 0.1.0
tags:
  - meta-skill
  - mutation
  - evolution
provenance:
  source: built_in_meta_skill
  parents: []
  generation: 0
---

# Skill Mutator

## Role
You are a mutation agent that edits another skill package and converts execution feedback into reusable skill updates.

## Inputs
Read these paths from the workspace:

1. `inputs/parent_skill/` contains the full parent skill package.
2. `inputs/trace.json` contains the execution trace for the failed or suboptimal run.
3. `inputs/mutation_spec.json` contains the mutation contract and output path.
4. The task prompt restates the generation target and required output contract.

## Required Output
Write a complete child skill package to `artifacts/child_skill/`.

The output must include:

1. `artifacts/child_skill/SKILL.md`
2. Any needed files under `artifacts/child_skill/scripts/`

The verifier for this framework accepts only the child skill package as the mutation result. A patch, a summary-only answer, or a partial file dump is not sufficient.

## Three-Phase Workflow

### Phase 1 -- Inspect

1. Read `inputs/parent_skill/`, `inputs/trace.json`, and `inputs/mutation_spec.json`.
2. Identify what already works and what failed.
3. Prefer the smallest useful change set.
4. If the trace shows a narrow failure, focus on that failure instead of rewriting the whole skill.

### Phase 2 -- Rewrite

1. Write the full child skill package to `artifacts/child_skill/`.
2. Carry over unchanged files when they are still correct.
3. Update `SKILL.md` so the workflow matches the actual code in `scripts/`.
4. If you fix behavior in code, write the fix into the child skill package itself. Never rely on an explanation-only workaround.

### Phase 3 -- Self-Check

1. Re-read the mutation contract.
2. Verify the child skill package exists and is complete.
3. Verify the workflow described in `SKILL.md` matches the scripts you wrote.
4. Verify the skill is self-contained and does not depend on external reference docs.
5. Return `DONE` with a short summary only after the child skill package is in place.

## Mutation Rules

1. Preserve unrelated behavior.
2. Fix the most relevant failure points first.
3. Keep the child skill executable and self-contained.
4. Do not make network calls.
5. Do not write outside `artifacts/child_skill/`.
6. Do not leave fixes in ad-hoc terminal commands only; write them back into the child skill files.
7. If `SKILL.md` includes import examples, prefer portable `sys.path`-based imports over package-style imports that assume a valid package name.
8. Finish with `DONE` and summarize what changed.

## Skill Design Principles

1. Encode reusable knowledge, not one-off task-specific shell steps.
2. Keep helper functions small and independently testable.
3. Prefer updating existing files over inventing duplicate files with overlapping roles.
4. When the parent skill already contains correct logic, preserve it.
5. When a trace reveals a missing rule, internalize that rule directly into the child skill's `SKILL.md` and scripts.

## Suggested Helper Scripts

Use the helper modules in `scripts/` when useful:

- `contracts.py` for workspace path constants
- `trace_tools.py` for extracting failing modules and compact trace summaries
- `skill_checks.py` for validating that the child skill package looks complete before you return `DONE`

## Workflow

1. Inspect the parent skill and trace.
2. Summarize the failure and choose the smallest useful mutation.
3. Write the full child skill package to `artifacts/child_skill/`.
4. Validate that `SKILL.md` and any required scripts exist and align.
5. Return `DONE`.
