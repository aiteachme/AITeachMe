"""导入导出 API 请求/响应 Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


class ExportOptions(BaseModel):
    """导出选项（请求体）。"""

    include_raw_files: bool = Field(default=True, description="是否包含原始上传文件。")
    include_chat_history: bool = Field(default=True, description="是否包含对话记录。")
    include_exam_history: bool = Field(default=True, description="是否包含题库与考试记录。")
    include_profile: bool = Field(default=True, description="是否包含学习画像。")


class ExportPreviewStats(BaseModel):
    """导出预览统计。"""

    raw_file_count: int = 0
    total_raw_file_size_bytes: int = 0
    knowledge_document_count: int = 0
    knowledge_node_count: int = 0
    knowledge_edge_count: int = 0
    teaching_unit_count: int = 0
    question_template_count: int = 0
    exam_paper_count: int = 0
    chat_session_count: int = 0
    user_knowledge_state_count: int = 0


class ExportPreviewData(BaseModel):
    """导出预览响应。"""

    subject_id: str
    subject_name: str
    stats: ExportPreviewStats
    estimated_size_bytes: int = 0


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class ImportOptions(BaseModel):
    """导入选项（请求体）。"""

    new_subject_name: str | None = Field(default=None, description="自定义导入学科名。")


class ImportResultData(BaseModel):
    """导入结果响应。"""

    subject_id: str = Field(description="导入后的学科外部标识。")
    subject_name: str = Field(description="导入后的学科名称。")
    imported_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Course packages (shared folder)
# ---------------------------------------------------------------------------


class CoursePackageItem(BaseModel):
    """共享课程目录中的一个 .atmx 文件。"""

    filename: str = Field(description="文件名。")
    subject_name: str = Field(description="学科名称（从 manifest 读取）。")
    description: str = Field(default="", description="学科描述。")
    file_size_bytes: int = Field(default=0)
    exported_at: datetime | None = Field(default=None)
    stats: dict[str, int] = Field(default_factory=dict)

