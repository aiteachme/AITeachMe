"""Knowledge docs API routes."""

from __future__ import annotations

import asyncio
from typing import Literal

import structlog
from fastapi import APIRouter, Body, Depends, Path, Query, Request
from fastapi.responses import Response, StreamingResponse
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
    BuildPlannerConfirmResponse,
    BuildPlannerCreateRequest,
    BuildPlannerMessageRequest,
    BuildPlannerSessionResponse,
    ClearKnowledgeResponse,
    DocGenBuildCancelData,
    DocGenBuildData,
    DocGenBuildRequest,
    DocGenGetResponse,
    KnowledgeDebugTriggerRequest,
    KnowledgeDebugTriggerResponse,
    KnowledgeOverviewRequest,
    KnowledgeOverviewResponse,
)
from app.workflows.digest.planner import (
    append_build_planner_message,
    confirm_build_planner_session,
    create_build_planner_session,
    get_latest_planner_session,
    mark_confirmed_build_plan_status,
)
from app.workflows.support.auth import set_guest_cookie_for_user
from app.workflows.digest.docgen import (
    clear_subject_knowledge,
    get_docgen_result,
    run_docgen_background,
    trigger_docgen_build,
)
from app.workflows.support.knowledge_graph import (
    clear_subject_graph_entities,
    get_knowledge_overview,
    run_graph_build_background,
    run_graph_docs_sync_debug_background,
    run_graph_file_ingest_debug_background,
)
from app.workflows.support.subjects import get_subject_record
from app.workflows.interact.chat.lib.streaming import SSEEventEmitter
from app.utils.docgen_store import (
    KnowledgeBuildLock,
    acquire_knowledge_build_lock,
    read_knowledge_build_status,
    release_knowledge_build_lock,
    update_knowledge_build_status,
)
from app.utils.time import utcnow
from app.shared.infra.exceptions import AITeachMeError, SubjectBuildLockConflictError
from app.workflows.digest.docgen.lib.export_document import (
    build_content_disposition,
    build_export_filename,
    markdown_to_pdf_bytes,
)

router = APIRouter(tags=["knowledge"])
logger = structlog.get_logger(__name__)


def _planner_stream_response(
    *,
    request: Request,
    user_id: str,
    runner,
) -> StreamingResponse:
    emitter = SSEEventEmitter()

    async def workflow_task() -> None:
        logger.info("planner_stream_task_started", user_id=user_id)
        try:
            await emitter.emit_event(
                "status",
                {
                    "stage": "accepted",
                    "detail": "请求已受理，正在读取学习目标与资料。",
                },
            )

            async def progress_callback(payload: dict[str, object]) -> None:
                await emitter.emit_event(
                    "status",
                    payload,
                )

            async def token_callback(token: str) -> None:
                await emitter.emit_token(token)

            response = await runner(progress_callback, token_callback)
            logger.info(
                "planner_stream_runner_completed",
                user_id=user_id,
                session_id=getattr(response, "session_id", ""),
                status=getattr(response, "status", ""),
            )
            runtime_stats = getattr(response, "runtime_stats", None)
            elapsed_ms = 0
            if runtime_stats is not None:
                elapsed_ms = int(
                    getattr(runtime_stats, "elapsed_ms", None)
                    or getattr(runtime_stats, "workflow_elapsed_ms", 0)
                    or 0
                )
            await emitter.emit_event(
                "status",
                {
                    "stage": "completed",
                    "detail": (
                        f"构建方案已生成，用时 {elapsed_ms} ms。"
                        if runtime_stats is not None
                        else "构建方案已生成。"
                    ),
                    "elapsed_ms": elapsed_ms,
                },
            )
            await emitter.emit_event("done", {"session": response.model_dump(mode="json")})
        except asyncio.CancelledError:
            # Client disconnected or the SSE stream was intentionally aborted.
            logger.info("planner_stream_task_cancelled", user_id=user_id)
            pass
        except Exception as exc:
            logger.exception("planner_stream_task_failed", user_id=user_id, error=str(exc))
            await emitter.emit_error(detail=str(exc), error_code="planner_stream_failed")
        finally:
            logger.info("planner_stream_task_closed", user_id=user_id)
            await emitter.close()

    async def event_stream():
        task = asyncio.create_task(workflow_task())
        async for payload in emitter.stream(request=request, workflow_task=task):
            yield payload

    stream_response = StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
    set_guest_cookie_for_user(stream_response, user_id=user_id)
    return stream_response


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
    data = await create_build_planner_session(
        subject=subject_record,
        user_id=user.user_id,
        payload=body,
    )
    return ok_response(data)


