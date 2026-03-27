"""Raw file model definition."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.enums import IngestStatus, TaskStatus
from app.utils.time import utcnow


class RawFile(SQLModel, table=True):
    """User-uploaded source material."""

    __tablename__ = "raw_file"

    id: int | None = Field(default=None, primary_key=True)
    uid: str = Field(index=True, unique=True)
    subject: str = Field(index=True)
    filename: str
    filetype: str
    file_path: str
    markdown_path: str | None = None
    markdown_content: str = ""
    asset_dir: str | None = None
    storage_uri: str | None = None
    markdown_uri: str | None = None
    asset_manifest_json: str = Field(default="[]")
    user_note: str | None = None
    status: str = Field(default=TaskStatus.PENDING.value, index=True)
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    content_hash: str | None = Field(default=None)
    file_size_bytes: int | None = Field(default=None)
    estimated_pages: int | None = Field(default=None)
    detected_language: str | None = Field(default=None)
    detected_discipline: str | None = Field(default=None, index=True)
    detected_sub_discipline: str | None = Field(default=None)
    detected_content_type: str | None = Field(default=None)
    classification_result: str | None = Field(default=None)
    quality_score: float | None = Field(default=None)
    parse_metadata: str | None = Field(default=None)
    material_profile_json: str = Field(default="{}")
    parse_metadata_json: str = Field(default="{}")
    image_count: int | None = Field(default=None)
    ingest_status: str = Field(default=IngestStatus.PENDING.value, index=True)
    current_step: str | None = Field(default=None, index=True)
