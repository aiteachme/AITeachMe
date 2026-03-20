"""知识接口。"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Path
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.schemas.knowledge import (
    ClearKnowledgeResponse,
    CurriculumSnapshotResponse,
    DigestBuildData,
    DigestBuildRequest,
    DigestStatusRequest,
    DigestStatusResponse,
    EvidenceContextRequest,
    EvidenceContextResponse,
    FullGraphResponse,
    GraphNodeDetailRequest,
    GraphNodesQueryRequest,
    KnowledgeNodeDetailResponse,
    KnowledgeNodeResponse,
    PrereqDagResponse,
    TaxonomyAnchorResponse,
    TeachingUnitDetailResponse,
    TeachingUnitResponse,
    ThemeTreeResponse,
    UnitDetailRequest,
    UnitsQueryRequest,
    AnchorManageRequest,
)
from app.services.knowledge.curriculum_service import (
    clear_subject_knowledge,
    get_current_curriculum_snapshot,
    get_current_prereq_dag,
    get_current_theme_tree,
    get_teaching_unit_detail,
    get_teaching_units,
    manage_taxonomy_anchors,
)
from app.services.knowledge.digest_service import (
    get_digest_status,
    run_graph_digest_background,
    trigger_digest_build,
)
from app.services.knowledge.graph_query_service import (
    get_evidence_context,
    get_full_graph,
    get_graph_node_detail,
    get_graph_nodes,
)
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/knowledge", tags=["knowledge"])


@router.post(
    "/digest/build",
    response_model=ApiResponse[DigestBuildData],
    summary="触发增量构建",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def digest_build(
    background_tasks: BackgroundTasks,
    subject: str = Path(...),
    body: DigestBuildRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[DigestBuildData]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    data = trigger_digest_build(
        session,
        subject=normalized,
        file_ids=body.file_ids,
        idempotency_key=body.idempotency_key,
    )
    if not data.is_existing:
        background_tasks.add_task(
            run_graph_digest_background,
            subject=normalized,
            job_id=data.job_id,
        )
    return ok_response(data)


@router.post(
    "/digest/status",
    response_model=ApiResponse[DigestStatusResponse],
    summary="查询增量构建聚合状态",
    responses=build_error_responses([400, 404, 500]),
)
async def digest_status(
    subject: str = Path(...),
    body: DigestStatusRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[DigestStatusResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_digest_status(session, subject=normalized, job_id=body.job_id)
    )


@router.post(
    "/graph/nodes/query",
    response_model=ApiResponse[PaginatedData[KnowledgeNodeResponse]],
    summary="分页查询知识节点",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_nodes_query(
    subject: str = Path(...),
    body: GraphNodesQueryRequest = Body(default=GraphNodesQueryRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[KnowledgeNodeResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_graph_nodes(
            session,
            subject=normalized,
            node_type=body.node_type,
            page=body.page,
            size=body.size,
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
    return ok_response(
        get_graph_node_detail(session, subject=normalized, node_id=body.node_id)
    )


@router.post(
    "/graph/full",
    response_model=ApiResponse[FullGraphResponse],
    summary="获取完整知识图谱（节点+边）",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_full(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[FullGraphResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_full_graph(session, subject=normalized)
    )


@router.post(
    "/graph/evidence/context",
    response_model=ApiResponse[EvidenceContextResponse],
    summary="获取证据原文上下文",
    responses=build_error_responses([400, 404, 500]),
)
async def evidence_context(
    subject: str = Path(...),
    body: EvidenceContextRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[EvidenceContextResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_evidence_context(session, subject=normalized, evidence_id=body.evidence_id)
    )



# ── Phase 2: 教学单元路由 ──


@router.post(
    "/units/query",
    response_model=ApiResponse[PaginatedData[TeachingUnitResponse]],
    summary="分页查询教学单元",
    responses=build_error_responses([400, 404, 500]),
)
async def units_query(
    subject: str = Path(...),
    body: UnitsQueryRequest = Body(default=UnitsQueryRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[TeachingUnitResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_teaching_units(
            session,
            subject=normalized,
            status=body.status,
            page=body.page,
            size=body.size,
        )
    )


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
    return ok_response(
        get_teaching_unit_detail(session, subject=normalized, unit_id=body.unit_id)
    )



# ── Phase 3: 主题树路由 ──


@router.post(
    "/theme-tree/current",
    response_model=ApiResponse[ThemeTreeResponse],
    summary="当前主题树",
    responses=build_error_responses([400, 404, 500]),
)
async def theme_tree_current(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[ThemeTreeResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_current_theme_tree(session, subject=normalized)
    )


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



# ── Phase 4: 先修 DAG 路由 ──


@router.post(
    "/prereq-dag/current",
    response_model=ApiResponse[PrereqDagResponse],
    summary="当前先修 DAG",
    responses=build_error_responses([400, 404, 500]),
)
async def prereq_dag_current(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[PrereqDagResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_current_prereq_dag(session, subject=normalized)
    )


@router.post(
    "/curriculum/current",
    response_model=ApiResponse[CurriculumSnapshotResponse],
    summary="当前课程快照",
    responses=build_error_responses([400, 404, 500]),
)
async def curriculum_current(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[CurriculumSnapshotResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    return ok_response(
        get_current_curriculum_snapshot(session, subject=normalized)
    )


# ── 清空知识数据 ──


@router.post(
    "/clear",
    response_model=ApiResponse[ClearKnowledgeResponse],
    summary="清空学科所有知识数据",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_clear(
    subject: str = Path(...),
    session: Session = Depends(get_db),
) -> ApiResponse[ClearKnowledgeResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    counts = clear_subject_knowledge(session, subject=normalized)
    return ok_response(
        ClearKnowledgeResponse(subject=normalized, deleted_counts=counts)
    )
