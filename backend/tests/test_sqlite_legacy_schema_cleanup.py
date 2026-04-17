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
