"""知识文档相关模型。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class KnowledgeDoc(SQLModel, table=True):
    """Digest 生成的知识文档，每条记录对应一个章节。"""

    __tablename__ = "knowledge_doc"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    chapter_index: int = Field(description="章节序号，用于控制输出顺序")
    title: str = Field(description="章节标题")
    summary: str = Field(default="", description="章节导读摘要")
    markdown_content: str = Field(default="", description="完整 Markdown 正文")
    markdown_path: str | None = Field(default=None, description="章节 Markdown 文件路径")
    tags: str = Field(default="[]", description="JSON 数组格式的章节标签")
    source_file_ids: str = Field(default="[]", description="JSON 数组格式的来源 RawFile ID")
    word_count: int = Field(default=0, description="章节字数")
    version: int = Field(default=1, description="版本号")
    status: str = Field(default="draft", index=True, description="draft / published / archived")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
