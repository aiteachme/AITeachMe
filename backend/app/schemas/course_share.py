"""课程分享 API 结构。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.export_import import ExportOptions


class CourseShareCreateRequest(BaseModel):
    """创建分享链接。"""

    expires_in_days: int = Field(default=30, ge=1, le=365)
    export_options: ExportOptions | None = Field(default=None)


class CourseShareImportRequest(BaseModel):
    """从分享链接导入课程。"""

    new_course_name: str | None = Field(default=None, max_length=120)


class CourseShareData(BaseModel):
    """课程分享链接状态。"""

    share_id: str
    token: str | None = None
    share_path: str | None = None
    source_course_id: str
    course_name: str
    course_description: str = ""
    course_icon_key: str | None = None
    status: str
    can_import: bool
    created_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    file_size_bytes: int = 0
    import_count: int = 0
    stats: dict[str, int] = Field(default_factory=dict)
    export_options: ExportOptions = Field(default_factory=ExportOptions)


class CourseShareDocumentPreview(BaseModel):
    """分享页公开展示的知识文档片段。"""

    doc_id: str
    title: str
    summary: str = ""
    excerpt: str = ""
    chapter_index: int = 0
    order_index: int = 0


class CourseShareDocumentContent(CourseShareDocumentPreview):
    """分享页公开读取的单篇知识文档正文。"""

    content_markdown: str = ""


class CourseSharePreviewData(BaseModel):
    """打开分享链接时展示的公开预览。"""

    token: str
    course_name: str
    course_description: str = ""
    course_icon_key: str | None = None
    status: str
    can_import: bool
    created_at: datetime
    expires_at: datetime
    file_size_bytes: int = 0
    stats: dict[str, int] = Field(default_factory=dict)
    documents: list[CourseShareDocumentPreview] = Field(default_factory=list)
