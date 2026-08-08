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
from collections.abc import Callable
import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

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
from app.shared.infra.env_support import get_env, get_env_bool  # noqa: E402
from app.shared.infra.runtime import (  # noqa: E402
    collect_project_settings_config_errors,
    is_cloud_mode,
)

ALLOW_RESET_ENV = "ALLOW_CLOUD_DB_RESET"


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap cloud PostgreSQL into the expected runtime state.")
    parser.add_argument(
        "--reset-db",
        action="store_true",
        help="Permit wiping only a legacy dirty database without Alembic versioning.",
    )
    return parser


def _prepare_runtime_schema() -> int:
    from scripts import prepare_cloud_db

    return prepare_cloud_db.main([])


def _validate_runtime_dependencies() -> int:
    from scripts import check_cloud_db

    return check_cloud_db.main()


def _run_post_migration_step(step_name: str, step: Callable[[], int]) -> None:
    exit_code = step()
    if exit_code:
        raise RuntimeError(f"{step_name} failed (exit={exit_code})")


def _run_post_migration_steps() -> None:
    _run_post_migration_step("prepare_cloud_db.py", _prepare_runtime_schema)
    _run_post_migration_step("check_cloud_db.py", _validate_runtime_dependencies)


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


def _database_target_summary() -> str:
    raw_url = (get_env("DATABASE_URL") or "").strip()
    if not raw_url:
        return "DATABASE_URL=missing"
    try:
        url = make_url(raw_url)
    except Exception:  # noqa: BLE001
        return "DATABASE_URL=unparseable"

    return (
        f"driver={url.drivername}, "
        f"host={url.host or 'unknown'}, "
        f"port={url.port or 'default'}, "
        f"database={url.database or 'unknown'}"
    )


def _looks_like_database_connectivity_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return isinstance(exc, OperationalError) or any(
        marker in text
        for marker in (
            "could not translate host name",
            "name or service not known",
            "temporary failure in name resolution",
            "connection refused",
            "connection timed out",
            "timeout expired",
            "no route to host",
            "network is unreachable",
            "password authentication failed",
        )
    )


def _format_database_connectivity_error(exc: Exception) -> str:
    text = str(exc).lower()
    lines = [
        "cloud database bootstrap failed before migrations: cannot connect to PostgreSQL.",
        f"Target: {_database_target_summary()}",
    ]
    if "could not translate host name" in text or "name or service not known" in text:
        lines.extend(
            [
                "Reason: DATABASE_URL host cannot be resolved by DNS from this runtime.",
                "If the host ends with `.svc` or `.svc.cluster.local`, it is Kubernetes-internal "
                "and only works from a workload inside the same cluster network.",
                "Fix: use the database public/pooled connection string, or run the backend/bootstrap "
                "Job in the same Sealos/Kubernetes cluster and verify the service name plus namespace.",
            ]
        )
    elif "password authentication failed" in text:
        lines.append("Reason: PostgreSQL rejected the configured username/password.")
    else:
        lines.append(
            "Reason: PostgreSQL is unreachable or rejected the connection. "
            "Check network, port, firewall, and DATABASE_URL."
        )
    lines.append(f"Original error: {exc}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    if not is_cloud_mode():
        print("bootstrap_cloud_db requires APP_MODE=cloud.", file=sys.stderr)
        return 2

    args = _build_arg_parser().parse_args(argv)
    settings_errors = collect_project_settings_config_errors()
    if settings_errors:
        print(
            "cloud database bootstrap stopped before database inspection: "
            "project settings are invalid or incompatible with this backend build.",
            file=sys.stderr,
        )
        for error in settings_errors:
            print(f"- {error}", file=sys.stderr)
        return 2

    allow_reset = bool(args.reset_db) or get_env_bool(ALLOW_RESET_ENV, False)
    try:
        current_revision, existing_tables = _inspect_database_state()
    except Exception as exc:  # noqa: BLE001
        if _looks_like_database_connectivity_error(exc):
            print(_format_database_connectivity_error(exc), file=sys.stderr)
        else:
            print(f"cloud database bootstrap failed while inspecting database: {exc}", file=sys.stderr)
        return 1

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
        # Keep preparation and validation in this process. Spawning fresh
        # interpreters repeatedly re-imports LlamaIndex/boto3 before Uvicorn.
        _run_post_migration_steps()
    except Exception as exc:  # noqa: BLE001
        if _looks_like_database_connectivity_error(exc):
            print(_format_database_connectivity_error(exc), file=sys.stderr)
        else:
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
