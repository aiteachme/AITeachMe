"""Initialize a local `.env` file from `.env.example`.

This script is intentionally lightweight:

- it copies `.env.example` to `.env` when `.env` does not exist
- it refuses to overwrite an existing `.env` unless `--force` is passed
- it prints the next steps so new contributors know what to edit and test
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for `.env` initialization."""

    parser = argparse.ArgumentParser(description="Initialize .env from .env.example")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite .env if it already exists.",
    )
    return parser.parse_args()


def main() -> int:
    """Create `.env` from the example file and print onboarding hints."""

    args = parse_args()
    project_root = Path(__file__).resolve().parent.parent
    env_example = project_root / ".env.example"
    env_file = project_root / ".env"

    if not env_example.exists():
        print("ERROR: .env.example not found.")
        return 1

    if env_file.exists() and not args.force:
        print("SKIP: .env already exists.")
        print("If you want to recreate it from .env.example, run:")
        print("  python scripts/init_env.py --force")
        return 0

    shutil.copyfile(env_example, env_file)
    print(f"OK: created {env_file.name} from {env_example.name}")
    print("")
    print("Next steps:")
    print("1. Open .env and fill in LLM_API_KEY")
    print("2. Adjust optional values only if needed")
    print("3. Validate config with: python scripts/test_env.py")
    print("4. Start server with: uvicorn app.main:app --reload --port 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
