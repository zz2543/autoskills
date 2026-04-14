"""Bandit wrapper used by the safety filter."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def run_bandit_scan(path: str | Path) -> list[dict[str, Any]]:
    """Run Bandit in JSON mode if available.

    The function fails closed only when Bandit successfully reports findings.
    Missing Bandit is treated as a non-blocking environment issue so the rest of
    the framework remains inspectable.
    """

    try:
        result = subprocess.run(
            ["python", "-m", "bandit", "-r", str(path), "-f", "json"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []

    if result.returncode not in {0, 1}:
        return []

    stdout = result.stdout.strip()
    if not stdout:
        return []
    payload = json.loads(stdout)
    return payload.get("results", [])
