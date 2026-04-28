"""Validate the Render/PostgreSQL database after migration preparation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import sqlalchemy as sa

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.shared.infra.database import (  # noqa: E402
    get_engine,
    validate_postgres_runtime_schema,
)
from app.shared.infra.database.core import _SCHEMA_TABLES  # noqa: E402
from app.shared.infra.runtime import is_cloud_mode  # noqa: E402
from app.shared.infra.search.llamaindex_index import prepare_postgres_store  # noqa: E402

_REQUIRED_UNIQUE_CONSTRAINTS = (
    ("retrieval_chunk", "uq_retrieval_chunk_file_id_chunk_index"),
    ("retrieval_chunk", "uq_retrieval_chunk_subject_digest_chunk_uid"),
    ("knowledge_unit", "uq_unit_subject_type_name"),
    ("knowledge_edge", "uq_edge_subject_src_tgt_type"),
    ("question_template", "uq_template_subject_stem"),
    ("exam_paper_item", "uq_paper_item_order"),
)
_REQUIRED_UNIQUE_INDEXES = (
    "ix_user_username",
    "ix_user_email",
    "ix_user_device_key",
    "ix_subject_slug",
    "ix_raw_file_id",
    "uq_user_knowledge_state_node",
)
_REQUIRED_FOREIGN_KEYS = (
    ("subject", "user_id", "user"),
    ("retrieval_chunk", "subject", "subject"),
    ("retrieval_chunk", "file_id", "raw_file"),
    ("knowledge_edge", "source_node_id", "knowledge_unit"),
    ("knowledge_edge", "target_node_id", "knowledge_unit"),
    ("exam_paper_item", "exam_paper_id", "exam_paper"),
    ("exam_paper_item", "question_template_id", "question_template"),
    ("chat_message", "session_id", "chat_session"),
    ("chat_message", "source_chunk_id", "retrieval_chunk"),
)


def _constraint_exists(connection: sa.Connection, table_name: str, constraint_name: str) -> bool:
    row = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            WHERE n.nspname = current_schema()
              AND t.relname = :table_name
              AND c.conname = :constraint_name
            """
        ),
        {"table_name": table_name, "constraint_name": constraint_name},
    ).first()
    return row is not None


def _index_exists(connection: sa.Connection, index_name: str) -> bool:
    row = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM pg_class i
            JOIN pg_namespace n ON n.oid = i.relnamespace
            WHERE n.nspname = current_schema()
              AND i.relkind = 'i'
              AND i.relname = :index_name
            """
        ),
        {"index_name": index_name},
    ).first()
    return row is not None


def _foreign_key_exists(
    connection: sa.Connection,
    *,
    table_name: str,
    column_name: str,
    referenced_table: str,
) -> bool:
    row = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_namespace n ON n.oid = t.relnamespace
            JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(c.conkey)
            JOIN pg_class rt ON rt.oid = c.confrelid
            WHERE n.nspname = current_schema()
              AND c.contype = 'f'
              AND t.relname = :table_name
              AND a.attname = :column_name
              AND rt.relname = :referenced_table
            """
        ),
        {
            "table_name": table_name,
            "column_name": column_name,
            "referenced_table": referenced_table,
        },
    ).first()
    return row is not None


def _partial_index_is_correct(connection: sa.Connection) -> bool:
    row = connection.execute(
        sa.text(
            """
            SELECT pg_get_indexdef(i.oid)
            FROM pg_class i
            JOIN pg_namespace n ON n.oid = i.relnamespace
            WHERE n.nspname = current_schema()
              AND i.relname = 'uq_user_knowledge_state_node'
            """
        )
    ).first()
    return row is not None and "knowledge_unit_id IS NOT NULL" in str(row[0])


def _collect_deep_schema_errors(connection: sa.Connection) -> list[str]:
    errors: list[str] = []

    for table in _SCHEMA_TABLES:
        if not connection.execute(
            sa.text(
                """
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = current_schema()
                  AND table_name = :table_name
                """
            ),
            {"table_name": table.name},
        ).first():
            errors.append(f"missing table: {table.name}")

    for table_name, constraint_name in _REQUIRED_UNIQUE_CONSTRAINTS:
        if not _constraint_exists(connection, table_name, constraint_name):
            errors.append(f"missing constraint: {table_name}.{constraint_name}")

    for index_name in _REQUIRED_UNIQUE_INDEXES:
        if not _index_exists(connection, index_name):
            errors.append(f"missing unique index: {index_name}")

    if _index_exists(connection, "uq_user_knowledge_state_node") and not _partial_index_is_correct(connection):
        errors.append("partial index uq_user_knowledge_state_node is missing its WHERE clause")

    for table_name, column_name, referenced_table in _REQUIRED_FOREIGN_KEYS:
        if not _foreign_key_exists(
            connection,
            table_name=table_name,
            column_name=column_name,
            referenced_table=referenced_table,
        ):
            errors.append(
                f"missing foreign key: {table_name}.{column_name} -> {referenced_table}"
            )

    return errors


def main() -> int:
    if not is_cloud_mode():
        print("check_cloud_db requires APP_MODE=cloud.", file=sys.stderr)
        return 2

    errors = validate_postgres_runtime_schema()
    engine = get_engine()
    with engine.connect() as connection:
        errors.extend(_collect_deep_schema_errors(connection))

    try:
        prepare_postgres_store()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"LlamaIndex PGVectorStore initialization failed: {exc}")

    if errors:
        print("cloud database validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("cloud database validation passed")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("APP_MODE", "cloud")
    raise SystemExit(main())
