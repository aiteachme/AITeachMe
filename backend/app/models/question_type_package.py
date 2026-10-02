"""Persistent models for declarative course question-type packages."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class QuestionTypePackageImport(SQLModel, table=True):
    """Short-lived validated upload awaiting an explicit install action."""

    __tablename__ = "question_type_package_import"
    __table_args__ = (
        sa.Index(
            "ix_question_type_package_import_owner_expiry",
            "course_id",
            "user_id",
            "expires_at",
        ),
    )

    id: str = Field(primary_key=True)
    course_id: str = Field(foreign_key="course.id", index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    original_filename: str
    status: str = Field(default="valid", index=True)
    package_key: str = Field(default="", index=True)
    type_key: str = Field(default="", index=True)
    version: str = Field(default="")
    package_hash: str = Field(default="", index=True)
    public_preview_json: str = Field(
        default="{}",
        sa_column=sa.Column(sa.Text(), nullable=False, default="{}"),
    )
    compiled_definition_json: str = Field(
        default="{}",
        sa_column=sa.Column(sa.Text(), nullable=False, default="{}"),
    )
    archive_base64: str = Field(
        default="",
        sa_column=sa.Column(sa.Text(), nullable=False, default=""),
    )
    errors_json: str = Field(
        default="[]",
        sa_column=sa.Column(sa.Text(), nullable=False, default="[]"),
    )
    warnings_json: str = Field(
        default="[]",
        sa_column=sa.Column(sa.Text(), nullable=False, default="[]"),
    )
    installed_version_id: int | None = Field(default=None, index=True)
    expires_at: datetime = Field(index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class QuestionTypePackageVersion(SQLModel, table=True):
    """Immutable compiled definition installed for one course registry entry."""

    __tablename__ = "question_type_package_version"
    __table_args__ = (
        UniqueConstraint(
            "registry_id",
            "version",
            name="uq_question_type_package_registry_version",
        ),
        UniqueConstraint(
            "course_id",
            "package_key",
            "version",
            name="uq_question_type_package_course_key_version",
        ),
        sa.Index(
            "uq_question_type_package_current_registry",
            "registry_id",
            unique=True,
            postgresql_where=sa.text("is_current = true"),
            sqlite_where=sa.text("is_current = 1"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    registry_id: int = Field(foreign_key="question_type_registry.id", index=True)
    course_id: str = Field(foreign_key="course.id", index=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    package_key: str = Field(index=True)
    type_key: str = Field(index=True)
    version: str
    package_hash: str = Field(index=True)
    source_filename: str = Field(default="")
    compiled_definition_json: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    public_preview_json: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    profile_eligible: bool = Field(default=False, index=True)
    is_current: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)


class QuestionTypePackageAsset(SQLModel, table=True):
    """Validated binary asset belonging to an immutable package version."""

    __tablename__ = "question_type_package_asset"
    __table_args__ = (
        UniqueConstraint(
            "package_version_id",
            "path",
            name="uq_question_type_package_asset_path",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    package_version_id: int = Field(
        foreign_key="question_type_package_version.id",
        index=True,
    )
    course_id: str = Field(foreign_key="course.id", index=True)
    path: str
    role: str
    media_type: str
    sha256: str = Field(index=True)
    size_bytes: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    content_base64: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    created_at: datetime = Field(default_factory=utcnow)


__all__ = [
    "QuestionTypePackageAsset",
    "QuestionTypePackageImport",
    "QuestionTypePackageVersion",
]
