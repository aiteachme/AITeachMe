"""Schemas for knowledge outline and markdown document APIs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import PipelineStageValue


class OutlineNode(BaseModel):
    """Tree node returned by the knowledge outline endpoint."""

    id: int = Field(description="知识图谱节点 ID。", examples=[1])
    title: str = Field(description="节点标题。", examples=["第一章 概率基础"])
    level: int = Field(description="节点层级深度，1 表示顶层。", ge=1, examples=[1])
    children: list[OutlineNode] = Field(
        default_factory=list,
        description="当前节点的直接子节点。",
    )


class OutlineResponse(BaseModel):
    """Outline tree grouped by knowledge document."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "knowledge_id": 7,
                "title": "lesson1.pdf",
                "nodes": [
                    {
                        "id": 1,
                        "title": "第一章 概率基础",
                        "level": 1,
                        "children": [],
                    }
                ],
            }
        }
    )

    knowledge_id: int = Field(description="知识文档 ID。", examples=[7])
    title: str = Field(description="知识文档标题。", examples=["lesson1.pdf"])
    nodes: list[OutlineNode] = Field(description="该文档的大纲树根节点列表。")


class DocumentItem(BaseModel):
    """Knowledge document plus its digest progress."""

    id: int = Field(description="知识文档 ID。", examples=[7])
    title: str = Field(description="知识文档标题。", examples=["lesson1.pdf"])
    markdown_content: str = Field(description="可直接渲染的 Markdown 正文。")
    pipeline_stage: PipelineStageValue = Field(description="Digest 流水线当前阶段。")


class DocumentListResponse(BaseModel):
    """Paginated response for stored knowledge documents."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 7,
                        "title": "lesson1.pdf",
                        "markdown_content": "# 第一章\n内容摘要",
                        "pipeline_stage": "embedded",
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[DocumentItem] = Field(description="当前分页返回的知识文档列表。")
    total: int = Field(description="满足条件的知识文档总数。", ge=0)
