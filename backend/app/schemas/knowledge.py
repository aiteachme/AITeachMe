"""知识相关 Schema — OutlineNode、OutlineResponse、DocumentItem、DocumentListResponse"""

from __future__ import annotations

from pydantic import BaseModel, Field


class OutlineNode(BaseModel):
    id: int
    title: str
    level: int
    children: list[OutlineNode] = Field(default_factory=list)


class OutlineResponse(BaseModel):
    knowledge_id: int
    title: str
    nodes: list[OutlineNode]


class DocumentItem(BaseModel):
    id: int
    title: str
    markdown_content: str
    pipeline_stage: str


class DocumentListResponse(BaseModel):
    items: list[DocumentItem]
    total: int
