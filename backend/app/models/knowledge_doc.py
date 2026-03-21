"""知识文档生成相关模型定义。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class KnowledgeDoc(SQLModel, table=True):
    """Digest 引擎生成的知识文档（一个章节对应一条记录）。"""

    __tablename__ = "knowledge_doc"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    chapter_index: int = Field(description="章节序号，决定排列顺序")
    title: str = Field(description="章节标题")
    summary: str = Field(default="", description="50 字导读摘要")
    markdown_content: str = Field(default="", description="完整 Markdown 内容")
    markdown_path: str | None = Field(default=None, description="磁盘 .md 文件路径")
    tags: str = Field(default="[]", description="JSON 数组，章节标签")
    source_file_ids: str = Field(default="[]", description="JSON 数组，来源 RawFile ID")
    word_count: int = Field(default=0, description="字数")
    version: int = Field(default=1, description="版本号")
    status: str = Field(default="draft", index=True, description="draft / published / archived")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class DocGenJob(SQLModel, table=True):
    """知识文档生成任务记录，跟踪 DocGen 工作流进度。"""

    __tablename__ = "docgen_job"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    status: str = Field(default="pending", index=True, description="pending / processing / completed / failed")
    progress: int = Field(default=0, description="进度百分比 0-100")
    current_step: str | None = Field(default=None, description="当前阶段")
    total_chapters: int = Field(default=0, description="总章节数")
    completed_chapters: int = Field(default=0, description="已完成章节数")
    error_message: str | None = Field(default=None)
    input_file_ids_json: str = Field(default="[]", description="输入文件 ID JSON")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
