"""Upload and digest helper functions shared by upload APIs and services."""

from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings
from app.repositories.models import Knowledge, ParseStatus, PipelineStage, RawFile
from app.schemas.upload import PipelineStatusResponse


_PIPELINE_STAGE_DISPLAY: dict[str, tuple[str, int, str]] = {
    PipelineStage.PENDING: ("digest", 40, "等待消化索引"),
    PipelineStage.CLEANED: ("digest", 50, "Markdown 清洗完成"),
    PipelineStage.OUTLINED: ("digest", 60, "大纲提取完成"),
    PipelineStage.STORED: ("digest", 70, "知识落库完成"),
    PipelineStage.CHUNKED: ("digest", 80, "文档切块完成"),
    PipelineStage.EMBEDDED: ("done", 100, "处理完成"),
    PipelineStage.FAILED: ("failed", 100, "索引失败"),
}


def get_data_dir() -> Path:
    """Return the configured data root directory as a `Path` object."""

    return Path(get_settings().data_dir)


def build_storage_prefix(record_id: int) -> str:
    """Bucket persisted files by the first two digits of their record ID."""

    return str(record_id)[:2]


def build_raw_file_path(record_id: int, extension: str) -> Path:
    """Return the final storage path for an uploaded raw file."""

    normalized_extension = extension if extension.startswith(".") else f".{extension}"
    return get_data_dir() / "raw" / build_storage_prefix(record_id) / f"{record_id}{normalized_extension}"


def build_markdown_path(raw_file_id: int) -> Path:
    """Return the markdown output path for a parsed raw file."""

    return get_data_dir() / "markdown" / build_storage_prefix(raw_file_id) / f"{raw_file_id}.md"


def build_pipeline_status(raw_file: RawFile, knowledge: Knowledge | None) -> PipelineStatusResponse:
    """Aggregate raw-file parse state and digest state into one API response."""

    if raw_file.parse_status == ParseStatus.PENDING:
        return PipelineStatusResponse(stage="upload", progress=0, message="等待解析", error=None)
    if raw_file.parse_status == ParseStatus.PARSING:
        return PipelineStatusResponse(stage="parse", progress=20, message="正在解析文档", error=None)
    if raw_file.parse_status == ParseStatus.PARSE_FAILED:
        return PipelineStatusResponse(stage="failed", progress=100, message="解析失败", error="文件解析失败")

    if knowledge is None:
        return PipelineStatusResponse(stage="parse", progress=30, message="解析完成，准备索引", error=None)

    stage, progress, message = _PIPELINE_STAGE_DISPLAY.get(
        knowledge.pipeline_stage,
        ("digest", 40, "处理中"),
    )
    error = "消化索引失败" if knowledge.pipeline_stage == PipelineStage.FAILED else None
    return PipelineStatusResponse(stage=stage, progress=progress, message=message, error=error)
