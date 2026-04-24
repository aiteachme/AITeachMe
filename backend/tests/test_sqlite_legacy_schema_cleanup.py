import sqlalchemy as sa
from sqlmodel import create_engine

from app.shared.infra.database.core import _drop_sqlite_legacy_schema


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
    settings_snapshot_columns = {
        column["name"]
        for column in inspector.get_columns("system_settings_snapshot")
    }

    assert "user_goal" not in chat_session_columns
    assert "settings_path" not in settings_snapshot_columns


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
    monkeypatch.setattr(
        core,
        "_inspect_sqlite_schema_drift",
        lambda engine: {
            "unexpected_tables": [],
            "missing_columns": {"system_settings_snapshot": ["settings_source"]},
            "unexpected_columns": {"system_settings_snapshot": ["settings_path"]},
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
        "reset",
        ("remove", db_path),
    ]
