"""Helpers for scoring trace events during crossover and analysis."""

from __future__ import annotations

from apo_skillsmd.trace.schema import Trace


def module_score(trace: Trace, module_prefix: str) -> int:
    """Compute a simple success-minus-failure score for one module prefix."""

    score = 0
    for event in trace.module_events:
        if not event.module.startswith(module_prefix):
            continue
        score += 1
        if event.exceptions:
            score -= len(event.exceptions)
    return score


def failing_modules(trace: Trace) -> list[str]:
    """List modules that emitted at least one exception."""

    return [event.module for event in trace.module_events if event.exceptions]
