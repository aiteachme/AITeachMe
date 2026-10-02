"""Add version-frozen custom question runtime data."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260912_0032"
down_revision = "20260907_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("question_template") as batch:
        batch.add_column(sa.Column("identity_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("question_type_registry_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("question_type_version_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("public_payload_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("answer_schema_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("reference_answer_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("grading_spec_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("runtime_snapshot_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("profile_eligible", sa.Boolean(), server_default=sa.true(), nullable=False))
        batch.create_foreign_key(
            "fk_question_template_type_registry",
            "question_type_registry",
            ["question_type_registry_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_question_template_type_version",
            "question_type_package_version",
            ["question_type_version_id"],
            ["id"],
        )
    op.execute("UPDATE question_template SET identity_hash = stem_hash WHERE identity_hash IS NULL")
    with op.batch_alter_table("question_template") as batch:
        batch.create_unique_constraint(
            "uq_template_course_identity",
            ["course_id", "identity_hash"],
        )
    for column in (
        "identity_hash",
        "question_type_registry_id",
        "question_type_version_id",
        "profile_eligible",
    ):
        op.create_index(f"ix_question_template_{column}", "question_template", [column])

    with op.batch_alter_table("exam_paper_item") as batch:
        batch.add_column(sa.Column("question_type_registry_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("question_type_version_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("public_payload_snapshot_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("answer_schema_snapshot_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("reference_answer_snapshot_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("grading_spec_snapshot_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("runtime_snapshot_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("profile_eligible", sa.Boolean(), server_default=sa.true(), nullable=False))
        batch.add_column(sa.Column("answer_payload_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("grading_detail_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("grading_status", sa.String(), server_default="pending", nullable=False))
        batch.add_column(sa.Column("grading_error_code", sa.String(), server_default="", nullable=False))
        batch.create_foreign_key(
            "fk_exam_paper_item_type_registry",
            "question_type_registry",
            ["question_type_registry_id"],
            ["id"],
        )
        batch.create_foreign_key(
            "fk_exam_paper_item_type_version",
            "question_type_package_version",
            ["question_type_version_id"],
            ["id"],
        )
    for column in (
        "question_type_registry_id",
        "question_type_version_id",
        "profile_eligible",
        "grading_status",
    ):
        op.create_index(f"ix_exam_paper_item_{column}", "exam_paper_item", [column])

    with op.batch_alter_table("mastery_drill_attempt") as batch:
        batch.add_column(sa.Column("answer_payload_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("grading_detail_json", sa.Text(), server_default="{}", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("mastery_drill_attempt") as batch:
        batch.drop_column("grading_detail_json")
        batch.drop_column("answer_payload_json")

    for column in (
        "grading_status",
        "profile_eligible",
        "question_type_version_id",
        "question_type_registry_id",
    ):
        op.drop_index(f"ix_exam_paper_item_{column}", table_name="exam_paper_item")
    with op.batch_alter_table("exam_paper_item") as batch:
        batch.drop_constraint("fk_exam_paper_item_type_version", type_="foreignkey")
        batch.drop_constraint("fk_exam_paper_item_type_registry", type_="foreignkey")
        for column in (
            "grading_error_code",
            "grading_status",
            "grading_detail_json",
            "answer_payload_json",
            "profile_eligible",
            "runtime_snapshot_json",
            "grading_spec_snapshot_json",
            "reference_answer_snapshot_json",
            "answer_schema_snapshot_json",
            "public_payload_snapshot_json",
            "question_type_version_id",
            "question_type_registry_id",
        ):
            batch.drop_column(column)

    for column in (
        "profile_eligible",
        "question_type_version_id",
        "question_type_registry_id",
        "identity_hash",
    ):
        op.drop_index(f"ix_question_template_{column}", table_name="question_template")
    with op.batch_alter_table("question_template") as batch:
        batch.drop_constraint("uq_template_course_identity", type_="unique")
        batch.drop_constraint("fk_question_template_type_version", type_="foreignkey")
        batch.drop_constraint("fk_question_template_type_registry", type_="foreignkey")
        for column in (
            "profile_eligible",
            "runtime_snapshot_json",
            "grading_spec_json",
            "reference_answer_json",
            "answer_schema_json",
            "public_payload_json",
            "question_type_version_id",
            "question_type_registry_id",
            "identity_hash",
        ):
            batch.drop_column(column)
