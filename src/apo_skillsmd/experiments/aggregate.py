"""Aggregate experiment summaries from multiple result directories."""

from __future__ import annotations

import json
from pathlib import Path


def aggregate_summaries(result_dirs: list[str | Path]) -> list[dict]:
    """Read `experiment_summary.json` from multiple experiment directories."""

    summaries: list[dict] = []
    for result_dir in result_dirs:
        path = Path(result_dir) / "experiment_summary.json"
        if not path.exists():
            continue
        summaries.append(json.loads(path.read_text(encoding="utf-8")))
    return summaries
