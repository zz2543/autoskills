"""Download baseline skills repositories."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def clone_or_update(repo_url: str, out_dir: Path) -> None:
    if out_dir.exists():
        subprocess.run(["git", "-C", str(out_dir), "pull", "--ff-only"], check=True)
        return
    subprocess.run(["git", "clone", repo_url, str(out_dir)], check=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download baseline skills.")
    parser.add_argument("--out", required=True, help="Target directory for the baseline mirror.")
    parser.add_argument(
        "--repo-url",
        default="https://github.com/anthropics/skills",
        help="Repository URL.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    clone_or_update(args.repo_url, Path(args.out))


if __name__ == "__main__":
    main()
