"""File API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.enums import TaskStatusValue


class FileAssetItem(BaseModel):
    """Public asset descriptor for one extracted file asset."""

    name: str = Field(description="Asset filename.")
    url: str = Field(description="Runtime static URL for this asset.")
    mime_type: str | None = Field(default=None, description="Asset mime type.")
    asset_kind: str | None = Field(default=None, description="Asset kind.")
    page_num: int | None = Field(default=None, description="Source page number.")
    width: int | None = Field(default=None, description="Asset width.")
    height: int | None = Field(default=None, description="Asset height.")
    ocr_text: str | None = Field(default=None, description="OCR text extracted from this asset.")


class FileRecord(BaseModel):
    """Unified file record for list, preview, and upload responses."""

    id: str = Field(description="Stable public file ID.")
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
    asset_base_url: str | None = Field(default=None, description="Runtime static base URL for this file's assets.")
    assets: list[FileAssetItem] = Field(default_factory=list, description="Extracted assets.")
    classification_json: str | None = Field(default=None, description="Classification result JSON.")
    quality_score: float | None = Field(default=None, description="Parse quality score.")
    digest_current_step: str | None = Field(default=None, description="Current digest step.")
    parse_metadata_json: str | None = Field(default=None, description="Parse metadata JSON.")
    latest_updated_at: datetime = Field(description="Last updated time.")
    created_at: datetime = Field(description="Created time.")


class FilesData(BaseModel):
    """Aggregated files response."""

    course_id: str | None = Field(default=None, description="Course ID, or null for the user library.")
    total: int = Field(description="Total file count.")
    ready_count: int = Field(description="Count of markdown-ready files.")
    processing_count: int = Field(description="Count of files still processing.")
    failed_count: int = Field(description="Count of failed files.")
    items: list[FileRecord] = Field(default_factory=list, description="Full file records.")


class FilesUploadData(BaseModel):
    """Upload response."""

    course_id: str | None = Field(default=None, description="Course ID, or null for the user library.")
    filenames: list[str] = Field(description="Uploaded filenames.")
    uploaded_items: list[FileRecord] = Field(default_factory=list, description="Uploaded file records.")
    started_parse_count: int = Field(default=0, description="Count of auto-started parse files.")


class FileDeleteRequest(BaseModel):
    """Delete request."""

    file_id: str | None = Field(default=None, description="Single public file ID.")
    file_ids: list[str] | None = Field(default=None, description="Multiple public file IDs.")

    @model_validator(mode="after")
    def validate_ids(self) -> "FileDeleteRequest":
        if self.file_id is None and not self.file_ids:
            raise ValueError("file_id or file_ids is required.")
        return self


class FileDeleteData(BaseModel):
    """Delete result."""

    deleted_file_ids: list[str] = Field(default_factory=list, description="Deleted public file IDs.")


class FileLinkRequest(BaseModel):
    """Link existing user-library files to a course."""

    file_ids: list[str] = Field(default_factory=list, description="Public file IDs to link.")

    @model_validator(mode="after")
    def validate_ids(self) -> "FileLinkRequest":
        if not self.file_ids:
            raise ValueError("file_ids is required.")
        return self


FilesUploadData.model_rebuild()
