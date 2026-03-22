"""File API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.enums import TaskStatusValue


class FileAssetItem(BaseModel):
    """Public asset descriptor for one extracted file asset."""

    name: str = Field(description="Asset filename.")
    url: str = Field(description="Public asset URL.")
    mime_type: str | None = Field(default=None, description="Asset mime type.")


class FileRecord(BaseModel):
    """Unified file record for list, preview, and upload responses."""

    id: int = Field(description="File ID.")
    filename: str = Field(description="Filename.")
    filetype: str = Field(description="File extension.")
    status: TaskStatusValue = Field(description="Task status.")
    ingest_status: str = Field(description="Ingest workflow status.")
    markdown_ready: bool = Field(description="Whether markdown is ready.")
    asset_ready: bool = Field(description="Whether asset directory is ready.")
    error_message: str | None = Field(default=None, description="Failure reason.")
    file_size_bytes: int | None = Field(default=None, description="File size in bytes.")
    detected_language: str | None = Field(default=None, description="Detected language.")
    estimated_pages: int | None = Field(default=None, description="Estimated pages.")
    image_count: int | None = Field(default=None, description="Extracted image count.")
    parser_used: str | None = Field(default=None, description="Parser used.")
    markdown_content: str = Field(default="", description="Parsed markdown content.")
    asset_base_url: str | None = Field(default=None, description="Base URL for assets of this file.")
    assets: list[FileAssetItem] = Field(default_factory=list, description="Extracted assets.")
    latest_updated_at: datetime = Field(description="Last updated time.")
    created_at: datetime = Field(description="Created time.")


class FilesData(BaseModel):
    """Aggregated subject files response."""

    subject: str = Field(description="Subject slug.")
    total: int = Field(description="Total file count.")
    ready_count: int = Field(description="Count of markdown-ready files.")
    processing_count: int = Field(description="Count of files still processing.")
    failed_count: int = Field(description="Count of failed files.")
    items: list[FileRecord] = Field(default_factory=list, description="Full file records.")


class FilesUploadData(BaseModel):
    """Upload response."""

    subject: str = Field(description="Subject slug.")
    filenames: list[str] = Field(description="Uploaded filenames.")
    uploaded_items: list[FileRecord] = Field(default_factory=list, description="Uploaded file records.")
    accepted_parse_file_ids: list[int] = Field(default_factory=list, description="Auto-started parse file IDs.")
    started_parse_count: int = Field(default=0, description="Count of auto-started parse files.")


class FileDeleteRequest(BaseModel):
    """Delete request."""

    file_id: int | None = Field(default=None, description="Single file ID.")
    file_ids: list[int] | None = Field(default=None, description="Multiple file IDs.")

    @model_validator(mode="after")
    def validate_ids(self) -> "FileDeleteRequest":
        if self.file_id is None and not self.file_ids:
            raise ValueError("file_id or file_ids is required.")
        return self


class FileDeleteData(BaseModel):
    """Delete result."""

    deleted_file_ids: list[int] = Field(description="Deleted file IDs.")


FilesUploadData.model_rebuild()
