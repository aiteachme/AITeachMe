"""Add question type registry.

This revision stores the built-in exam question types as system-owned seed
data so future course-specific question types can use the same registry.
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

from migrations.seed_data.question_types import BUILTIN_QUESTION_TYPE_ROWS


revision = "20260423_0002"
down_revision = "20260421_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_type_registry",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("type_key", sa.String(), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("course", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("answer_format", sa.String(), nullable=False),
        sa.Column("grading_method", sa.String(), nullable=False),
        sa.Column("option_schema_json", sa.String(), nullable=False),
        sa.Column("rubric_json", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("scope", "course", "type_key", name="uq_question_type_scope_course_key"),
    )
    op.create_index("ix_question_type_registry_type_key", "question_type_registry", ["type_key"])
    op.create_index("ix_question_type_registry_scope", "question_type_registry", ["scope"])
    op.create_index("ix_question_type_registry_course", "question_type_registry", ["course"])
    op.create_index("ix_question_type_registry_is_system", "question_type_registry", ["is_system"])
    op.create_index("ix_question_type_registry_is_active", "question_type_registry", ["is_active"])

    question_type_table = sa.table(
        "question_type_registry",
        sa.column("type_key", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("scope", sa.String()),
        sa.column("course", sa.String()),
        sa.column("description", sa.String()),
        sa.column("answer_format", sa.String()),
        sa.column("grading_method", sa.String()),
        sa.column("option_schema_json", sa.String()),
        sa.column("rubric_json", sa.String()),
        sa.column("source", sa.String()),
        sa.column("confidence", sa.Float()),
        sa.column("is_system", sa.Boolean()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    now = datetime(2026, 4, 23, tzinfo=timezone.utc)
    op.bulk_insert(
        question_type_table,
        [
            {
                **row,
                "scope": "global",
                "course": "",
                "source": "system",
                "confidence": 1.0,
                "is_system": True,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
            for row in BUILTIN_QUESTION_TYPE_ROWS
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_question_type_registry_is_active", table_name="question_type_registry")
    op.drop_index("ix_question_type_registry_is_system", table_name="question_type_registry")
    op.drop_index("ix_question_type_registry_course", table_name="question_type_registry")
    op.drop_index("ix_question_type_registry_scope", table_name="question_type_registry")
    op.drop_index("ix_question_type_registry_type_key", table_name="question_type_registry")
    op.drop_table("question_type_registry")
