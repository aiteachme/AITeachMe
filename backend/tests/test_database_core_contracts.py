from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa
from sqlmodel import Session, select

import app.shared.infra.database.core as db_core
from app.models import QuestionKnowledgeUnitLink, SystemRuntimeSettings


def _file_sqlite_engine(tmp_path: Path, name: str) -> sa.Engine:
    return sa.create_engine(f"sqlite:///{tmp_path / name}")


def test_schema_drift_ignores_runtime_tables_and_reports_real_mismatches(tmp_path: Path) -> None:
    engine = _file_sqlite_engine(tmp_path, "drift.db")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE user (id TEXT PRIMARY KEY, username TEXT)"))
        connection.execute(sa.text("CREATE TABLE atm_vec_course_shadow (id INTEGER)"))
        connection.execute(sa.text("CREATE TABLE memory_entries (id INTEGER)"))
        connection.execute(sa.text("CREATE TABLE unexpected_table (id INTEGER)"))

    drift = db_core._inspect_sqlite_schema_drift(engine)

    assert drift is not None
    assert drift["unexpected_tables"] == ["unexpected_table"]
    assert "user" in drift["missing_columns"]
    assert "runtime_settings_json" in drift["missing_columns"]["user"]
    assert "atm_vec_course_shadow" not in drift["unexpected_tables"]
    assert "memory_entries" not in drift["unexpected_tables"]


def test_sqlite_question_link_migration_normalizes_legacy_refs(tmp_path: Path) -> None:
    engine = _file_sqlite_engine(tmp_path, "question-links.db")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE question_template (
                    id INTEGER PRIMARY KEY,
                    knowledge_unit_id INTEGER,
                    knowledge_unit_refs_json TEXT
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE exam_paper_item (
                    id INTEGER PRIMARY KEY,
                    knowledge_unit_id INTEGER,
                    knowledge_unit_refs_json TEXT
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO question_template (id, knowledge_unit_id, knowledge_unit_refs_json)
                VALUES (1, 7, NULL)
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO exam_paper_item (id, knowledge_unit_id, knowledge_unit_refs_json)
                VALUES (2, 9, 'not-json')
                """
            )
        )

    db_core._migrate_sqlite_question_knowledge_links(engine)

    with Session(engine) as session:
        links = session.exec(select(QuestionKnowledgeUnitLink).order_by(QuestionKnowledgeUnitLink.id)).all()

    assert [(link.question_template_id, link.exam_paper_item_id, link.knowledge_unit_id, link.coverage_weight) for link in links] == [
        (1, None, 7, 1.0),
        (None, 2, 9, 1.0),
    ]
    assert db_core._normalize_legacy_question_refs(
        '[{"knowledge_unit_id": 8, "coverage_weight": 0.75}, {"knowledge_unit_id": 8}]',
        fallback_unit_id=7,
    ) == [{"knowledge_unit_id": 8, "coverage_weight": 0.75}]


def test_removed_schema_migrations_preserve_user_and_system_settings(tmp_path: Path) -> None:
    engine = _file_sqlite_engine(tmp_path, "removed-schema.db")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE user (
                    id TEXT PRIMARY KEY,
                    username TEXT,
                    email TEXT,
                    hashed_password TEXT,
                    is_active BOOLEAN,
                    is_superuser BOOLEAN,
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE user_runtime_settings (
                    user_id TEXT PRIMARY KEY,
                    settings_json TEXT
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE system_runtime_settings (
                    id TEXT PRIMARY KEY,
                    settings_json JSON NOT NULL DEFAULT '{}',
                    created_at DATETIME,
                    updated_at DATETIME
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE system_settings_snapshot (
                    id TEXT PRIMARY KEY,
                    settings_json TEXT,
                    settings_source TEXT,
                    settings_hash TEXT
                )
                """
            )
        )
        connection.execute(sa.text("INSERT INTO user (id, username) VALUES ('u1', 'u1')"))
        connection.execute(sa.text("INSERT INTO user_runtime_settings (user_id, settings_json) VALUES ('u1', '{\"theme\":\"dark\"}')"))
        connection.execute(sa.text("INSERT INTO system_runtime_settings (id, settings_json) VALUES ('runtime', '{}')"))
        connection.execute(
            sa.text(
                "INSERT INTO system_settings_snapshot (id, settings_json, settings_source, settings_hash) "
                "VALUES ('runtime', '{\"models\":{\"primary\":\"test\"}}', 'project', 'hash-1')"
            )
        )

    db_core._drop_sqlite_removed_schema(engine)

    inspector = sa.inspect(engine)
    assert "user_runtime_settings" not in set(inspector.get_table_names())
    assert "system_settings_snapshot" not in set(inspector.get_table_names())

    with engine.connect() as connection:
        user_runtime = connection.execute(
            sa.text("SELECT runtime_settings_json FROM user WHERE id = 'u1'")
        ).scalar_one()
        snapshot = connection.execute(
            sa.text(
                "SELECT settings_source, settings_hash, effective_settings_json "
                "FROM system_runtime_settings WHERE id = 'runtime'"
            )
        ).mappings().one()

    assert json.loads(user_runtime) == {"theme": "dark"}
    assert snapshot["settings_source"] == "project"
    assert snapshot["settings_hash"] == "hash-1"
    assert json.loads(snapshot["effective_settings_json"]) == {"models": {"primary": "test"}}


