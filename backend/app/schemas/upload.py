"""Schemas for `files/*` endpoints under one subject."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginationParams
from app.schemas.enums import ParseStatusValue


class FilesParseRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"file_ids": [1, 2, 3]}})

    file_ids: list[int] = Field(min_length=1, description="Uploaded raw file identifiers to parse.")


class FileStatusRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"file_id": 1}})

    file_id: int = Field(description="Raw file identifier.", examples=[1])


class FileGetRequest(FileStatusRequest):
    pass


class FilesUploadResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "subject": "math",
                "file_ids": [1, 2],
                "filenames": ["lesson1.pdf", "lesson2.pdf"],
            }
        }
    )

    subject: str = Field(description="Top-level subject slug.", examples=["math"])
    file_ids: list[int] = Field(description="Newly created raw file identifiers.")
    filenames: list[str] = Field(description="Original filenames accepted by the backend.")


class FilesParseResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "parsed_file_ids": [1],
                "failed": [{"file_id": 2, "error": "Unsupported file type '.xlsx'."}],
            }
        }
    )

    parsed_file_ids: list[int] = Field(description="Files that finished parsing successfully in this request.")
    failed: list[dict[str, str | int]] = Field(
        default_factory=list,
        description="Files that failed parsing during this request.",
    )


class FileItem(BaseModel):
    id: int = Field(description="Raw file identifier.", examples=[1])
    filename: str = Field(description="Original uploaded filename.", examples=["lesson1.pdf"])
    filetype: str = Field(description="Normalized extension without the leading dot.", examples=["pdf"])
    parse_status: ParseStatusValue = Field(description="Parse status for the raw file.")
    markdown_ready: bool = Field(description="Whether parsed markdown is already stored.")
    latest_updated_at: datetime = Field(description="Latest update timestamp in UTC.")
    created_at: datetime = Field(description="Creation timestamp in UTC.")


class FileListRequest(PaginationParams):
    model_config = ConfigDict(
        json_schema_extra={"example": {"limit": 20, "offset": 0, "parse_status": "parsed"}}
    )

    parse_status: ParseStatusValue | None = Field(
        default=None,
        description="Optional parse-status filter.",
    )


class FileListResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 1,
                        "filename": "lesson1.pdf",
                        "filetype": "pdf",
                        "parse_status": "parsed",
                        "markdown_ready": True,
                        "latest_updated_at": "2026-03-16T08:00:00Z",
                        "created_at": "2026-03-16T08:00:00Z",
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[FileItem] = Field(description="Current page of raw files.")
    total: int = Field(description="Total raw file count.", ge=0)


class FileStatusResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_id": 1,
                "upload_status": "uploaded",
                "parse_status": "parsed",
                "markdown_ready": True,
                "asset_ready": False,
                "error": None,
                "latest_updated_at": "2026-03-16T08:00:00Z",
            }
        }
    )

    file_id: int = Field(description="Raw file identifier.", examples=[1])
    upload_status: str = Field(description="Current upload status.", examples=["uploaded"])
    parse_status: ParseStatusValue = Field(description="Current parse status.")
    markdown_ready: bool = Field(description="Whether parsed markdown already exists.")
    asset_ready: bool = Field(description="Whether extracted assets are available.")
    error: str | None = Field(default=None, description="Latest parse error message.")
    latest_updated_at: datetime = Field(description="Latest update timestamp in UTC.")


class FileAssetItem(BaseModel):
    path: str = Field(description="Relative or absolute asset path.")


class FileGetResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_id": 1,
                "filename": "lesson1.pdf",
                "parse_status": "parsed",
                "markdown_content": "# Lesson 1\n\nProbability basics\n",
                "assets": [],
            }
        }
    )

    file_id: int = Field(description="Raw file identifier.")
    filename: str = Field(description="Original uploaded filename.")
    parse_status: ParseStatusValue = Field(description="Current parse status.")
    markdown_content: str = Field(description="Stored parsed markdown content.")
    assets: list[FileAssetItem] = Field(default_factory=list, description="Parsed asset references.")
