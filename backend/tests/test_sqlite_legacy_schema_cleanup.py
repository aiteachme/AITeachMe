import sqlalchemy as sa
from sqlmodel import create_engine

from app.shared.infra.database.core import (
    _apply_sqlite_additive_schema_updates,
    _drop_sqlite_legacy_schema,
    _inspect_sqlite_schema_drift,
    _json_dumps,
)


def test_drop_sqlite_legacy_schema_removes_legacy_indexes_before_columns(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE question_template (
                    id INTEGER PRIMARY KEY,
                    stem TEXT NOT NULL,
                    curriculum_version_id INTEGER
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE INDEX ix_question_template_curriculum_version_id
                ON question_template (curriculum_version_id)
                """
            )
        )

    _drop_sqlite_legacy_schema(engine)

    inspector = sa.inspect(engine)
    remaining_columns = {
        column["name"]
        for column in inspector.get_columns("question_template")
    }
    remaining_indexes = {
        index["name"]
        for index in inspector.get_indexes("question_template")
    }

    assert "curriculum_version_id" not in remaining_columns
    assert "ix_question_template_curriculum_version_id" not in remaining_indexes


def test_drop_sqlite_legacy_schema_removes_local_legacy_columns(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE chat_session (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    user_goal TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE system_settings_snapshot (
                    id TEXT PRIMARY KEY,
                    settings_hash TEXT NOT NULL,
                    settings_path TEXT NOT NULL
                )
                """
            )
        )

    _drop_sqlite_legacy_schema(engine)

    inspector = sa.inspect(engine)
    chat_session_columns = {
        column["name"]
        for column in inspector.get_columns("chat_session")
    }
    remaining_tables = set(inspector.get_table_names())

    assert "user_goal" not in chat_session_columns
    assert "system_settings_snapshot" not in remaining_tables


def test_drop_sqlite_legacy_schema_renames_email_confirmation_table(tmp_path):
    db_path = tmp_path / "legacy_email.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE email_verification_code (
                    id INTEGER PRIMARY KEY,
                    email TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    code_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    consumed_at TEXT,
                    attempt_count INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )

    _drop_sqlite_legacy_schema(engine)

    tables = set(sa.inspect(engine).get_table_names())

    assert "email_confirmation" in tables
    assert "email_verification_code" not in tables


def test_drop_sqlite_legacy_schema_moves_user_runtime_settings_into_user(tmp_path):
    db_path = tmp_path / "legacy_user_settings.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE user (
                    id TEXT PRIMARY KEY,
                    username TEXT NOT NULL,
                    profile_json TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE user_runtime_settings (
                    user_id TEXT PRIMARY KEY,
                    settings_json JSON
                )
                """
            )
        )
        connection.execute(sa.text("INSERT INTO user (id, username, profile_json) VALUES ('local', 'local', '{}')"))
        connection.execute(
            sa.text(
                """
                INSERT INTO user_runtime_settings (user_id, settings_json)
                VALUES ('local', '{"models":{"primary":"unit-test"}}')
                """
            )
        )

    _drop_sqlite_legacy_schema(engine)

    inspector = sa.inspect(engine)
    user_columns = {column["name"] for column in inspector.get_columns("user")}
    tables = set(inspector.get_table_names())
    with engine.connect() as connection:
        row = connection.execute(
            sa.text("SELECT runtime_settings_json FROM user WHERE id = 'local'")
        ).one()

    assert "runtime_settings_json" in user_columns
    assert "user_runtime_settings" not in tables
    assert row[0] == '{"models":{"primary":"unit-test"}}'


def test_drop_sqlite_legacy_schema_moves_system_snapshot_into_runtime_settings(tmp_path):
    db_path = tmp_path / "legacy_system_settings.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE system_runtime_settings (
                    id TEXT PRIMARY KEY,
                    settings_json JSON,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                CREATE TABLE system_settings_snapshot (
                    id TEXT PRIMARY KEY,
                    settings_source TEXT NOT NULL,
                    settings_hash TEXT NOT NULL,
                    settings_json JSON,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO system_runtime_settings (id, settings_json, created_at, updated_at)
                VALUES ('runtime', '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO system_settings_snapshot
                (id, settings_source, settings_hash, settings_json, created_at, updated_at)
                VALUES ('runtime', 'code defaults', 'hash-a', '{"models":{"primary":"snapshot"}}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )

    _drop_sqlite_legacy_schema(engine)

    inspector = sa.inspect(engine)
    runtime_columns = {
        column["name"]
        for column in inspector.get_columns("system_runtime_settings")
    }
    tables = set(inspector.get_table_names())
    with engine.connect() as connection:
        row = connection.execute(
            sa.text(
                """
                SELECT settings_source, settings_hash, effective_settings_json
                FROM system_runtime_settings
                WHERE id = 'runtime'
                """
            )
        ).one()

    assert {"settings_source", "settings_hash", "effective_settings_json"} <= runtime_columns
    assert "system_settings_snapshot" not in tables
    assert row == ("code defaults", "hash-a", '{"models":{"primary":"snapshot"}}')


def test_sqlite_additive_schema_updates_add_subject_text_fields(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE subject (
                    id INTEGER PRIMARY KEY,
                    user_id VARCHAR NOT NULL,
                    slug VARCHAR NOT NULL,
                    name VARCHAR NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO subject (id, user_id, slug, name)
                VALUES (1, 'local', 'subj_test', 'Test')
                """
            )
        )

    _apply_sqlite_additive_schema_updates(engine)

    inspector = sa.inspect(engine)
    subject_columns = {
        column["name"]
        for column in inspector.get_columns("subject")
    }
    with engine.connect() as connection:
        row = connection.execute(
            sa.text("SELECT description, user_intent FROM subject WHERE id = 1")
        ).one()

    assert {"description", "user_intent"} <= subject_columns
    assert row == ("", "")