def test_confirmed_build_plan_migration_embeds_plan_in_planner_session(tmp_path: Path) -> None:
    engine = _file_sqlite_engine(tmp_path, "confirmed-plan.db")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE chat_session (
                    id TEXT PRIMARY KEY,
                    course_id TEXT,
                    user_id TEXT,
                    source TEXT,
                    meta_json TEXT,
                    updated_at TEXT,
                    last_message_at TEXT
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE confirmed_build_plan (
                    id TEXT PRIMARY KEY,
                    course_id TEXT,
                    planner_session_id TEXT,
                    user_id TEXT,
                    status TEXT,
                    user_prompt TEXT,
                    digest_mode TEXT,
                    selected_file_ids_json TEXT,
                    chapter_plan_json TEXT,
                    build_constraints_json TEXT,
                    plan_summary TEXT,
                    plan_json TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO chat_session (id, course_id, user_id, source, meta_json, updated_at, last_message_at)
                VALUES ('session-1', 'course_math00000000', 'user-1', 'build_planner', '{}', '2026-01-01', '2026-01-01')
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO confirmed_build_plan (
                    id, course_id, planner_session_id, user_id, status, user_prompt, digest_mode,
                    selected_file_ids_json, chapter_plan_json, build_constraints_json, plan_summary,
                    plan_json, created_at, updated_at
                )
                VALUES (
                    'plan-1', 'course_math00000000', 'session-1', 'user-1', 'confirmed',
                    'build notes', 'systematic', '["file-1"]', '[{"title":"Chapter"}]',
                    '{"tone":"concise"}', 'summary', '{"course_id":"course_math00000000"}',
                    '2026-01-01', '2026-01-02'
                )
                """
            )
        )

    db_core._migrate_sqlite_confirmed_build_plans(engine)

    with engine.connect() as connection:
        meta_json = connection.execute(sa.text("SELECT meta_json FROM chat_session WHERE id = 'session-1'")).scalar_one()

    meta = json.loads(meta_json)
    assert meta["confirmed_plan_id"] == "plan-1"
    assert meta["confirmed_plan"]["selected_file_ids"] == ["file-1"]
    assert meta["confirmed_plan"]["chapters"] == [{"title": "Chapter"}]
    assert meta["confirmed_plan"]["plan"] == "summary"
    assert meta["confirmed_plan"]["build_constraints"] == {"tone": "concise"}


def test_additive_schema_updates_backfill_parse_signatures_and_indexes(tmp_path: Path) -> None:
    engine = _file_sqlite_engine(tmp_path, "additive-schema.db")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE raw_file (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    content_hash TEXT,
                    file_size_bytes INTEGER,
                    filetype TEXT,
                    status TEXT,
                    created_at TEXT,
                    parse_request_signature TEXT
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO raw_file (id, user_id, content_hash, file_size_bytes, filetype, status, created_at, parse_request_signature)
                VALUES
                    ('file-1', 'u1', 'hash', 10, 'pdf', 'ready', '2026-01-01', ''),
                    ('file-2', 'u1', 'hash', 10, 'pdf', 'ready', '2026-01-02', NULL),
                    ('file-3', 'u1', 'hash', 10, 'pdf', 'failed', '2026-01-03', '')
                """
            )
        )

    db_core._backfill_sqlite_raw_file_parse_signatures(engine)
    db_core._apply_sqlite_additive_index_updates(engine)

    with engine.connect() as connection:
        rows = dict(connection.execute(sa.text("SELECT id, parse_request_signature FROM raw_file")).all())
        indexes = {index["name"] for index in sa.inspect(connection).get_indexes("raw_file")}

    assert rows["file-1"] == "default"
    assert rows["file-2"] == "legacy:file-2"
    assert rows["file-3"] == "default"
    assert "ix_raw_file_user_hash_size_type" in indexes
    assert "uq_raw_file_user_hash_size_type_signature_active" in indexes


