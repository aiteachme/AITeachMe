"""Validate the Render/PostgreSQL database after migration preparation."""

from __future__ import annotations

import os
import sys
import uuid
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
from app.shared.infra.storage import get_artifact_store, run_store_sync  # noqa: E402
from app.shared.infra.storage.config import storage_is_s3  # noqa: E402
from app.shared.infra.search.llamaindex_index import prepare_postgres_store  # noqa: E402

_STORAGE_HEALTHCHECK_DATA = b"aiteachme-cloud-storage-ok"

_REQUIRED_UNIQUE_CONSTRAINTS = (
    ("retrieval_chunk", "uq_retrieval_chunk_course_file_id_chunk_index"),
    ("retrieval_chunk", "uq_retrieval_chunk_course_digest_chunk_uid"),
    ("knowledge_unit", "uq_unit_course_type_name"),
    ("knowledge_edge", "uq_edge_course_src_tgt_type"),
    ("question_template", "uq_template_course_stem"),
    ("exam_paper_item", "uq_paper_item_order"),
)
_REQUIRED_UNIQUE_INDEXES = (
    "ix_user_username",
    "ix_user_email",
    "ix_user_device_key",
    "ix_raw_file_id",
    "uq_user_knowledge_state_node",
)
_REQUIRED_FOREIGN_KEYS = (
    ("course", "user_id", "user"),
    ("retrieval_chunk", "course_id", "course"),
    ("course_file", "course_id", "course"),
    ("course_file", "file_id", "raw_file"),
    ("retrieval_chunk", "file_id", "raw_file"),
    ("knowledge_edge", "source_node_id", "knowledge_unit"),
    ("knowledge_edge", "target_node_id", "knowledge_unit"),
    ("exam_paper_item", "exam_paper_id", "exam_paper"),
    ("exam_paper_item", "question_template_id", "question_template"),
    ("chat_message", "session_id", "chat_session"),
    ("chat_message", "source_chunk_id", "retrieval_chunk"),
)
_FORBIDDEN_FOREIGN_KEYS = (
    ("raw_file", "origin_course_id", "course"),
)
_FORBIDDEN_COLUMNS = (
    ("raw_file", "course"),
    ("raw_file", "uid"),
    ("course", "slug"),
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


def _table_exists(connection: sa.Connection, table_name: str) -> bool:
    row = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = current_schema()
              AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def _column_exists(connection: sa.Connection, *, table_name: str, column_name: str) -> bool:
    row = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {"table_name": table_name, "column_name": column_name},
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
        if not _table_exists(connection, table.name):
            errors.append(f"missing table: {table.name}")
            continue
        for column in table.columns:
            if not _column_exists(connection, table_name=table.name, column_name=column.name):
                errors.append(f"missing column: {table.name}.{column.name}")

    for table_name, column_name in _FORBIDDEN_COLUMNS:
        if _column_exists(connection, table_name=table_name, column_name=column_name):
            errors.append(f"unexpected legacy column: {table_name}.{column_name}")

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

    for table_name, column_name, referenced_table in _FORBIDDEN_FOREIGN_KEYS:
        if _foreign_key_exists(
            connection,
            table_name=table_name,
            column_name=column_name,
            referenced_table=referenced_table,
        ):
            errors.append(
                f"unexpected foreign key: {table_name}.{column_name} -> {referenced_table}"
            )

    return errors


def _collect_storage_errors() -> list[str]:
    if not storage_is_s3():
        return []

    errors: list[str] = []
    test_key = f"__healthcheck/predeploy/{uuid.uuid4().hex}.txt"
    store = None
    try:
        store = get_artifact_store()
        run_store_sync(store.write_bytes, test_key, _STORAGE_HEALTHCHECK_DATA)
        read_back = run_store_sync(store.read_bytes, test_key)
        if read_back != _STORAGE_HEALTHCHECK_DATA:
            errors.append("object storage validation failed: read-back content mismatch")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"object storage validation failed: {exc}")
    finally:
        if store is not None:
            try:
                run_store_sync(store.delete, test_key)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"object storage cleanup failed: {exc}")

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

    errors.extend(_collect_storage_errors())

    if errors:
        print("cloud runtime validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("cloud runtime validation passed")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("APP_MODE", "cloud")
    raise SystemExit(main())
