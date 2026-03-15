"""Schemas for upload, file listing, and pipeline progress endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import ParseStatusValue, PipelineStatusStage


class UploadResponse(BaseModel):
    """Response returned immediately after a file is accepted for processing."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"task_id": 42, "filename": "lesson1.pdf", "subject": "math"}}
    )

    task_id: int = Field(description="上传任务 ID，可用于轮询处理状态。", examples=[42])
    filename: str = Field(description="客户端上传的原始文件名。", examples=["lesson1.pdf"])
    subject: str = Field(description="归一化后的学科标识。", examples=["math"])


class PipelineStatusResponse(BaseModel):
    """Aggregated progress view spanning upload, parse, and digest stages."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "stage": "digest",
                "progress": 60,
                "message": "大纲提取完成",
                "error": None,
            }
        }
    )

    stage: PipelineStatusStage = Field(
        description="聚合后的高层处理阶段。"
    )
    progress: int = Field(description="0 到 100 的粗粒度进度值。", ge=0, le=100, examples=[60])
    message: str = Field(description="面向前端展示的当前状态说明。")
    error: str | None = Field(default=None, description="失败时的简短错误说明。")


class FileItem(BaseModel):
    """Single uploaded file record returned by file listing endpoints."""

    id: int = Field(description="原始文件记录 ID。", examples=[42])
    filename: str = Field(description="上传文件名。", examples=["lesson1.pdf"])
    filetype: str = Field(description="文件扩展名，不含点。", examples=["pdf"])
    parse_status: ParseStatusValue = Field(description="原始文件解析阶段状态。")
    created_at: datetime = Field(description="文件记录创建时间（UTC）。")


class FileListResponse(BaseModel):
    """Paginated response for uploaded files under the same subject."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 42,
                        "filename": "lesson1.pdf",
                        "filetype": "pdf",
                        "parse_status": "parsed",
                        "created_at": "2026-03-15T08:00:00Z",
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[FileItem] = Field(description="当前分页内的文件记录列表。")
    total: int = Field(description="满足条件的文件总数。", ge=0)
