"""Move question knowledge coverage into a relation table."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260426_0008"
down_revision = "20260426_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "question_knowledge_unit_link",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_template_id", sa.Integer(), nullable=True),
        sa.Column("exam_paper_item_id", sa.Integer(), nullable=True),
        sa.Column("knowledge_unit_id", sa.Integer(), nullable=False),
        sa.Column("coverage_weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.CheckConstraint(
            "(question_template_id IS NOT NULL AND exam_paper_item_id IS NULL) "
            "OR (question_template_id IS NULL AND exam_paper_item_id IS NOT NULL)",
            name="ck_question_link_one_question_ref",
        ),
        sa.ForeignKeyConstraint(["question_template_id"], ["question_template.id"]),
        sa.ForeignKeyConstraint(["exam_paper_item_id"], ["exam_paper_item.id"]),
        sa.ForeignKeyConstraint(["knowledge_unit_id"], ["knowledge_unit.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_template_id", "knowledge_unit_id", name="uq_question_template_knowledge_unit"),
        sa.UniqueConstraint("exam_paper_item_id", "knowledge_unit_id", name="uq_exam_paper_item_knowledge_unit"),
    )
    op.create_index("ix_question_knowledge_unit_link_question_template_id", "question_knowledge_unit_link", ["question_template_id"])
    op.create_index("ix_question_knowledge_unit_link_exam_paper_item_id", "question_knowledge_unit_link", ["exam_paper_item_id"])
    op.create_index("ix_question_knowledge_unit_link_knowledge_unit_id", "question_knowledge_unit_link", ["knowledge_unit_id"])

    op.execute(
        """
        INSERT INTO question_knowledge_unit_link
            (question_template_id, exam_paper_item_id, knowledge_unit_id, coverage_weight, created_at, updated_at)
        SELECT
            qt.id,
            NULL,
            (ref.value->>'knowledge_unit_id')::integer,
            COALESCE(NULLIF(ref.value->>'coverage_weight', '')::double precision, 1.0),
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM question_template qt
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN qt.knowledge_unit_refs_json IS NULL OR qt.knowledge_unit_refs_json = ''
                THEN '[]'::jsonb
                ELSE qt.knowledge_unit_refs_json::jsonb
            END
        ) AS ref(value)
        WHERE (ref.value->>'knowledge_unit_id') ~ '^[0-9]+$'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO question_knowledge_unit_link
            (question_template_id, exam_paper_item_id, knowledge_unit_id, coverage_weight, created_at, updated_at)
        SELECT qt.id, NULL, qt.knowledge_unit_id, 1.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM question_template qt
        WHERE qt.knowledge_unit_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO question_knowledge_unit_link
            (question_template_id, exam_paper_item_id, knowledge_unit_id, coverage_weight, created_at, updated_at)
        SELECT
            NULL,
            item.id,
            (ref.value->>'knowledge_unit_id')::integer,
            COALESCE(NULLIF(ref.value->>'coverage_weight', '')::double precision, 1.0),
            CURRENT_TIMESTAMP,
            CURRENT_TIMESTAMP
        FROM exam_paper_item item
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
                WHEN item.knowledge_unit_refs_json IS NULL OR item.knowledge_unit_refs_json = ''
                THEN '[]'::jsonb
                ELSE item.knowledge_unit_refs_json::jsonb
            END
        ) AS ref(value)
        WHERE (ref.value->>'knowledge_unit_id') ~ '^[0-9]+$'
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO question_knowledge_unit_link
            (question_template_id, exam_paper_item_id, knowledge_unit_id, coverage_weight, created_at, updated_at)
        SELECT NULL, item.id, item.knowledge_unit_id, 1.0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM exam_paper_item item
        WHERE item.knowledge_unit_id IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )

    op.drop_constraint("uq_template_course_node_stem", "question_template", type_="unique")
    op.create_unique_constraint("uq_template_course_stem", "question_template", ["course", "stem_hash"])
    op.execute(
        sa.text(
            "ALTER TABLE question_template DROP COLUMN knowledge_unit_refs_json "
            "/* atm-allow-destructive-ddl: copied into question_knowledge_unit_link */"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE question_template DROP COLUMN knowledge_unit_id "
            "/* atm-allow-destructive-ddl: copied into question_knowledge_unit_link */"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE exam_paper_item DROP COLUMN knowledge_unit_refs_json "
            "/* atm-allow-destructive-ddl: copied into question_knowledge_unit_link */"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE exam_paper_item DROP COLUMN knowledge_unit_id "
            "/* atm-allow-destructive-ddl: copied into question_knowledge_unit_link */"
        )
    )


def downgrade() -> None:
    op.add_column("question_template", sa.Column("knowledge_unit_id", sa.Integer(), nullable=True))
    op.add_column("question_template", sa.Column("knowledge_unit_refs_json", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("exam_paper_item", sa.Column("knowledge_unit_id", sa.Integer(), nullable=True))
    op.add_column("exam_paper_item", sa.Column("knowledge_unit_refs_json", sa.Text(), nullable=False, server_default="[]"))

    op.execute(
        """
        UPDATE question_template qt
        SET
            knowledge_unit_id = first_link.knowledge_unit_id,
            knowledge_unit_refs_json = COALESCE(link_payload.refs_json, '[]')
        FROM LATERAL (
            SELECT ql.knowledge_unit_id
            FROM question_knowledge_unit_link ql
            WHERE ql.question_template_id = qt.id
            ORDER BY ql.coverage_weight DESC, ql.id
            LIMIT 1
        ) first_link,
        LATERAL (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'knowledge_unit_id', ql.knowledge_unit_id,
                    'coverage_weight', ql.coverage_weight
                )
                ORDER BY ql.coverage_weight DESC, ql.id
            )::text AS refs_json
            FROM question_knowledge_unit_link ql
            WHERE ql.question_template_id = qt.id
        ) link_payload
        """
    )
    op.execute(
        """
        UPDATE exam_paper_item item
        SET
            knowledge_unit_id = first_link.knowledge_unit_id,
            knowledge_unit_refs_json = COALESCE(link_payload.refs_json, '[]')
        FROM LATERAL (
            SELECT ql.knowledge_unit_id
            FROM question_knowledge_unit_link ql
            WHERE ql.exam_paper_item_id = item.id
            ORDER BY ql.coverage_weight DESC, ql.id
            LIMIT 1
        ) first_link,
        LATERAL (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'knowledge_unit_id', ql.knowledge_unit_id,
                    'coverage_weight', ql.coverage_weight
                )
                ORDER BY ql.coverage_weight DESC, ql.id
            )::text AS refs_json
            FROM question_knowledge_unit_link ql
            WHERE ql.exam_paper_item_id = item.id
        ) link_payload
        """
    )

    op.drop_constraint("uq_template_course_stem", "question_template", type_="unique")
    op.create_unique_constraint("uq_template_course_node_stem", "question_template", ["course", "knowledge_unit_id", "stem_hash"])
    op.drop_table("question_knowledge_unit_link")
