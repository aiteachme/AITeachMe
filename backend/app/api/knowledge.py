"""Knowledge API routes."""

from __future__ import annotations

import asyncio
from fastapi import APIRouter, Body, Depends, Path, Request
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.knowledge import (
    AnchorManageRequest,
    BuildPlannerConfirmResponse,
    BuildPlannerCreateRequest,
    BuildPlannerMessageRequest,
    BuildPlannerSessionResponse,
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
    StudyPlanRequest,
    StudyPlanResponse,
    TaxonomyAnchorResponse,
    TeachingUnitDetailResponse,
    UnitDetailRequest,
)
from app.services.knowledge.build_planner_service import (
    append_build_planner_message_service,
    confirm_build_planner_session_service,
    create_build_planner_session_service,
)
from app.services.knowledge.cleanup_service import clear_subject_knowledge
from app.services.knowledge.curriculum_service import (
    get_teaching_unit_detail,
    manage_taxonomy_anchors,
)
from app.services.knowledge.digest_service import (
    get_docgen_result,
    run_docgen_background,
    run_graph_build_background,
    run_unified_build_background,
    trigger_docgen_build,
)
from app.services.knowledge.graph_query_service import (
    get_chunk_context,
    get_graph_node_detail,
)
from app.services.knowledge.overview_service import get_knowledge_overview
from app.services.knowledge.study_plan_service import handle_study_plan_request
from app.services.subject_service import get_subject_record
from app.workflows.interact.support.streaming import SSEEventEmitter

router = APIRouter(prefix="/api/v1/subjects/{subject}/knowledge", tags=["knowledge"])


def _planner_status_detail(payload: dict[str, object]) -> str:
    node_name = str(payload.get("node_name") or "").strip()
    elapsed_ms = int(payload.get("elapsed_ms", 0) or 0)
    status = str(payload.get("status") or "ok").strip() or "ok"
    if node_name:
        if status == "failed":
            return f"{node_name} 失败，耗时 {elapsed_ms} ms。"
        return f"{node_name} 完成，耗时 {elapsed_ms} ms。"
    return "正在生成构建方案。"


