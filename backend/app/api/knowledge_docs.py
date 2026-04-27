"""Knowledge docs API routes."""

from __future__ import annotations

import asyncio
import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Body, Depends, Path, Request, Response
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.api.deps import (
    CurrentUserContext,
    get_current_user_context,
    get_db,
    normalize_subject_slug,
)
from app.api.openapi import build_error_responses
from app.models import Subject
from app.schemas.common import ApiResponse, ok_response
from app.schemas.knowledge import (
    BuildPlannerAdjustClickResponse,
    BuildPlannerConfirmResponse,
    BuildPlannerCreateRequest,
    BuildPlannerMessageRequest,
    BuildPlannerSessionResponse,
    ClearKnowledgeResponse,
    DocGenBuildCancelData,
    DocGenBuildData,
    DocGenBuildRequest,
    DocGenGetResponse,
    KnowledgeBuildRuntimeResponse,
    KnowledgeGraphBuildData,
    KnowledgeOverviewRequest,
    KnowledgeOverviewResponse,
)
from app.workflows.digest.planner import (
    append_build_planner_message,
    confirm_build_planner_session,
    create_build_planner_session,
    get_latest_planner_session,
    mark_confirmed_build_plan_status,
    record_build_planner_adjust_click,
)
from app.workflows.support.auth import set_guest_cookie_for_user
from app.workflows.digest.docgen import (
    clear_subject_knowledge,
    get_docgen_result,
    get_knowledge_build_runtime_result,
    run_docgen_background,
    trigger_docgen_build,
)
from app.workflows.digest.kg_doc_sync import (
    get_knowledge_overview,
    load_knowledge_doc_sync_input,
    run_graph_docs_sync_manual_build,
)
from app.workflows.support.subjects import get_subject_record
from app.workflows.interact.chat.lib.streaming import SSEEventEmitter
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.database import managed_session
from app.shared.infra.workflow.live_stream import (
    WorkflowStreamEvent,
    format_sse_event,
    subscribe_workflow_stream,
)
from app.shared.infra.knowledge.build_store import (
    build_aggregate_knowledge_build_status,
    read_knowledge_build_runtime,
    read_knowledge_manifest,
    release_knowledge_build_lock,
    update_knowledge_build_lane_status,
)
from app.shared.infra.llm_support.common import capture_llm_runtime_snapshot
from app.shared.infra.storage import SubjectStorageScope, build_subject_storage_scope
from app.utils.time import utcnow

router = APIRouter(tags=["knowledge"])
logger = structlog.get_logger(__name__)

_ACTIVE_BUILD_STATUSES = {"accepted", "running", "publishing"}


def _collect_graph_source_file_ids(structured_context: dict[str, object]) -> list[int]:
    """Resolve source file ids from persisted docs-sync context."""

    collected: list[int] = []
    seen: set[int] = set()
    chapters = structured_context.get("chapters")
    if not isinstance(chapters, list):
        return collected
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        raw_ids = chapter.get("source_file_ids")
        if not isinstance(raw_ids, list):
            continue
        for raw_id in raw_ids:
            try:
                parsed = int(raw_id)
            except (TypeError, ValueError):
                continue
            if parsed <= 0 or parsed in seen:
                continue
            seen.add(parsed)
            collected.append(parsed)
    return collected


def _storage_scope_for_subject_record(subject: Subject) -> SubjectStorageScope:
    """Build storage scope from the already-authorized subject record."""

    return build_subject_storage_scope(user_id=subject.user_id, subject=subject.slug)


