"""原始文件模型定义。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.enums import IngestStatus, TaskStatus
from app.utils.time import utcnow


class RawFile(SQLModel, table=True):
    """用户上传的原始资料文件。"""

    __tablename__ = "raw_file"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    filename: str
    filetype: str
    file_path: str
    markdown_path: str | None = None
    asset_dir: str | None = None
    status: str = Field(default=TaskStatus.PENDING.value, index=True)
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    # ── Ingest 增强字段 ──
    content_hash: str | None = Field(default=None, description="文件 SHA-256")
    file_size_bytes: int | None = Field(default=None, description="文件大小（字节）")
    estimated_pages: int | None = Field(default=None, description="预估页数/slide 数")
    detected_language: str | None = Field(default=None, description="检测语言 zh/en/mixed")
    classification_result: str | None = Field(default=None, description="分类结果 JSON")
    quality_score: float | None = Field(default=None, description="解析质量总分 0-1")
    parse_metadata: str | None = Field(default=None, description="解析元数据 JSON")
    image_count: int | None = Field(default=None, description="提取的图片数量")
    ingest_status: str = Field(default=IngestStatus.PENDING.value, description="Ingest 流水线状态")