def _planner_stream_response(
    *,
    request: Request,
    runner,
) -> StreamingResponse:
    emitter = SSEEventEmitter()

    async def workflow_task() -> None:
        try:
            await emitter.emit_event(
                "status",
                {
                    "stage": "accepted",
                    "detail": "已接收请求，正在读取资料与用户目标。",
                },
            )

            async def progress_callback(payload: dict[str, object]) -> None:
                await emitter.emit_event(
                    "status",
                    {
                        **payload,
                        "stage": str(payload.get("node_name") or "node"),
                        "detail": str(payload.get("detail") or "").strip() or _planner_status_detail(payload),
                    },
                )

            async def token_callback(token: str) -> None:
                await emitter.emit_token(token)

            response = await runner(progress_callback, token_callback)
            runtime_stats = getattr(response, "runtime_stats", None)
            await emitter.emit_event(
                "status",
                {
                    "stage": "completed",
                    "detail": (
                        f"方案生成完成，总耗时 {runtime_stats.workflow_elapsed_ms} ms。"
                        if runtime_stats is not None
                        else "方案生成完成。"
                    ),
                    "workflow_elapsed_ms": (
                        int(runtime_stats.workflow_elapsed_ms)
                        if runtime_stats is not None
                        else 0
                    ),
                },
            )
            await emitter.emit_event("done", {"session": response.model_dump(mode="json")})
        except Exception as exc:
            await emitter.emit_error(detail=str(exc), error_code="planner_stream_failed")
        finally:
            await emitter.close()

    async def event_stream():
        task = asyncio.create_task(workflow_task())
        async for payload in emitter.stream(request=request, workflow_task=task):
            yield payload

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/build/plans",
    response_model=ApiResponse[BuildPlannerSessionResponse],
    summary="Create a build planner session",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def knowledge_build_plan_create(
    subject: str = Path(...),
    body: BuildPlannerCreateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[BuildPlannerSessionResponse]:
    normalized = normalize_subject_slug(subject)
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    data = await create_build_planner_session_service(
        session,
        subject=subject_record,
        user_id=user.user_id,
        payload=body,
    )
    return ok_response(data)


@router.post(
    "/build/plans/stream",
    summary="Create a build planner session with SSE progress",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def knowledge_build_plan_create_stream(
    request: Request,
    subject: str = Path(...),
    body: BuildPlannerCreateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    normalized = normalize_subject_slug(subject)
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    return _planner_stream_response(
        request=request,
        runner=lambda progress_callback, token_callback: create_build_planner_session_service(
            session,
            subject=subject_record,
            user_id=user.user_id,
            payload=body,
            progress_callback=progress_callback,
            token_callback=token_callback,
        ),
    )


@router.post(
    "/build/plans/{session_id}/messages",
    response_model=ApiResponse[BuildPlannerSessionResponse],
    summary="Append planner feedback and regenerate the plan",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def knowledge_build_plan_message(
    subject: str = Path(...),
    session_id: str = Path(...),
    body: BuildPlannerMessageRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[BuildPlannerSessionResponse]:
    normalized = normalize_subject_slug(subject)
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    data = await append_build_planner_message_service(
        session,
        subject=subject_record,
        user_id=user.user_id,
        session_id=session_id,
        payload=body,
    )
    return ok_response(data)


@router.post(
    "/build/plans/{session_id}/messages/stream",
    summary="Append planner feedback with SSE progress",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def knowledge_build_plan_message_stream(
    request: Request,
    subject: str = Path(...),
    session_id: str = Path(...),
    body: BuildPlannerMessageRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> StreamingResponse:
    normalized = normalize_subject_slug(subject)
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    return _planner_stream_response(
        request=request,
        runner=lambda progress_callback, token_callback: append_build_planner_message_service(
            session,
            subject=subject_record,
            user_id=user.user_id,
            session_id=session_id,
            payload=body,
            progress_callback=progress_callback,
            token_callback=token_callback,
        ),
    )


@router.post(
    "/build/plans/{session_id}/confirm",
    response_model=ApiResponse[BuildPlannerConfirmResponse],
    summary="Confirm the current planner draft and freeze a build plan",
    responses=build_error_responses([400, 404, 422, 500]),
)
def knowledge_build_plan_confirm(
    subject: str = Path(...),
    session_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[BuildPlannerConfirmResponse]:
    normalized = normalize_subject_slug(subject)
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    data = confirm_build_planner_session_service(
        session,
        subject=subject_record,
        user_id=user.user_id,
        session_id=session_id,
    )
    return ok_response(data)


@router.post(
    "/build",
    response_model=ApiResponse[DocGenBuildData],
    summary="Trigger docs and/or graph digest build",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def knowledge_build(
    request: Request,
    subject: str = Path(...),
    body: DocGenBuildRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[DocGenBuildData]:
    normalized = normalize_subject_slug(subject)
    subject_record = get_subject_record(
        session,
        normalized,
        owner_user_id=user.user_id,
    )

    data, accepted_file_ids = trigger_docgen_build(
        session,
        subject=subject_record,
        user_id=user.user_id,
        file_uids=body.file_uids,
        prompt=body.prompt,
        embedding_resolution=body.embedding_resolution,
        confirmed_plan_id=body.confirmed_plan_id,
        build_type=body.build_type or "all",
    )

    build_type = body.build_type or "all"

    if build_type == "docs":
        request.app.state.background_task_registry.spawn(
            run_docgen_background(
                subject=normalized,
                file_ids=accepted_file_ids,
                prompt=data.prompt,
                requested_at=data.requested_at,
                planner_session_id=data.planner_session_id,
                confirmed_plan_id=data.confirmed_plan_id,
                user_id=user.user_id,
            ),
            kind="knowledge.build.docs",
            subject=normalized,
            name=f"knowledge.build.docs:{normalized}",
        )
    elif build_type == "graph":
        request.app.state.background_task_registry.spawn(
            run_graph_build_background(
                subject=normalized,
                file_ids=accepted_file_ids,
                prompt=data.prompt,
                requested_at=data.requested_at,
            ),
            kind="knowledge.build.graph",
            subject=normalized,
            name=f"knowledge.build.graph:{normalized}",
        )
    else:
        request.app.state.background_task_registry.spawn(
            run_unified_build_background(
                subject=normalized,
                file_ids=accepted_file_ids,
                prompt=data.prompt,
                requested_at=data.requested_at,
                planner_session_id=data.planner_session_id,
                confirmed_plan_id=data.confirmed_plan_id,
                user_id=user.user_id,
            ),
            kind="knowledge.build",
            subject=normalized,
            name=f"knowledge.build:{normalized}",
        )
    return ok_response(data)


@router.post(
    "/docs",
    response_model=ApiResponse[DocGenGetResponse],
    summary="Fetch knowledge docs and minimal build state",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_docs(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[DocGenGetResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(get_docgen_result(session, subject=normalized))


@router.post(
    "/overview",
    response_model=ApiResponse[KnowledgeOverviewResponse],
    summary="Fetch aggregated knowledge overview",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_overview(
    subject: str = Path(...),
    body: KnowledgeOverviewRequest = Body(default=KnowledgeOverviewRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeOverviewResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
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
    summary="Fetch knowledge node detail",
    responses=build_error_responses([400, 404, 500]),
)
async def graph_node_detail(
    subject: str = Path(...),
    body: GraphNodeDetailRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeNodeDetailResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(get_graph_node_detail(session, subject=normalized, node_id=body.node_id))


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


@router.post(
    "/units/detail",
    response_model=ApiResponse[TeachingUnitDetailResponse],
    summary="Fetch teaching unit detail",
    responses=build_error_responses([400, 404, 500]),
)
async def unit_detail(
    subject: str = Path(...),
    body: UnitDetailRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[TeachingUnitDetailResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(get_teaching_unit_detail(session, subject=normalized, unit_id=body.unit_id))


@router.post(
    "/study-plan",
    response_model=ApiResponse[StudyPlanResponse],
    summary="Fetch or update the learner study plan",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def knowledge_study_plan(
    subject: str = Path(...),
    body: StudyPlanRequest = Body(default=StudyPlanRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[StudyPlanResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(handle_study_plan_request(session, subject=normalized, payload=body))


@router.post(
    "/taxonomy/anchors",
    response_model=ApiResponse[list[TaxonomyAnchorResponse]],
    summary="Manage taxonomy anchors",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def taxonomy_anchors(
    subject: str = Path(...),
    body: AnchorManageRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[TaxonomyAnchorResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
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
    summary="Clear knowledge artifacts for one subject",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def knowledge_clear(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ClearKnowledgeResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    counts = clear_subject_knowledge(session, subject=normalized)
    return ok_response(ClearKnowledgeResponse(subject=normalized, deleted_counts=counts))
