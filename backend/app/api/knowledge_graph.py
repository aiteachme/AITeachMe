"""Knowledge graph API routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path
from sqlmodel import Session

from app.api.deps import (
    CurrentUserContext,
    get_current_user_context,
    get_db,
    normalize_subject_slug,
)
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.knowledge import (
    ChunkContextRequest,
    ChunkContextResponse,
    KnowledgeUnitDetailRequest,
    KnowledgeUnitDetailResponse,
)
from app.workflows.digest.application.knowledge_graph.module import KnowledgeGraphModule
from app.workflows.support.subjects import get_subject_record

router = APIRouter(tags=["knowledge"])


@router.post(
    "/graph/knowledge-units/detail",
    response_model=ApiResponse[KnowledgeUnitDetailResponse],
    summary="Fetch KnowledgeUnit detail",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_knowledge_unit_detail(
    subject: str = Path(...),
    body: KnowledgeUnitDetailRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeUnitDetailResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    kg = KnowledgeGraphModule(session=session)
    return ok_response(
        kg.get_knowledge_unit_detail(
            subject=normalized,
            knowledge_unit_id=body.knowledge_unit_id,
        )
    )


@router.post(
    "/chunks/context",
    response_model=ApiResponse[ChunkContextResponse],
    summary="Fetch source chunk context",
    responses=build_error_responses([400, 404, 500]),
)
async def chunk_context(
    subject: str = Path(...),
    body: ChunkContextRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ChunkContextResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    kg = KnowledgeGraphModule(session=session)
    return ok_response(kg.get_chunk_context(subject=normalized, chunk_id=body.chunk_id))
