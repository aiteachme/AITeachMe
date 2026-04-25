from __future__ import annotations

from pathlib import Path

import pytest


def test_migration_sql_guard_flags_destructive_ddl() -> None:
    from scripts.check_migration_sql import find_dangerous_sql

    findings = find_dangerous_sql(
        """
        CREATE TABLE example (id integer);
        DROP TABLE example;
        ALTER TABLE example DROP COLUMN name;
        """
    )

    assert any("DROP TABLE" in finding for finding in findings)
    assert any("DROP COLUMN" in finding for finding in findings)


def test_migration_sql_guard_allows_safe_upgrade_sql() -> None:
    from scripts.check_migration_sql import find_dangerous_sql

    findings = find_dangerous_sql(
        """
        CREATE EXTENSION IF NOT EXISTS vector;
        CREATE TABLE example (id integer);
        CREATE INDEX ix_example_id ON example (id);
        """
    )

    assert findings == []


def test_alembic_has_single_head_revision() -> None:
    pytest.importorskip("alembic")
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_root = Path(__file__).resolve().parents[1]
    script = ScriptDirectory.from_config(Config(str(backend_root / "alembic.ini")))

    assert script.get_current_head() == "20260425_0004"


def test_cloud_postgres_init_does_not_create_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.shared.infra.database import core

    class Settings:
        embedding_dim = 1024
        normalized_embedding_model = "text-embedding-v4"

    engine = object()

    def fail_create_all(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("cloud startup must not call SQLModel.metadata.create_all")

    monkeypatch.setattr(core, "get_engine", lambda: engine)
    monkeypatch.setattr(core, "assert_postgres_runtime_schema_ready", lambda **kwargs: None)
    monkeypatch.setattr(core, "_refresh_system_settings_override", lambda *args, **kwargs: None)
    monkeypatch.setattr(core, "_upsert_settings_snapshot", lambda *args, **kwargs: None)
    monkeypatch.setattr(core.SQLModel.metadata, "create_all", fail_create_all)

    core._init_postgres_db(Settings())


def test_cloud_postgres_schema_not_ready_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.shared.infra.database import core

    monkeypatch.setattr(
        core,
        "validate_postgres_runtime_schema",
        lambda engine=None, settings=None: ["alembic revision mismatch"],
    )

    with pytest.raises(RuntimeError, match="PostgreSQL schema is not ready"):
        core.assert_postgres_runtime_schema_ready()


def test_cloud_runtime_schema_no_longer_requires_global_embedding_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.shared.infra.database import core

    connection = object()

    monkeypatch.setattr(core, "_get_alembic_head_revision", lambda: "head")
    monkeypatch.setattr(core, "_get_postgres_alembic_revision", lambda conn: "head")
    monkeypatch.setattr(core, "_postgres_extension_exists", lambda conn, extension_name: True)
    monkeypatch.setattr(core, "_postgres_table_exists", lambda conn, table_name: True)

    errors = core._collect_postgres_runtime_schema_errors(connection, settings=object())

    assert errors == []


def test_retrieval_chunk_unique_constraints_are_named() -> None:
    from app.models.knowledge import RetrievalChunk

    names = {
        constraint.name
        for constraint in RetrievalChunk.__table__.constraints
        if getattr(constraint, "name", None)
    }

    assert "uq_retrieval_chunk_document_id_chunk_index" in names
    assert "uq_retrieval_chunk_subject_digest_chunk_uid" in names
