"""Add exam background generation metadata."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260428_0013"
down_revision = "20260427_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "exam_paper",
        sa.Column("visibility", sa.String(), nullable=False, server_default="visible"),
    )
    op.add_column(
        "exam_paper",
        sa.Column("generation_origin", sa.String(), nullable=False, server_default="user"),
    )
    op.add_column(
        "exam_paper",
        sa.Column("config_hash", sa.String(), nullable=False, server_default=""),
    )
    op.add_column(
        "exam_paper",
        sa.Column("config_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column("exam_paper", sa.Column("prepared_at", sa.DateTime(), nullable=True))
    op.add_column("exam_paper", sa.Column("claimed_at", sa.DateTime(), nullable=True))
    op.add_column("exam_paper", sa.Column("expires_at", sa.DateTime(), nullable=True))
    op.create_index("ix_exam_paper_visibility", "exam_paper", ["visibility"])
    op.create_index("ix_exam_paper_generation_origin", "exam_paper", ["generation_origin"])
    op.create_index("ix_exam_paper_config_hash", "exam_paper", ["config_hash"])
    op.create_index("ix_exam_paper_prepared_at", "exam_paper", ["prepared_at"])
    op.create_index("ix_exam_paper_claimed_at", "exam_paper", ["claimed_at"])
    op.create_index("ix_exam_paper_expires_at", "exam_paper", ["expires_at"])

    op.create_table(
        "exam_study_guide_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("exam_paper_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False, server_default="local"),
        sa.Column("status", sa.String(), nullable=False, server_default="completed"),
        sa.Column("guide_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["exam_paper_id"], ["exam_paper.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exam_paper_id", name="uq_exam_study_guide_paper"),
    )
    op.create_index("ix_exam_study_guide_cache_exam_paper_id", "exam_study_guide_cache", ["exam_paper_id"])
    op.create_index("ix_exam_study_guide_cache_subject", "exam_study_guide_cache", ["subject"])
    op.create_index("ix_exam_study_guide_cache_user_id", "exam_study_guide_cache", ["user_id"])
    op.create_index("ix_exam_study_guide_cache_status", "exam_study_guide_cache", ["status"])
    op.create_index("ix_exam_study_guide_cache_generated_at", "exam_study_guide_cache", ["generated_at"])


def downgrade() -> None:
    op.drop_index("ix_exam_study_guide_cache_generated_at", table_name="exam_study_guide_cache")
    op.drop_index("ix_exam_study_guide_cache_status", table_name="exam_study_guide_cache")
    op.drop_index("ix_exam_study_guide_cache_user_id", table_name="exam_study_guide_cache")
    op.drop_index("ix_exam_study_guide_cache_subject", table_name="exam_study_guide_cache")
    op.drop_index("ix_exam_study_guide_cache_exam_paper_id", table_name="exam_study_guide_cache")
    op.drop_table("exam_study_guide_cache")

    op.drop_index("ix_exam_paper_expires_at", table_name="exam_paper")
    op.drop_index("ix_exam_paper_claimed_at", table_name="exam_paper")
    op.drop_index("ix_exam_paper_prepared_at", table_name="exam_paper")
    op.drop_index("ix_exam_paper_config_hash", table_name="exam_paper")
    op.drop_index("ix_exam_paper_generation_origin", table_name="exam_paper")
    op.drop_index("ix_exam_paper_visibility", table_name="exam_paper")
    op.drop_column("exam_paper", "expires_at")
    op.drop_column("exam_paper", "claimed_at")
    op.drop_column("exam_paper", "prepared_at")
    op.drop_column("exam_paper", "config_snapshot_json")
    op.drop_column("exam_paper", "config_hash")
    op.drop_column("exam_paper", "generation_origin")
    op.drop_column("exam_paper", "visibility")