def test_vector_table_helpers_and_pool_config(monkeypatch, tmp_path: Path) -> None:
    engine = _file_sqlite_engine(tmp_path, "vector.db")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE vec_table (embedding FLOAT[1536])"))
        assert db_core.vector_table_exists(connection, "vec_table") is True
        assert db_core.vector_table_exists(connection, "missing") is False
        assert db_core.get_vector_table_dim(connection, "vec_table") == 1536
        assert db_core.get_vector_table_dim(connection, "missing") is None

    monkeypatch.setattr(db_core, "get_env_int", lambda name, default: {"DB_POOL_SIZE": 100, "DB_MAX_OVERFLOW": -1, "DB_POOL_TIMEOUT": 0, "DB_POOL_RECYCLE": 10}.get(name, default))
    monkeypatch.setattr(db_core, "get_env_bool", lambda name, default: False)

    assert db_core._postgres_pool_config() == {
        "pool_size": 50,
        "max_overflow": 0,
        "pool_timeout": 1,
        "pool_recycle": 30,
        "pool_use_lifo": False,
    }


def test_settings_snapshot_and_override_refresh(monkeypatch, tmp_path: Path) -> None:
    engine = _file_sqlite_engine(tmp_path, "settings.db")
    SQLModel = db_core.SQLModel
    SQLModel.metadata.create_all(engine, tables=[SystemRuntimeSettings.__table__])
    settings = SimpleNamespace(
        model_dump=lambda mode: {
            "models": {"primary": "gpt-test"},
            "env": {"LLM_API_KEY": "secret"},
        }
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(db_core, "describe_project_settings_source", lambda: "project-settings.yaml")
    monkeypatch.setattr(db_core, "split_runtime_settings_payload", lambda payload: ({"models": payload.get("models", {})}, {"LLM_API_KEY": "secret"}))
    monkeypatch.setattr(db_core, "set_runtime_env_overrides", lambda overrides: captured.setdefault("env", overrides))
    monkeypatch.setattr(db_core, "set_system_settings_override", lambda payload: captured.setdefault("settings", payload))

    db_core._upsert_settings_snapshot(engine, settings)
    with Session(engine) as session:
        row = session.get(SystemRuntimeSettings, "runtime")
        assert row is not None
        row.settings_json = {"models": {"primary": "override"}}
        session.add(row)
        session.commit()

    db_core._refresh_system_settings_override(engine)

    assert captured["env"] == {"LLM_API_KEY": "secret"}
    assert captured["settings"] == {"models": {"primary": "override"}}
