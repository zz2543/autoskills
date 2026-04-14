"""Best-effort runtime guard helpers."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


def detect_hardcoded_answer(expected_output: str, candidate_text: str, *, min_length: int = 12) -> bool:
    """Detect direct answer leakage through literal reuse or hash matches."""

    if len(expected_output) < min_length:
        return False
    direct_match = expected_output in candidate_text
    digest_match = sha256(expected_output.encode("utf-8")).hexdigest() in candidate_text
    return direct_match or digest_match


def is_path_within_root(root: Path, candidate: Path) -> bool:
    """Check whether a candidate path stays under the sandbox root."""

    return str(candidate.resolve()).startswith(str(root.resolve()))
