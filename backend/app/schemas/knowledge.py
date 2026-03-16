"""Schemas for `knowledge/*` endpoints under one subject."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginationParams
from app.schemas.enums import PipelineStageValue


class KnowledgeBuildRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "file_ids": [1, 2],
                "title": "Probability Midterm Review",
                "desc": "Slides and notes for chapters 1-3.",
            }
        }
    )

    file_ids: list[int] = Field(min_length=1, description="Parsed raw file identifiers selected for this build.")
    title: str = Field(description="Human-readable document set title.")
    desc: str = Field(default="", description="Optional document set description.")


class KnowledgeBuildResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"docset_id": 3, "build_job_id": 7}}
    )

    docset_id: int = Field(description="Created document-set identifier.")
    build_job_id: int = Field(description="Associated background build-job identifier.")


class KnowledgeStatusRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"docset_id": 3}})

    docset_id: int = Field(description="Document-set identifier.", examples=[3])


class KnowledgeStatusResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "docset_id": 3,
                "build_job_id": 7,
                "stage": "outlined",
                "progress": 60,
                "message": "Processed 1/2 source files.",
                "docs_count": 2,
                "chunks_count": 18,
                "error": None,
            }
        }
    )

    docset_id: int = Field(description="Document-set identifier.")
    build_job_id: int | None = Field(default=None, description="Latest build-job identifier.")
    stage: str = Field(description="Current digest build stage for the whole document set.")
    progress: int = Field(description="Approximate build progress percentage.", ge=0, le=100)
    message: str = Field(description="Human-readable progress description.")
    docs_count: int = Field(description="Number of documents under this document set.", ge=0)
    chunks_count: int = Field(description="Number of chunks generated so far.", ge=0)
    error: str | None = Field(default=None, description="Latest build error if the build failed.")


class KnowledgeListRequest(PaginationParams):
    pass


class DocSetListItem(BaseModel):
    id: int = Field(description="Document-set identifier.")
    title: str = Field(description="Document-set title.")
    description: str = Field(description="Document-set description.")
    build_status: PipelineStageValue = Field(description="Latest persisted build status.")
    documents_count: int = Field(description="Number of documents currently attached to the set.", ge=0)
    created_at: datetime = Field(description="Creation timestamp in UTC.")
    updated_at: datetime = Field(description="Latest update timestamp in UTC.")


class KnowledgeListResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 3,
                        "title": "Probability Midterm Review",
                        "description": "Slides and notes for chapters 1-3.",
                        "build_status": "embedded",
                        "documents_count": 2,
                        "created_at": "2026-03-16T08:00:00Z",
                        "updated_at": "2026-03-16T08:02:00Z",
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[DocSetListItem] = Field(description="Current page of document sets.")
    total: int = Field(description="Total document-set count.", ge=0)


class KnowledgeGetRequest(KnowledgeStatusRequest):
    pass


class DocumentItem(BaseModel):
    id: int = Field(description="Document identifier.")
    source_file_id: int = Field(description="Source raw file identifier.")
    title: str = Field(description="Document title.")
    markdown_content: str = Field(description="Stored digest markdown content.")
    pipeline_stage: PipelineStageValue = Field(description="Current digest stage for this document.")


class KnowledgeGetResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "docset_id": 3,
                "title": "Probability Midterm Review",
                "description": "Slides and notes for chapters 1-3.",
                "build_status": "embedded",
                "documents": [
                    {
                        "id": 10,
                        "source_file_id": 1,
                        "title": "lesson1.pdf",
                        "markdown_content": "# Probability basics\n",
                        "pipeline_stage": "embedded",
                    }
                ],
            }
        }
    )

    docset_id: int = Field(description="Document-set identifier.")
    title: str = Field(description="Document-set title.")
    description: str = Field(description="Document-set description.")
    build_status: PipelineStageValue = Field(description="Latest build status.")
    documents: list[DocumentItem] = Field(description="Documents generated for the selected set.")


class KnowledgeTreeRequest(KnowledgeStatusRequest):
    pass


class OutlineNode(BaseModel):
    id: int = Field(description="Outline node identifier.", examples=[1])
    title: str = Field(description="Outline node title.", examples=["Chapter 1: Probability Basics"])
    level: int = Field(description="Outline depth where 1 is the top level.", ge=1, examples=[1])
    children: list["OutlineNode"] = Field(default_factory=list, description="Nested child nodes.")


class DocumentTreeItem(BaseModel):
    document_id: int = Field(description="Document identifier.")
    title: str = Field(description="Document title.")
    nodes: list[OutlineNode] = Field(description="Outline root nodes for this document.")


class KnowledgeTreeResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "docset_id": 3,
                "title": "Probability Midterm Review",
                "documents": [
                    {
                        "document_id": 10,
                        "title": "lesson1.pdf",
                        "nodes": [
                            {
                                "id": 1,
                                "title": "Chapter 1: Probability Basics",
                                "level": 1,
                                "children": [],
                            }
                        ],
                    }
                ],
            }
        }
    )

    docset_id: int = Field(description="Document-set identifier.")
    title: str = Field(description="Document-set title.")
    documents: list[DocumentTreeItem] = Field(description="Per-document outline trees.")
