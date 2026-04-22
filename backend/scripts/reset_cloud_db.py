"""Dangerous one-time helper to reset the current cloud PostgreSQL public schema."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.shared.infra.database import reset_postgres_public_schema  # noqa: E402
from app.shared.infra.env_support import get_env_bool  # noqa: E402
from app.shared.infra.runtime import is_cloud_mode  # noqa: E402

ALLOW_RESET_ENV = "ALLOW_CLOUD_DB_RESET"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reset the current cloud PostgreSQL public schema.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Actually perform the schema reset. Without this flag the script refuses to run.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if not is_cloud_mode():
        print("reset_cloud_db requires APP_MODE=cloud.", file=sys.stderr)
        return 2

    args = _build_arg_parser().parse_args(argv)
    allow_reset = bool(args.force) or get_env_bool(ALLOW_RESET_ENV, False)
    if not allow_reset:
        print(
            f"Use --force (or set {ALLOW_RESET_ENV}=true) to reset the current cloud database.",
            file=sys.stderr,
        )
        return 3

    try:
        reset_postgres_public_schema()
    except Exception as exc:  # noqa: BLE001
        print(f"cloud database reset failed: {exc}", file=sys.stderr)
        return 1

    print(
        "cloud database public schema reset completed "
        f"(forced={str(bool(args.force)).lower()}, {ALLOW_RESET_ENV}={str(get_env_bool(ALLOW_RESET_ENV, False)).lower()})"
    )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("APP_MODE", "cloud")
    raise SystemExit(main())
