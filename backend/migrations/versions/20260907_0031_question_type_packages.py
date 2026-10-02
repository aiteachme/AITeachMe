"""Add course question-type package imports, versions, and assets."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260907_0031"
down_revision = "20260828_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "question_type_registry",
        sa.Column("status", sa.String(), server_default="active", nullable=False),
    )
    op.create_index(
        "ix_question_type_registry_status",
        "question_type_registry",
        ["status"],
    )

    op.create_table(
        "question_type_package_version",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("registry_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("package_key", sa.String(), nullable=False),
        sa.Column("type_key", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("package_hash", sa.String(), nullable=False),
        sa.Column("source_filename", sa.String(), server_default="", nullable=False),
        sa.Column("compiled_definition_json", sa.Text(), nullable=False),
        sa.Column("public_preview_json", sa.Text(), nullable=False),
        sa.Column("profile_eligible", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["registry_id"], ["question_type_registry.id"]),
        sa.ForeignKeyConstraint(["course_id"], ["course.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.UniqueConstraint(
            "registry_id",
            "version",
            name="uq_question_type_package_registry_version",
        ),
        sa.UniqueConstraint(
            "course_id",
            "package_key",
            "version",
            name="uq_question_type_package_course_key_version",
        ),
    )
    for column in (
        "registry_id",
        "course_id",
        "user_id",
        "package_key",
        "type_key",
        "package_hash",
        "profile_eligible",
        "is_current",
    ):
        op.create_index(
            f"ix_question_type_package_version_{column}",
            "question_type_package_version",
            [column],
        )
    op.create_index(
        "uq_question_type_package_current_registry",
        "question_type_package_version",
        ["registry_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
        sqlite_where=sa.text("is_current = 1"),
    )

    op.create_table(
        "question_type_package_asset",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("package_version_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("content_base64", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["package_version_id"],
            ["question_type_package_version.id"],
        ),
        sa.ForeignKeyConstraint(["course_id"], ["course.id"]),
        sa.UniqueConstraint(
            "package_version_id",
            "path",
            name="uq_question_type_package_asset_path",
        ),
    )
    for column in ("package_version_id", "course_id", "sha256"):
        op.create_index(
            f"ix_question_type_package_asset_{column}",
            "question_type_package_asset",
            [column],
        )

    op.create_table(
        "question_type_package_import",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("course_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("original_filename", sa.String(), nullable=False),
        sa.Column("status", sa.String(), server_default="valid", nullable=False),
        sa.Column("package_key", sa.String(), server_default="", nullable=False),
        sa.Column("type_key", sa.String(), server_default="", nullable=False),
        sa.Column("version", sa.String(), server_default="", nullable=False),
        sa.Column("package_hash", sa.String(), server_default="", nullable=False),
        sa.Column("public_preview_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("compiled_definition_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("archive_base64", sa.Text(), server_default="", nullable=False),
        sa.Column("errors_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("warnings_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("installed_version_id", sa.Integer(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["course.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
    )
    for column in (
        "course_id",
        "user_id",
        "status",
        "package_key",
        "type_key",
        "package_hash",
        "installed_version_id",
        "expires_at",
    ):
        op.create_index(
            f"ix_question_type_package_import_{column}",
            "question_type_package_import",
            [column],
        )
    op.create_index(
        "ix_question_type_package_import_owner_expiry",
        "question_type_package_import",
        ["course_id", "user_id", "expires_at"],
    )


def downgrade() -> None:
    op.drop_table("question_type_package_import")
    op.drop_table("question_type_package_asset")
    op.drop_table("question_type_package_version")
    op.drop_index("ix_question_type_registry_status", table_name="question_type_registry")
    op.drop_column("question_type_registry", "status")
