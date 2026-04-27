from __future__ import annotations

import ast
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


def test_migration_sql_guard_allows_reviewed_marker() -> None:
    from scripts.check_migration_sql import find_dangerous_sql

    findings = find_dangerous_sql(
        "DROP TABLE old_settings /* atm-allow-destructive-ddl: copied before drop */"
    )

    assert findings == []


def test_alembic_has_single_head_revision() -> None:
    pytest.importorskip("alembic")
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    backend_root = Path(__file__).resolve().parents[1]
    script = ScriptDirectory.from_config(Config(str(backend_root / "alembic.ini")))

    assert script.get_current_head() == "20260427_0011"


def _load_revision_metadata() -> dict[str, tuple[str | tuple[str, ...] | None, Path]]:
    versions_dir = Path(__file__).resolve().parents[1] / "migrations" / "versions"
    metadata: dict[str, tuple[str | tuple[str, ...] | None, Path]] = {}
    for path in sorted(versions_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision: str | None = None
        down_revision: str | tuple[str, ...] | None = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "revision" in targets:
                value = ast.literal_eval(node.value)
                revision = str(value)
            if "down_revision" in targets:
                value = ast.literal_eval(node.value)
                if value is None or isinstance(value, str):
                    down_revision = value
                elif isinstance(value, tuple):
                    down_revision = tuple(str(item) for item in value)
                else:
                    raise AssertionError(f"Unsupported down_revision in {path.name}: {value!r}")
        assert revision, f"Missing revision in {path.name}"
        assert revision not in metadata, f"Duplicate Alembic revision {revision!r} in {path.name} and {metadata[revision][1].name}"
        metadata[revision] = (down_revision, path)
    return metadata


def test_migration_revisions_are_unique_and_have_one_head() -> None:
    metadata = _load_revision_metadata()
    referenced: set[str] = set()
    base_revisions: list[str] = []

    for revision, (down_revision, _path) in metadata.items():
        if down_revision is None:
            base_revisions.append(revision)
            continue
        parents = (down_revision,) if isinstance(down_revision, str) else down_revision
        for parent in parents:
            assert parent in metadata, f"Revision {revision!r} points to missing parent {parent!r}"
            referenced.add(parent)

    heads = set(metadata) - referenced
    assert base_revisions == ["20260421_0001"]
    assert heads == {"20260427_0011"}


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


def test_postgres_pool_config_uses_bounded_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.shared.infra.database import core

    for name in (
        "DB_POOL_SIZE",
        "DB_MAX_OVERFLOW",
        "DB_POOL_TIMEOUT",
        "DB_POOL_RECYCLE",
        "DB_POOL_USE_LIFO",
    ):
        monkeypatch.delenv(name, raising=False)

    assert core._postgres_pool_config() == {
        "pool_size": 5,
        "max_overflow": 5,
        "pool_timeout": 30,
        "pool_recycle": 1800,
        "pool_use_lifo": True,
    }

    monkeypatch.setenv("DB_POOL_SIZE", "12")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "20")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "8")
    monkeypatch.setenv("DB_POOL_RECYCLE", "600")
    monkeypatch.setenv("DB_POOL_USE_LIFO", "false")

    assert core._postgres_pool_config() == {
        "pool_size": 12,
        "max_overflow": 20,
        "pool_timeout": 8,
        "pool_recycle": 600,
        "pool_use_lifo": False,
    }

    monkeypatch.setenv("DB_POOL_SIZE", "0")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "-1")
    monkeypatch.setenv("DB_POOL_TIMEOUT", "0")
    monkeypatch.setenv("DB_POOL_RECYCLE", "1")
    monkeypatch.setenv("DB_POOL_USE_LIFO", "yes")

    assert core._postgres_pool_config() == {
        "pool_size": 1,
        "max_overflow": 0,
        "pool_timeout": 1,
        "pool_recycle": 30,
        "pool_use_lifo": True,
    }


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