@router.post(
    "/debug/kg-file-ingest",
    response_model=ApiResponse[KnowledgeDebugTriggerResponse],
    summary="Trigger kg_file_ingest only for debugging",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def knowledge_debug_kg_file_ingest(
    request: Request,
    subject: str = Path(...),
    body: KnowledgeDebugTriggerRequest = Body(default=KnowledgeDebugTriggerRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDebugTriggerResponse]:
    normalized = normalize_subject_slug(subject)
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    data, accepted_file_ids = trigger_docgen_build(
        session,
        subject=subject_record,
        user_id=user.user_id,
        file_uids=body.file_uids,
        prompt=body.prompt,
        embedding_resolution=body.embedding_resolution,
        confirmed_plan_id=None,
        build_type="graph",
    )
    request.app.state.background_task_registry.spawn(
        run_graph_file_ingest_debug_background(
            subject=normalized,
            file_ids=accepted_file_ids,
            prompt=data.prompt,
            requested_at=data.requested_at,
        ),
        kind="knowledge.debug.kg_file_ingest",
        subject=normalized,
        name=f"knowledge.debug.kg_file_ingest:{normalized}",
    )
    return ok_response(
        KnowledgeDebugTriggerResponse(
            action="kg_file_ingest",
            requested_at=data.requested_at,
            accepted_file_uids=data.accepted_file_uids,
            message=f"已触发 kg_file_ingest，本轮纳入 {len(data.accepted_file_uids)} 份已解析资料。",
        )
    )


@router.post(
    "/debug/kg-docs-sync",
    response_model=ApiResponse[KnowledgeDebugTriggerResponse],
    summary="Trigger kg_docs_sync only for debugging",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def knowledge_debug_kg_docs_sync(
    request: Request,
    subject: str = Path(...),
    body: KnowledgeDebugTriggerRequest = Body(default=KnowledgeDebugTriggerRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDebugTriggerResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    requested_at = utcnow()
    if not acquire_knowledge_build_lock(
        normalized,
        KnowledgeBuildLock(requested_at=requested_at, source_file_ids=[], prompt=body.prompt),
    ):
        raise SubjectBuildLockConflictError(normalized)
    update_knowledge_build_status(
        normalized,
        requested_at=requested_at,
        build_kind="graph",
        status="accepted",
        stage="graph_docs_sync",
        prompt=body.prompt,
        source_file_ids=[],
        current_stage_description="已接收 kg_docs_sync 调试请求，正在排队启动。",
    )
    request.app.state.background_task_registry.spawn(
        run_graph_docs_sync_debug_background(
            subject=normalized,
            prompt=body.prompt,
            requested_at=requested_at,
        ),
        kind="knowledge.debug.kg_docs_sync",
        subject=normalized,
        name=f"knowledge.debug.kg_docs_sync:{normalized}",
    )
    return ok_response(
        KnowledgeDebugTriggerResponse(
            action="kg_docs_sync",
            requested_at=requested_at,
            accepted_file_uids=[],
            message="已触发 kg_docs_sync，将基于当前已发布知识文档同步知识单元、知识图片与图谱关系。",
        )
    )


@router.post(
    "/debug/clear-graph",
    response_model=ApiResponse[ClearKnowledgeResponse],
    summary="Clear knowledge units and graph edges only for debugging",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def knowledge_debug_clear_graph(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ClearKnowledgeResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    counts = clear_subject_graph_entities(session, subject=normalized)
    return ok_response(ClearKnowledgeResponse(subject=normalized, deleted_counts=counts))


@router.post(
    "/build/plans/latest",
    response_model=ApiResponse[BuildPlannerSessionResponse | None],
    summary="Get the latest build planner session for this subject",
    responses=build_error_responses([400, 404, 500]),
)
def knowledge_build_plan_latest(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[BuildPlannerSessionResponse | None]:
    normalized = normalize_subject_slug(subject)
    logger.info("planner_latest_requested", subject=normalized, user_id=user.user_id)
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    data = get_latest_planner_session(
        session,
        subject=subject_record,
        user_id=user.user_id,
    )
    logger.info(
        "planner_latest_completed",
        subject=normalized,
        user_id=user.user_id,
        found=bool(data),
        session_id=getattr(data, "session_id", "") if data else "",
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
    logger.info(
        "planner_create_stream_requested",
        subject=normalized,
        user_id=user.user_id,
        file_uid_count=len(body.file_uids or []),
        user_prompt_preview=(body.user_prompt or "")[:80],
    )
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    return _planner_stream_response(
        request=request,
        user_id=user.user_id,
        runner=lambda progress_callback, token_callback: create_build_planner_session(
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
    data = await append_build_planner_message(
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
    logger.info(
        "planner_message_stream_requested",
        subject=normalized,
        session_id=session_id,
        user_id=user.user_id,
        message_preview=(body.message or "")[:80],
    )
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    return _planner_stream_response(
        request=request,
        user_id=user.user_id,
        runner=lambda progress_callback, token_callback: append_build_planner_message(
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
    logger.info(
        "knowledge_build_plan_confirm_requested",
        subject=normalized,
        session_id=session_id,
        user_id=user.user_id,
    )
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    data = confirm_build_planner_session(
        session,
        subject=subject_record,
        user_id=user.user_id,
        session_id=session_id,
    )
    logger.info(
        "knowledge_build_plan_confirm_completed",
        subject=normalized,
        session_id=session_id,
        confirmed_plan_id=data.confirmed_plan_id,
        user_id=user.user_id,
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
    logger.info(
        "knowledge_build_request_received",
        subject=normalized,
        user_id=user.user_id,
        build_type=body.build_type or "docs",
        confirmed_plan_id=body.confirmed_plan_id,
        file_uid_count=len(body.file_uids or []),
    )
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
        build_type=body.build_type or "docs",
    )

    build_type = body.build_type or "docs"

    if build_type == "docs":
        logger.info(
            "knowledge_build_docs_background_spawning",
            subject=normalized,
            user_id=user.user_id,
            confirmed_plan_id=data.confirmed_plan_id,
            accepted_file_count=len(accepted_file_ids),
            requested_at=data.requested_at.isoformat(),
        )
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
        logger.info(
            "knowledge_build_graph_background_spawning",
            subject=normalized,
            user_id=user.user_id,
            accepted_file_count=len(accepted_file_ids),
            requested_at=data.requested_at.isoformat(),
        )
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
    logger.info(
        "knowledge_build_request_accepted",
        subject=normalized,
        user_id=user.user_id,
        build_type=build_type,
        confirmed_plan_id=data.confirmed_plan_id,
        accepted_file_count=len(accepted_file_ids),
        requested_at=data.requested_at.isoformat(),
    )
    return ok_response(data)


@router.post(
    "/build/cancel",
    response_model=ApiResponse[DocGenBuildCancelData],
    summary="Cancel the active digest build for this subject",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_build_cancel(
    request: Request,
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[DocGenBuildCancelData]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    build_status = read_knowledge_build_status(normalized)
    cancelled_task_count = 0
    registry = getattr(request.app.state, "background_task_registry", None)
    if registry is not None:
        cancelled_task_count += await registry.cancel_matching(kind="knowledge.build.docs", subject=normalized)
        cancelled_task_count += await registry.cancel_matching(kind="knowledge.build.graph", subject=normalized)

    requested_at = build_status.requested_at if build_status is not None else utcnow()
    confirmed_plan_id = build_status.confirmed_plan_id if build_status is not None else None
    if confirmed_plan_id:
        mark_confirmed_build_plan_status(
            session,
            subject=normalized,
            user_id=user.user_id,
            plan_id=confirmed_plan_id,
            status="cancelled",
        )
    update_knowledge_build_status(
        normalized,
        requested_at=requested_at,
        status="cancelled",
        stage="cancelled",
        error_message="build_cancelled",
        draft_available=False,
        planner_session_id=build_status.planner_session_id if build_status is not None else None,
        confirmed_plan_id=confirmed_plan_id,
        digest_mode=build_status.digest_mode if build_status is not None else None,
        current_stage_description="本轮知识构建已被用户终止。",
    )
    release_knowledge_build_lock(normalized)
    return ok_response(
        DocGenBuildCancelData(
            subject=normalized,
            cancelled_task_count=cancelled_task_count,
            requested_at=requested_at,
        )
    )


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


@router.get(
    "/docs/export",
    summary="Export the merged knowledge document",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_docs_export(
    subject: str = Path(...),
    format: Literal["md", "pdf"] = Query(default="md", description="Export format."),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> Response:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized, owner_user_id=user.user_id)
    doc = get_docgen_result(session, subject=normalized)
    markdown = str(doc.markdown or "").strip()
    if not doc.exists or not markdown:
        raise AITeachMeError(
            "当前还没有可导出的合并知识文档。",
            error_code="KNOWLEDGE_DOC_NOT_FOUND",
            status_code=404,
        )

    filename = build_export_filename(subject=normalized, markdown=markdown, extension=format)
    headers = {"Content-Disposition": build_content_disposition(filename)}
    if format == "md":
        return Response(
            content=markdown.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers=headers,
        )
    return Response(
        content=markdown_to_pdf_bytes(markdown=markdown, title=filename.rsplit(".", 1)[0]),
        media_type="application/pdf",
        headers=headers,
    )


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
