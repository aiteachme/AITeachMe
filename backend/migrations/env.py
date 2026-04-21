"""Alembic environment for AITeachMe PostgreSQL migrations."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Importing this module registers all table models on SQLModel.metadata.
from app.shared.infra.database import core as database_core  # noqa: F401,E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

_EXTERNAL_TABLE_PREFIXES = (
    "atm_llamaindex_rag",
    "data_atm_llamaindex_rag",
)


def _database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return "postgresql+psycopg://user:pass@localhost:5432/aiteachme"
    if url.startswith("postgres://"):
        url = f"postgresql://{url.removeprefix('postgres://')}"
    if url.startswith("postgresql://"):
        url = f"postgresql+psycopg://{url.removeprefix('postgresql://')}"
    return url


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    del parent_names
    if type_ == "table" and name:
        return not name.startswith(_EXTERNAL_TABLE_PREFIXES)
    return True


def include_object(object_, name: str | None, type_: str, reflected: bool, compare_to) -> bool:
    del compare_to
    if reflected and type_ == "column" and name == "embedding":
        table = getattr(object_, "table", None)
        if getattr(table, "name", None) == "retrieval_chunk":
            return False
    if reflected and type_ == "index" and name == "idx_retrieval_chunk_embedding":
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_name=include_name,
        include_object=include_object,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_name=include_name,
            include_object=include_object,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
