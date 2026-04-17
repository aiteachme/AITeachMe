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
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.schemas.knowledge import (
    ChunkContextRequest,
    ChunkContextResponse,
    FullGraphResponse,
    KnowledgePathResponse,
    KnowledgeUnitPathRequest,
    KnowledgeRelationExplanationRequest,
    KnowledgeRelationExplanationResponse,
    KnowledgeRelationResponse,
    KnowledgeSubgraphRequest,
    KnowledgeSubgraphResponse,
    KnowledgeUnitDetailRequest,
    KnowledgeUnitDetailResponse,
    KnowledgeUnitsQueryRequest,
    KnowledgeUnitRelationsRequest,
    KnowledgeUnitResponse,
)
from app.workflows.support.knowledge_graph import (
    explain_relation_path,
    find_knowledge_path,
    get_chunk_context,
    get_focus_subgraph,
    get_full_graph,
    get_knowledge_unit_detail,
    get_knowledge_unit_relations,
    get_knowledge_units,
)
from app.workflows.support.subjects import get_subject_record

router = APIRouter(tags=["knowledge"])


@router.post(
    "/graph/knowledge-units",
    response_model=ApiResponse[PaginatedData[KnowledgeUnitResponse]],
    summary="List KnowledgeUnits",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_knowledge_units(
    subject: str = Path(...),
    body: KnowledgeUnitsQueryRequest = Body(default_factory=KnowledgeUnitsQueryRequest),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[KnowledgeUnitResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(
        get_knowledge_units(
            session,
            subject=normalized,
            knowledge_unit_type=body.knowledge_unit_type,
            page=body.page,
            size=body.size,
        )
    )


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
    return ok_response(
        get_knowledge_unit_detail(
            session,
            subject=normalized,
            knowledge_unit_id=body.knowledge_unit_id,
        )
    )


@router.post(
    "/graph/knowledge-units/relations",
    response_model=ApiResponse[list[KnowledgeRelationResponse]],
    summary="List KnowledgeUnit relations",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_knowledge_unit_relations(
    subject: str = Path(...),
    body: KnowledgeUnitRelationsRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[KnowledgeRelationResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(
        get_knowledge_unit_relations(
            session,
            subject=normalized,
            knowledge_unit_id=body.knowledge_unit_id,
            direction=body.direction,
            edge_type=body.edge_type,
        )
    )


@router.post(
    "/graph/knowledge-units/path",
    response_model=ApiResponse[KnowledgePathResponse],
    summary="Find a KnowledgeUnit path",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_knowledge_unit_path(
    subject: str = Path(...),
    body: KnowledgeUnitPathRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgePathResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(
        find_knowledge_path(
            session,
            subject=normalized,
            source_knowledge_unit_id=body.source_knowledge_unit_id,
            target_knowledge_unit_id=body.target_knowledge_unit_id,
            edge_type=body.edge_type,
            max_depth=body.max_depth,
        )
    )


@router.post(
    "/graph/subgraph",
    response_model=ApiResponse[KnowledgeSubgraphResponse],
    summary="Fetch a focused knowledge subgraph",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_focus_subgraph(
    subject: str = Path(...),
    body: KnowledgeSubgraphRequest = Body(default_factory=KnowledgeSubgraphRequest),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeSubgraphResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(
        get_focus_subgraph(
            session,
            subject=normalized,
            center_knowledge_unit_id=body.center_knowledge_unit_id,
            topic=body.topic,
            edge_type=body.edge_type,
            hops=body.hops,
            limit=body.limit,
        )
    )


@router.post(
    "/graph/relations/explain",
    response_model=ApiResponse[KnowledgeRelationExplanationResponse],
    summary="Explain a relation path with evidence",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_relation_explanation(
    subject: str = Path(...),
    body: KnowledgeRelationExplanationRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeRelationExplanationResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(
        explain_relation_path(
            session,
            subject=normalized,
            source_knowledge_unit_id=body.source_knowledge_unit_id,
            target_knowledge_unit_id=body.target_knowledge_unit_id,
            edge_type=body.edge_type,
            max_depth=body.max_depth,
        )
    )


@router.post(
    "/graph/full",
    response_model=ApiResponse[FullGraphResponse],
    summary="Fetch full knowledge graph",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_full(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[FullGraphResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(get_full_graph(session, subject=normalized))


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
    return ok_response(get_chunk_context(session, subject=normalized, chunk_id=body.chunk_id))

