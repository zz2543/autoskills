"""Download redundant skill pools used for initialization."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from apo_skillsmd.bench.pool_sources import DEFAULT_POOL_SOURCES


def clone_or_update(repo_url: str, out_dir: Path) -> None:
    if out_dir.exists():
        subprocess.run(["git", "-C", str(out_dir), "pull", "--ff-only"], check=True)
        return
    subprocess.run(["git", "clone", repo_url, str(out_dir)], check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download redundant skill pools.")
    parser.add_argument("--out", required=True, help="Directory that will contain all pool mirrors.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    for source in DEFAULT_POOL_SOURCES:
        clone_or_update(source.url, root / source.local_dir)


if __name__ == "__main__":
    main()
