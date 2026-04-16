#!/usr/bin/env python3
"""Cleanup residual directories.

Commands:
  1) Show help
     python scripts/cleanup_residual_dirs.py -h

  2) Scan current directory and delete targets
     python scripts/cleanup_residual_dirs.py

  3) Dry run (preview only, no deletion)
     python scripts/cleanup_residual_dirs.py --dry-run

  4) Verbose mode (print skipped directories too)
     python scripts/cleanup_residual_dirs.py --verbose

  5) Scan a specific path
     python scripts/cleanup_residual_dirs.py <path>

  6) Dry run + verbose + specific path
     python scripts/cleanup_residual_dirs.py <path> --dry-run --verbose

Behavior:
  - Removes empty directories.
  - Removes directories that contain only '__pycache__' subdirectories.
  - Skips '.git', '.venv', and 'node_modules' trees.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


IGNORED_NAMES = {".git", ".venv", "node_modules"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Recursively remove residual directories: empty directories and directories "
            "that only contain __pycache__."
        )
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Root path to scan (default: current directory).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without deleting anything.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed traversal info.",
    )
    return parser.parse_args()


def is_only_pycache(dir_path: Path) -> bool:
    children = list(dir_path.iterdir())
    if not children:
        return False
    return all(child.is_dir() and child.name == "__pycache__" for child in children)


def should_skip(dir_path: Path, root: Path) -> bool:
    if dir_path == root:
        return True
    relative_parts = dir_path.relative_to(root).parts
    return any(part in IGNORED_NAMES for part in relative_parts)


def remove_dir(dir_path: Path, dry_run: bool) -> None:
    if dry_run:
        print(f"[DRY-RUN] remove: {dir_path}")
        return
    shutil.rmtree(dir_path)
    print(f"[REMOVED] {dir_path}")


def cleanup(root: Path, dry_run: bool, verbose: bool) -> int:
    removed_count = 0

    # Bottom-up traversal so child directories are handled before parents.
    for dir_path in sorted(
        [p for p in root.rglob("*") if p.is_dir()],
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        if should_skip(dir_path, root):
            if verbose:
                print(f"[SKIP] {dir_path}")
            continue

        if is_only_pycache(dir_path):
            remove_dir(dir_path, dry_run=dry_run)
            removed_count += 1
            continue

        if not any(dir_path.iterdir()):
            remove_dir(dir_path, dry_run=dry_run)
            removed_count += 1

    return removed_count


def main() -> None:
    args = parse_args()
    root = Path(args.path).resolve()

    if not root.exists():
        raise SystemExit(f"Path does not exist: {root}")
    if not root.is_dir():
        raise SystemExit(f"Path is not a directory: {root}")

    removed = cleanup(root=root, dry_run=args.dry_run, verbose=args.verbose)
    mode = "would be removed" if args.dry_run else "removed"
    print(f"Done. {removed} directories {mode}.")


if __name__ == "__main__":
    main()
