"""Raw file and asset models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint

from app.models.enums import IngestStatus, TaskStatus
from app.utils.time import utcnow


class RawFile(SQLModel, table=True):
    """Uploaded source file and ingest state."""

    __tablename__ = "raw_file"
    __table_args__ = (
        UniqueConstraint("subject_id", "uid", name="uq_raw_file_subject_uid"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    uid: str = Field(index=True)
    original_filename: str
    file_ext: str
    mime_type: str | None = Field(default=None)
    storage_backend: str = Field(default="local")
    storage_key: str
    parsed_markdown: str = Field(default="")
    parser_used: str | None = Field(default=None)
    parse_metadata_json: str = Field(default="{}")
    parse_error_message: str | None = Field(default=None)
    classification_json: str = Field(default="{}")
    quality_score: float | None = Field(default=None)
    image_count: int = Field(default=0, ge=0)
    status: str = Field(default=TaskStatus.PENDING.value, index=True)
    ingest_status: str = Field(default=IngestStatus.PENDING.value, index=True)
    digest_current_step: str | None = Field(default=None, index=True)
    size_bytes: int | None = Field(default=None, ge=0)
    checksum_sha256: str | None = Field(default=None, index=True)
    estimated_pages: int | None = Field(default=None, ge=0)
    detected_language: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class RawFileAsset(SQLModel, table=True):
    """Extracted file asset such as image, formula crop, or appendix."""

    __tablename__ = "raw_file_asset"
    __table_args__ = (
        UniqueConstraint("raw_file_id", "asset_name", name="uq_raw_file_asset_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    raw_file_id: int = Field(foreign_key="raw_file.id", index=True)
    asset_name: str
    asset_kind: str = Field(default="image", index=True)
    storage_backend: str = Field(default="local")
    storage_key: str
    mime_type: str | None = Field(default=None)
    page_num: int | None = Field(default=None, ge=1)
    width: int | None = Field(default=None, ge=0)
    height: int | None = Field(default=None, ge=0)
    ocr_text: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