async def _spawn_registered_task_after_response(
    request: Request,
    coro_factory,
    *,
    kind: str,
    subject: str,
    name: str,
) -> None:
    """Register a long-running workflow only after the HTTP response is flushed."""

    request.app.state.background_task_registry.spawn(
        coro_factory(),
        kind=kind,
        subject=subject,
        name=name,
    )


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
    response: Response,
    subject: str = Path(...),
    body: BuildPlannerCreateRequest = Body(...),
) -> StreamingResponse:
    normalized = normalize_subject_slug(subject)
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    logger.info(
        "planner_create_stream_requested",
        subject=normalized,
        user_id=user.user_id,
        file_uid_count=len(body.file_uids or []),
        user_prompt_preview=(body.user_prompt or "")[:80],
    )
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
    response: Response,
    subject: str = Path(...),
    session_id: str = Path(...),
    body: BuildPlannerMessageRequest = Body(...),
) -> StreamingResponse:
    normalized = normalize_subject_slug(subject)
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    logger.info(
        "planner_message_stream_requested",
        subject=normalized,
        session_id=session_id,
        user_id=user.user_id,
        message_preview=(body.message or "")[:80],
    )
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
    "/build/plans/{session_id}/adjust-click",
    response_model=ApiResponse[BuildPlannerAdjustClickResponse],
    summary="Record that the user opened planner adjustment mode",
    responses=build_error_responses([400, 404, 500]),
)
def knowledge_build_plan_adjust_click(
    subject: str = Path(...),
    session_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[BuildPlannerAdjustClickResponse]:
    normalized = normalize_subject_slug(subject)
    logger.info(
        "planner_adjust_click_requested",
        subject=normalized,
        session_id=session_id,
        user_id=user.user_id,
    )
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    data = record_build_planner_adjust_click(
        session,
        subject=subject_record,
        user_id=user.user_id,
        session_id=session_id,
    )
    return ok_response(BuildPlannerAdjustClickResponse.model_validate(data))


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
    summary="Trigger a knowledge-doc build with optional graph sync",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def knowledge_build(
    request: Request,
    background_tasks: BackgroundTasks,
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
        build_type=body.build_type,
        confirmed_plan_id=body.confirmed_plan_id,
        file_uid_count=len(body.file_uids or []),
    )
    subject_record = get_subject_record(
        session,
        normalized,
        owner_user_id=user.user_id,
    )

    data, accepted_file_ids, build_group_id = trigger_docgen_build(
        session,
        subject=subject_record,
        user_id=user.user_id,
        file_uids=body.file_uids,
        prompt=body.prompt,
        embedding_resolution=body.embedding_resolution,
        confirmed_plan_id=body.confirmed_plan_id,
    )

    logger.info(
        "knowledge_build_docs_background_spawning",
        subject=normalized,
        user_id=user.user_id,
        confirmed_plan_id=data.confirmed_plan_id,
        accepted_file_count=len(accepted_file_ids),
        requested_at=data.requested_at.isoformat(),
    )
    background_tasks.add_task(
        _spawn_registered_task_after_response,
        request,
        lambda: run_docgen_background(
            subject=normalized,
            file_ids=accepted_file_ids,
            prompt=data.prompt,
            requested_at=data.requested_at,
            build_group_id=build_group_id,
            planner_session_id=data.planner_session_id,
            confirmed_plan_id=data.confirmed_plan_id,
            user_id=user.user_id,
            background_task_registry=getattr(request.app.state, "background_task_registry", None),
        ),
        kind="knowledge.build.docs",
        subject=normalized,
        name=f"knowledge.build.docs:{normalized}",
    )
    logger.info(
        "knowledge_build_request_accepted",
        subject=normalized,
        user_id=user.user_id,
        build_type=body.build_type,
        confirmed_plan_id=data.confirmed_plan_id,
        accepted_file_count=len(accepted_file_ids),
        requested_at=data.requested_at.isoformat(),
    )
    return ok_response(data)


@router.post(
    "/build/graph",
    response_model=ApiResponse[KnowledgeGraphBuildData],
    summary="Rebuild the knowledge graph from the latest published knowledge docs",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def knowledge_graph_build(
    request: Request,
    background_tasks: BackgroundTasks,
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeGraphBuildData]:
    normalized = normalize_subject_slug(subject)
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    subject_scope = _storage_scope_for_subject_record(subject_record)

    runtime = read_knowledge_build_runtime(normalized, subject_scope=subject_scope)
    docgen_status = runtime.docgen_runtime if runtime is not None else None
    graph_status = runtime.graph_runtime if runtime is not None else None
    if docgen_status is not None and str(docgen_status.status or "").strip() in _ACTIVE_BUILD_STATUSES:
        raise AITeachMeError(
            detail="知识文档仍在构建中，请等待文档发布后再重建图谱。",
            error_code="DOCGEN_BUILD_IN_PROGRESS",
            status_code=409,
        )
    if graph_status is not None and str(graph_status.status or "").strip() in _ACTIVE_BUILD_STATUSES:
        raise AITeachMeError(
            detail="知识图谱正在构建中。",
            error_code="GRAPH_BUILD_IN_PROGRESS",
            status_code=409,
        )

    sync_input = load_knowledge_doc_sync_input(
        normalized,
        session=session,
        subject_scope=subject_scope,
    )
    if not sync_input.markdown.strip():
        raise AITeachMeError(
            detail="当前还没有已发布的知识文档，请先完成知识文档构建。",
            error_code="KNOWLEDGE_DOC_REQUIRED_FOR_GRAPH_BUILD",
            status_code=422,
        )

    manifest = read_knowledge_manifest(normalized, subject_scope=subject_scope)
    manifest_source_file_ids = list(manifest.source_file_ids) if manifest is not None else []
    source_file_ids = manifest_source_file_ids or _collect_graph_source_file_ids(sync_input.structured_context)
    prompt = manifest.prompt if manifest is not None else None
    requested_at = utcnow()
    build_group_id = uuid.uuid4().hex
    build_session_id = uuid.uuid4().hex
    doc_version_no = int(sync_input.structured_context.get("doc_version_no") or 0)
    chapters = sync_input.structured_context.get("chapters")
    chapter_count = len(chapters) if isinstance(chapters, list) else 0
    update_knowledge_build_lane_status(
        normalized,
        lane="graph",
        subject_scope=subject_scope,
        requested_at=requested_at,
        build_group_id=build_group_id,
        status="accepted",
        stage="manual_graph_requested",
        build_session_id=build_session_id,
        error_message=None,
        source_file_ids=source_file_ids,
        prompt=prompt,
        metrics={
            "knowledge_doc_source": sync_input.source,
            "knowledge_doc_chapter_count": chapter_count,
            "last_synced_doc_version_no": doc_version_no,
            "graph_input_paths": ["knowledge_doc"] + (["source_files"] if source_file_ids else []),
        },
        current_stage_description="已接收图谱重建请求，准备读取当前知识文档。",
    )
    llm_snapshot = capture_llm_runtime_snapshot()
    background_tasks.add_task(
        _spawn_registered_task_after_response,
        request,
        lambda: run_graph_docs_sync_manual_build(
            subject=normalized,
            requested_at=requested_at,
            build_group_id=build_group_id,
            build_session_id=build_session_id,
            file_ids=source_file_ids,
            prompt=prompt,
            llm_snapshot=llm_snapshot,
            subject_scope=subject_scope,
        ),
        kind="knowledge.build.graph",
        subject=normalized,
        name=f"knowledge.build.graph:{normalized}",
    )
    logger.info(
        "knowledge_graph_build_request_accepted",
        subject=normalized,
        user_id=user.user_id,
        requested_at=requested_at.isoformat(),
        build_group_id=build_group_id,
        build_session_id=build_session_id,
        source_file_count=len(source_file_ids),
    )
    return ok_response(
        KnowledgeGraphBuildData(
            subject=normalized,
            status="accepted",
            requested_at=requested_at,
            build_group_id=build_group_id,
            build_session_id=build_session_id,
            source_file_ids=source_file_ids,
        )
    )


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
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    subject_scope = _storage_scope_for_subject_record(subject_record)
    runtime = read_knowledge_build_runtime(normalized, subject_scope=subject_scope)
    aggregate_status = build_aggregate_knowledge_build_status(runtime)
    docgen_status = runtime.docgen_runtime if runtime is not None else None
    graph_status = runtime.graph_runtime if runtime is not None else None
    cancelled_task_count = 0
    registry = getattr(request.app.state, "background_task_registry", None)
    if registry is not None:
        cancelled_task_count += await registry.cancel_matching(kind="knowledge.build.docs", subject=normalized)
        cancelled_task_count += await registry.cancel_matching(kind="knowledge.build.graph", subject=normalized)

    requested_at = aggregate_status.requested_at if aggregate_status is not None else utcnow()
    confirmed_plan_id = docgen_status.confirmed_plan_id if docgen_status is not None else None
    if confirmed_plan_id:
        mark_confirmed_build_plan_status(
            session,
            subject=normalized,
            user_id=user.user_id,
            plan_id=confirmed_plan_id,
            status="cancelled",
        )
    if docgen_status is not None and (docgen_status.status or "").strip() in {"accepted", "running", "publishing"}:
        update_knowledge_build_lane_status(
            normalized,
            lane="docgen",
            subject_scope=subject_scope,
            requested_at=requested_at,
            build_group_id=docgen_status.build_group_id,
            status="cancelled",
            stage="cancelled",
            error_message="build_cancelled",
            draft_available=False,
            planner_session_id=docgen_status.planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=docgen_status.digest_mode,
            current_stage_description="本轮知识构建已被用户终止。",
        )
    if graph_status is not None and (graph_status.status or "").strip() in {"accepted", "running", "publishing"}:
        update_knowledge_build_lane_status(
            normalized,
            lane="graph",
            subject_scope=subject_scope,
            requested_at=requested_at,
            build_group_id=graph_status.build_group_id,
            status="cancelled",
            stage="cancelled",
            error_message="build_cancelled",
            current_stage_description="本轮图谱构建已被用户终止。",
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
    "/build/runtime",
    response_model=ApiResponse[KnowledgeBuildRuntimeResponse],
    summary="Fetch aggregate/docgen/graph runtime state",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_build_runtime(
    request: Request,
    response: Response,
    subject: str = Path(...),
) -> ApiResponse[KnowledgeBuildRuntimeResponse]:
    normalized = normalize_subject_slug(subject)
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
        subject_scope = _storage_scope_for_subject_record(subject_record)
    return ok_response(get_knowledge_build_runtime_result(subject=normalized, subject_scope=subject_scope))


@router.get(
    "/build/stream",
    summary="SSE stream for live build progress snapshots",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_build_stream(
    request: Request,
    response: Response,
    subject: str = Path(...),
) -> StreamingResponse:
    """SSE endpoint for live build runtime, direct deltas and fallback snapshots."""
    import hashlib
    import json

    normalized = normalize_subject_slug(subject)
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
        subject_scope = _storage_scope_for_subject_record(subject_record)

    _TERMINAL_STATUSES = {"completed", "failed", "cancelled", "partial_failed", "skipped"}
    _SNAPSHOT_FALLBACK_INTERVAL = 8.0

    async def event_generator():
        last_hash: str | None = None
        last_preview_text_by_chapter: dict[int, str] = {}

        def remember_preview_delta(payload: dict[str, object]) -> bool:
            chapter_index = int(payload.get("chapter_index") or 0)
            if chapter_index <= 0:
                return False
            text = str(payload.get("text") or "")
            if not text:
                return False
            previous = last_preview_text_by_chapter.get(chapter_index, "")
            full_length = int(payload.get("full_length") or 0)
            if full_length > 0 and len(previous) >= full_length:
                return False
            mode = str(payload.get("mode") or "replace")
            base_length = int(payload.get("base_length") or -1)
            if mode == "append" and base_length >= 0 and base_length != len(previous):
                return False
            next_text = f"{previous}{text}" if mode == "append" and previous else text
            last_preview_text_by_chapter[chapter_index] = next_text
            return True

        def build_preview_delta_payloads(result: KnowledgeBuildRuntimeResponse) -> list[dict[str, object]]:
            payloads: list[dict[str, object]] = []
            preview = result.docgen_preview
            if preview is None:
                return payloads
            for chapter_preview in list(preview.chapter_previews or []):
                chapter_index = int(chapter_preview.chapter_index or 0)
                if chapter_index <= 0:
                    continue
                text = str(chapter_preview.excerpt or "")
                previous = last_preview_text_by_chapter.get(chapter_index, "")
                if not text or text == previous:
                    continue
                mode = "append" if previous and text.startswith(previous) else "replace"
                payload = {
                    "kind": "chapter_preview",
                    "chapter_index": chapter_index,
                    "title": chapter_preview.title,
                    "status": chapter_preview.status,
                    "mode": mode,
                    "base_length": len(previous),
                    "text": text[len(previous):] if mode == "append" else text,
                    "full_length": len(text),
                    "updated_at": (
                        chapter_preview.updated_at.isoformat()
                        if chapter_preview.updated_at is not None
                        else None
                    ),
                }
                last_preview_text_by_chapter[chapter_index] = text
                payloads.append(payload)
            return payloads

        async def build_snapshot_events(*, force: bool = False) -> tuple[list[str], bool]:
            nonlocal last_hash
            try:
                with managed_session() as snapshot_session:
                    result = get_knowledge_build_runtime_result(
                        snapshot_session,
                        subject=normalized,
                        subject_scope=subject_scope,
                    )
            except Exception:
                return [], False

            events: list[str] = []
            for payload in build_preview_delta_payloads(result):
                events.append(format_sse_event("preview_delta", payload))
            snapshot_json = result.model_dump_json(exclude_none=True)
            current_hash = hashlib.md5(snapshot_json.encode()).hexdigest()
            if force or current_hash != last_hash:
                last_hash = current_hash
                events.append(f"event: snapshot\ndata: {snapshot_json}\n\n")

            agg = result.aggregate
            status = (agg.status if agg is not None else "idle").strip()
            if status in _TERMINAL_STATUSES:
                events.append(f"event: done\ndata: {json.dumps({'status': status}, ensure_ascii=False)}\n\n")
                return events, True
            return events, False

        def should_forward_direct_event(event: WorkflowStreamEvent) -> bool:
            if event.event != "preview_delta":
                return True
            return remember_preview_delta(event.data)

        with subscribe_workflow_stream(normalized) as queue:
            events, terminal = await build_snapshot_events(force=True)
            for payload in events:
                yield payload
            if terminal:
                return

            while True:
                if await request.is_disconnected():
                    break
                try:
                    stream_event = await asyncio.wait_for(
                        queue.get(),
                        timeout=_SNAPSHOT_FALLBACK_INTERVAL,
                    )
                except asyncio.TimeoutError:
                    events, terminal = await build_snapshot_events(force=False)
                    if events:
                        for payload in events:
                            yield payload
                    else:
                        yield "event: ping\ndata: {}\n\n"
                    if terminal:
                        break
                    continue

                if stream_event.event == "runtime_dirty":
                    events, terminal = await build_snapshot_events(force=False)
                    for payload in events:
                        yield payload
                    if terminal:
                        break
                    continue

                if should_forward_direct_event(stream_event):
                    yield format_sse_event(stream_event.event, stream_event.data)

    stream_response = StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
    for key, value in response.raw_headers:
        if key.lower() == b"set-cookie":
            stream_response.raw_headers.append((key, value))
    return stream_response


@router.post(
    "/docs",
    response_model=ApiResponse[DocGenGetResponse],
    summary="Fetch knowledge docs and minimal build state",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_docs(
    request: Request,
    response: Response,
    subject: str = Path(...),
) -> ApiResponse[DocGenGetResponse]:
    normalized = normalize_subject_slug(subject)
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
        subject_scope = _storage_scope_for_subject_record(subject_record)
    return ok_response(get_docgen_result(subject=normalized, subject_scope=subject_scope))


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
