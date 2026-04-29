from __future__ import annotations

import sqlalchemy as sa

from app.shared.infra.database.core import _migrate_sqlite_course_schema


def test_course_schema_migration_drops_duplicate_legacy_columns(tmp_path) -> None:
    legacy = "sub" + "ject"
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")

    with engine.begin() as connection:
        connection.execute(sa.text(f'CREATE TABLE "{legacy}" (id TEXT PRIMARY KEY, "{legacy}_intro_text" TEXT)'))
        connection.execute(
            sa.text(f'CREATE TABLE "{legacy}_file" (id INTEGER PRIMARY KEY, "{legacy}_id" TEXT, file_id TEXT)')
        )
        connection.execute(
            sa.text(
                f'CREATE TABLE raw_file (id TEXT PRIMARY KEY, origin_{legacy}_id TEXT, origin_{legacy}_name TEXT)'
            )
        )
        connection.execute(
            sa.text(
                f'CREATE TABLE retrieval_chunk (id INTEGER PRIMARY KEY, "{legacy}" TEXT, "{legacy}_id" TEXT)'
            )
        )

    _migrate_sqlite_course_schema(engine)

    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert "course" in tables
    assert "course_file" in tables
    assert legacy not in tables
    assert f"{legacy}_file" not in tables

    columns = {
        table_name: {column["name"] for column in inspector.get_columns(table_name)}
        for table_name in ["course", "course_file", "raw_file", "retrieval_chunk"]
    }
    assert "course_intro_text" in columns["course"]
    assert "course_id" in columns["course_file"]
    assert {"origin_course_id", "origin_course_name"} <= columns["raw_file"]
    assert "course_id" in columns["retrieval_chunk"]
    assert legacy not in columns["retrieval_chunk"]
    assert f"{legacy}_id" not in columns["retrieval_chunk"]
