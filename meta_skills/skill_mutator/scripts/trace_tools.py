"""Helpers for inspecting mutation traces inside the meta-skill workspace."""

from __future__ import annotations

import json
from pathlib import Path


def load_trace(trace_path: str | Path) -> dict:
    """Load the mutation trace JSON file."""

    return json.loads(Path(trace_path).read_text(encoding="utf-8"))


def failing_modules(trace_payload: dict) -> list[str]:
    """Return modules that emitted exceptions during the parent run."""

    modules: list[str] = []
    for event in trace_payload.get("module_events", []):
        if event.get("exceptions"):
            modules.append(str(event.get("module", "")))
    return modules


def summarize_trace(trace_payload: dict) -> str:
    """Create a compact text summary that can be copied into notes or SKILL.md."""

    failures = failing_modules(trace_payload)
    token_usage = trace_payload.get("execution_tokens", 0)
    if failures:
        return f"Observed failures in: {', '.join(sorted(set(failures)))}. Previous token usage: {token_usage}."
    return f"No explicit failure module recorded. Previous token usage: {token_usage}."
