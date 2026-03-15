"""Knowledge outline and document routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.api.docs import build_error_responses
from app.api.deps import get_db, validate_subject, PaginationParams
from app.schemas.knowledge import DocumentListResponse, OutlineResponse
from app.services.presenters import to_document_list_response
from app.services.knowledge_service import get_outlines, get_documents

router = APIRouter(prefix="/api/v1/knowledge", tags=["knowledge"])


@router.post(
    "/{subject}/outline",
    response_model=list[OutlineResponse],
    summary="获取知识大纲",
    description="返回指定学科下每篇知识文档对应的树形大纲结构。",
    response_description="按知识文档分组的大纲树列表。",
    responses=build_error_responses([400, 500]),
)
async def get_knowledge_outline(
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> list[OutlineResponse]:
    """Return outline trees grouped by knowledge document."""
    return get_outlines(session, subject)


@router.post(
    "/{subject}/document",
    response_model=DocumentListResponse,
    summary="列出知识文档",
    description="分页返回指定学科下已存储的 Markdown 知识文档及其 Digest 阶段。",
    response_description="知识文档分页列表。",
    responses=build_error_responses([400, 500]),
)
async def list_knowledge_documents(
    body: PaginationParams = Body(..., description="分页参数。"),
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> DocumentListResponse:
    """Return a paginated list of stored knowledge documents."""
    items, total = get_documents(
        session, subject, limit=body.limit, offset=body.offset
    )
    return to_document_list_response(items, total)
