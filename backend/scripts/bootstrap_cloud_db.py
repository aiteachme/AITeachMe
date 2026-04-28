"""Bootstrap the current cloud PostgreSQL database into the expected runtime state.

This script is intended to be the single cloud pre-deploy entrypoint.

Native runtime from the repo root:

    cd backend && python scripts/bootstrap_cloud_db.py

Docker image runtime:

    python scripts/bootstrap_cloud_db.py

Behavior:
- empty / normal Alembic-managed DB: run upgrade -> prepare -> check
- legacy DB without alembic_version but with existing app tables: require
  ALLOW_CLOUD_DB_RESET=true before wiping and rebuilding the current database
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.shared.infra.database import get_engine, reset_postgres_public_schema  # noqa: E402
from app.shared.infra.database.core import (  # noqa: E402
    _SCHEMA_TABLES,
    _get_alembic_head_revision,
    _get_postgres_alembic_revision,
    _postgres_table_exists,
)
from app.shared.infra.env_support import get_env_bool  # noqa: E402
from app.shared.infra.runtime import is_cloud_mode  # noqa: E402

ALLOW_RESET_ENV = "ALLOW_CLOUD_DB_RESET"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap cloud PostgreSQL into the expected runtime state.")
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Permit wiping only a legacy dirty database without Alembic versioning.",
    )
    return parser


def _run_script(script_name: str, *script_args: str) -> None:
    subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "scripts" / script_name), *script_args],
        cwd=BACKEND_ROOT,
        check=True,
    )


def _run_alembic_upgrade_head() -> None:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(config, "head")


def _format_revision(value: str | None) -> str:
    return value or "missing"


def _inspect_database_state() -> tuple[str | None, list[str]]:
    engine = get_engine()
    with engine.connect() as connection:
        current_revision = _get_postgres_alembic_revision(connection)
        existing_tables = [
            table.name
            for table in _SCHEMA_TABLES
            if _postgres_table_exists(connection, table.name)
        ]
    return current_revision, existing_tables


def main(argv: list[str] | None = None) -> int:
    if not is_cloud_mode():
        print("bootstrap_cloud_db requires APP_MODE=cloud.", file=sys.stderr)
        return 2

    args = _build_arg_parser().parse_args(argv)
    allow_reset = bool(args.reset_db) or get_env_bool(ALLOW_RESET_ENV, False)
    current_revision, existing_tables = _inspect_database_state()
    expected_revision = _get_alembic_head_revision()
    print(
        "cloud database bootstrap starting "
        f"(current_revision={_format_revision(current_revision)}, "
        f"expected_revision={expected_revision}, "
        f"existing_app_tables={len(existing_tables)}, "
        f"legacy_reset_allowed={str(allow_reset).lower()})"
    )

    # Dirty legacy DB: existing application tables but no Alembic version table.
    if current_revision is None and existing_tables:
        if not allow_reset:
            print(
                "Detected a legacy PostgreSQL schema without Alembic versioning.\n"
                f"Existing tables: {', '.join(existing_tables[:12])}\n"
                f"Use --reset-db (or set {ALLOW_RESET_ENV}=true) only if this database can be wiped and rebuilt.\n"
                "If the old data must be preserved, migrate it manually instead of resetting.",
                file=sys.stderr,
            )
            return 4
        print("legacy unversioned cloud database detected; resetting public schema before migrations")
        reset_postgres_public_schema()

    try:
        _run_alembic_upgrade_head()
        upgraded_revision, _ = _inspect_database_state()
        print(
            "cloud database migration completed "
            f"(current_revision={_format_revision(upgraded_revision)}, "
            f"expected_revision={expected_revision})"
        )
        _run_script("prepare_cloud_db.py")
        _run_script("check_cloud_db.py")
    except subprocess.CalledProcessError as exc:
        print(
            f"cloud database bootstrap failed while running `{Path(exc.cmd[-1]).name}` "
            f"(exit={exc.returncode})",
            file=sys.stderr,
        )
        return exc.returncode or 1
    except Exception as exc:  # noqa: BLE001
        print(f"cloud database bootstrap failed: {exc}", file=sys.stderr)
        return 1

    print(
        "cloud database bootstrap completed "
        f"(reset_db={str(bool(args.reset_db)).lower()}, "
        f"{ALLOW_RESET_ENV}={str(get_env_bool(ALLOW_RESET_ENV, False)).lower()})"
    )
    return 0


if __name__ == "__main__":
    os.environ.setdefault("APP_MODE", "cloud")
    raise SystemExit(main())
