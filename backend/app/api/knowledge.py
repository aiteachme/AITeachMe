"""
知识端点

GET /api/v1/knowledge/{subject}/outline — 知识大纲树
GET /api/v1/knowledge/{subject}/document — Markdown 文档分页列表
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_db, validate_subject, PaginationParams
from app.schemas.knowledge import (
    OutlineResponse,
    DocumentItem,
    DocumentListResponse,
)
from app.services.knowledge_service import get_outlines, get_documents

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.post("/{subject}/outline", response_model=list[OutlineResponse])
async def get_knowledge_outline(
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> list[OutlineResponse]:
    """返回该学科下所有文档的 KnowledgeGraphNode 树形结构。"""
    return get_outlines(session, subject)


@router.post("/{subject}/document", response_model=DocumentListResponse)
async def list_knowledge_documents(
    body: PaginationParams,
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> DocumentListResponse:
    """返回 Markdown 文档分页列表。"""
    items, total = get_documents(
        session, subject, limit=body.limit, offset=body.offset
    )
    return DocumentListResponse(
        items=[
            DocumentItem(
                id=k.id,  # type: ignore[arg-type]
                title=k.title,
                markdown_content=k.markdown_content,
                pipeline_stage=k.pipeline_stage,
            )
            for k in items
        ],
        total=total,
    )
