"""Prepare Render/PostgreSQL runtime database objects after Alembic migration."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.shared.infra.env_support import get_env_bool  # noqa: E402
from app.shared.infra.database import prepare_postgres_runtime_schema  # noqa: E402
from app.shared.infra.runtime import is_cloud_mode  # noqa: E402


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare cloud PostgreSQL runtime objects.")
    parser.add_argument(
        "--allow-vector-rebuild",
        action="store_true",
        help="Allow rebuilding retrieval_chunk.embedding when the configured dimension changes.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if not is_cloud_mode():
        print("prepare_cloud_db requires APP_MODE=cloud.", file=sys.stderr)
        return 2

    args = _build_arg_parser().parse_args(argv)
    allow_vector_rebuild = bool(args.allow_vector_rebuild) or get_env_bool("ALLOW_CLOUD_VECTOR_REBUILD", False)
    try:
        prepare_postgres_runtime_schema(allow_vector_rebuild=allow_vector_rebuild)
    except Exception as exc:  # noqa: BLE001
        print(f"cloud database preparation failed: {exc}", file=sys.stderr)
        return 1

    print(
        "cloud database prepared "
        f"(ALLOW_CLOUD_VECTOR_REBUILD={str(allow_vector_rebuild).lower()})"
    )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("APP_MODE", "cloud")
    raise SystemExit(main())
