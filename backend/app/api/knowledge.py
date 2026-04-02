"""Knowledge API routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path, Request
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.knowledge import (
    AnchorManageRequest,
    ChunkContextRequest,
    ChunkContextResponse,
    ClearKnowledgeResponse,
    DocGenBuildData,
    DocGenBuildRequest,
    DocGenGetResponse,
    GraphNodeDetailRequest,
    KnowledgeNodeDetailResponse,
    KnowledgeOverviewRequest,
    KnowledgeOverviewResponse,
    TaxonomyAnchorResponse,
    TeachingUnitDetailResponse,
    UnitDetailRequest,
)
from app.services.knowledge.cleanup_service import clear_subject_knowledge
from app.services.knowledge.curriculum_service import (
    get_teaching_unit_detail,
    manage_taxonomy_anchors,
)
from app.services.knowledge.digest_service import (
    get_docgen_result,
    run_unified_build_background,
    trigger_docgen_build,
)
from app.services.knowledge.graph_query_service import (
    get_chunk_context,
    get_graph_node_detail,
)
from app.services.knowledge.overview_service import get_knowledge_overview
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/knowledge", tags=["knowledge"])


@router.post(
    "/build",
    response_model=ApiResponse[DocGenBuildData],
    summary="触发知识文档与知识图谱构建",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def knowledge_build(
    request: Request,
    subject: str = Path(...),
    body: DocGenBuildRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[DocGenBuildData]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)

    data, accepted_file_ids = trigger_docgen_build(
        session,
        subject=normalized,
        file_uids=body.file_uids,
        prompt=body.prompt,
    )
    request.app.state.background_task_registry.spawn(
        run_unified_build_background(
            subject=normalized,
            file_ids=accepted_file_ids,
            prompt=data.prompt,
            requested_at=data.requested_at,
        ),
        kind="knowledge.build",
        subject=normalized,
        name=f"knowledge.build:{normalized}",
    )
    return ok_response(data)


@router.post(
    "/docs",
    response_model=ApiResponse[DocGenGetResponse],
    summary="查询知识文档结果",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_docs(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[DocGenGetResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(get_docgen_result(session, subject=normalized))


@router.post(
    "/overview",
    response_model=ApiResponse[KnowledgeOverviewResponse],
    summary="知识总结页聚合数据",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_overview(
    subject: str = Path(...),
    body: KnowledgeOverviewRequest = Body(default=KnowledgeOverviewRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeOverviewResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_knowledge_overview(
            session,
            subject=normalized,
            include=body.include,
            full=body.full,
        )
    )


@router.post(
    "/graph/nodes/detail",
    response_model=ApiResponse[KnowledgeNodeDetailResponse],
    summary="知识节点详情",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_node_detail(
    subject: str = Path(...),
    body: GraphNodeDetailRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeNodeDetailResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(get_graph_node_detail(session, subject=normalized, node_id=body.node_id))


@router.post(
    "/chunks/context",
    response_model=ApiResponse[ChunkContextResponse],
    summary="获取聊天引用原文上下文",
    responses=build_error_responses([400, 404, 500]),
)
async def chunk_context(
    subject: str = Path(...),
    body: ChunkContextRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[ChunkContextResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(get_chunk_context(session, subject=normalized, chunk_id=body.chunk_id))


@router.post(
    "/units/detail",
    response_model=ApiResponse[TeachingUnitDetailResponse],
    summary="教学单元详情",
    responses=build_error_responses([400, 404, 500]),
)
async def unit_detail(
    subject: str = Path(...),
    body: UnitDetailRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[TeachingUnitDetailResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(get_teaching_unit_detail(session, subject=normalized, unit_id=body.unit_id))


@router.post(
    "/taxonomy/anchors",
    response_model=ApiResponse[list[TaxonomyAnchorResponse]],
    summary="锚点管理",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def taxonomy_anchors(
    subject: str = Path(...),
    body: AnchorManageRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[list[TaxonomyAnchorResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        manage_taxonomy_anchors(
            session,
            subject=normalized,
            action=body.action,
            anchor_id=body.anchor_id,
            title=body.title,
            anchor_type=body.anchor_type,
            parent_anchor_id=body.parent_anchor_id,
            order_index=body.order_index,
        )
    )


@router.post(
    "/clear",
    response_model=ApiResponse[ClearKnowledgeResponse],
    summary="清空学科知识数据",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def knowledge_clear(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[ClearKnowledgeResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    counts = clear_subject_knowledge(session, subject=normalized)
    return ok_response(ClearKnowledgeResponse(subject=normalized, deleted_counts=counts))