def test_ensure_local_sqlite_schema_rebuilds_engine_after_drift(
    monkeypatch,
    tmp_path,
):
    from app.shared.infra.database import core

    db_path = tmp_path / "aiteachme.sqlite"
    db_path.write_text("placeholder", encoding="utf-8")

    old_engine = object()
    rebuilt_engine = object()
    calls: list[object] = []

    monkeypatch.setattr(core, "_get_db_path", lambda: db_path)
    monkeypatch.setattr(core, "_drop_sqlite_removed_schema", lambda engine: calls.append(("drop", engine)))
    monkeypatch.setattr(core, "_apply_sqlite_additive_schema_updates", lambda engine: calls.append(("additive", engine)))
    monkeypatch.setattr(
        core,
        "_inspect_sqlite_schema_drift",
        lambda engine: {
            "unexpected_tables": [],
            "missing_columns": {"user": ["runtime_settings_json"]},
            "unexpected_columns": {"chat_session": ["user_goal"]},
        },
    )
    monkeypatch.setattr(core, "is_local_mode", lambda: True)
    monkeypatch.setattr(core, "reset_runtime_state", lambda: calls.append("reset"))
    monkeypatch.setattr(core, "_remove_sqlite_files", lambda path: calls.append(("remove", path)))
    monkeypatch.setattr(core, "get_engine", lambda: rebuilt_engine)

    result = core._ensure_local_sqlite_schema(old_engine)

    assert result is rebuilt_engine
    assert calls == [
        ("drop", old_engine),
        ("additive", old_engine),
        "reset",
        ("remove", db_path),
    ]


def test_sqlite_schema_drift_allows_memory_runtime_tables(tmp_path):
    db_path = tmp_path / "runtime.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE memory_entries (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE learning_logs (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE atm_vec_chunks_dim_3 (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE atm_vec_chunks_dim_3_chunks (id INTEGER PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE atm_vec_chunks_dim_3_rowids (id INTEGER PRIMARY KEY)"))

    assert _inspect_sqlite_schema_drift(engine) is None


def test_sqlite_additive_schema_updates_add_subject_learning_context_columns(tmp_path):
    db_path = tmp_path / "legacy_subject.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")

    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE subject (
                    id INTEGER PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO subject (id, user_id, slug, name)
                VALUES (1, 'local', 'math', 'Math')
                """
            )
        )

    _apply_sqlite_additive_schema_updates(engine)

    inspector = sa.inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("subject")}
    assert {
        "learning_intent_text",
        "subject_intro_text",
        "document_summary_json",
        "llm_context_text",
    } <= columns

    with engine.connect() as connection:
        row = connection.execute(
            sa.text(
                """
                SELECT learning_intent_text, subject_intro_text, document_summary_json, llm_context_text
                FROM subject
                WHERE slug = 'math'
                """
            )
        ).one()
    assert tuple(row) == ("", "", "{}", "")


def test_database_json_serializer_keeps_unicode_readable():
    assert "\\u" not in _json_dumps({"subject": "高等数学"})
