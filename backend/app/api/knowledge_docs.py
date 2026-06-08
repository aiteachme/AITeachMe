"""Knowledge docs API routes."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request, Response
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from app.api.deps import (
    CurrentUserContext,
    get_current_user_context,
    get_db,
    normalize_course_id,
)
from app.api.openapi import build_error_responses
from app.api.sse import get_sse_interval, sse_headers
from app.models import Course
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
    KnowledgeDocInteractiveSelectionRequest,
    KnowledgeDocInteractiveSelectionResponse,
    KnowledgeGraphBuildData,
    KnowledgeOverviewRequest,
    KnowledgeOverviewResponse,
)
from app.workflows.digest.planner import (
    append_build_planner_message,
    confirm_build_planner_session,
    create_build_planner_session,
    get_latest_planner_session,
    record_build_planner_adjust_click,
)
from app.workflows.support.auth import set_guest_cookie_for_user
from app.workflows.digest.common.build_lifecycle import cancel_knowledge_build
from app.workflows.digest.docgen import (
    clear_course_knowledge,
    get_docgen_result,
    get_knowledge_build_runtime_result,
    run_docgen_background,
    trigger_docgen_build,
)
from app.workflows.digest.kg_doc_sync import (
    get_knowledge_overview,
    trigger_graph_docs_sync_manual_build,
)
from app.workflows.support.courses import get_course_record
from app.workflows.interact.chat.lib.streaming import SSEEventEmitter
from app.shared.infra.database import managed_session
from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.analytics.posthog import capture_course_build_event_later
from app.shared.infra.llm_support import run_llm_tasks
from app.shared.infra.observability.trace import (
    langsmith_trace,
    llm_trace_scope,
    sanitize_langsmith_input,
    sanitize_langsmith_output,
)
from app.shared.infra.workflow.live_stream import (
    WorkflowStreamEvent,
    format_sse_event,
    subscribe_workflow_stream,
)
from app.shared.infra.storage import CourseStorageScope, build_course_storage_scope
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib.interactive_html import generate_selection_interactive_html_asset
from app.workflows.digest.docgen.lib.interactive_overlays import (
    append_interactive_overlay,
    build_overlay_markdown_block,
    find_interactive_overlay_by_client_reference,
    interactive_overlay_reference_guard,
    overlay_preview_url,
)
from app.workflows.digest.docgen.lib.published_manifest import ensure_published_knowledge_manifest

router = APIRouter(tags=["knowledge"])
logger = structlog.get_logger(__name__)


def _interactive_generation_origin(client_reference_id: str | None) -> str:
    normalized = str(client_reference_id or "").strip()
    return "planned_auto" if normalized.startswith("ch") and "_interactive_" in normalized else "selection"


def _interactive_selection_response_from_overlay(
    overlay: dict[str, object],
    *,
    fallback_version_no: int,
) -> KnowledgeDocInteractiveSelectionResponse | None:
    asset_path = str(overlay.get("asset_path") or "").strip()
    preview_url = overlay_preview_url(
        str(overlay.get("preview_url") or "").strip(),
        client_reference_id=str(overlay.get("client_reference_id") or "").strip(),
        overlay_id=str(overlay.get("overlay_id") or "").strip(),
        anchor_id=str(overlay.get("anchor_id") or "").strip(),
        selected_text=str(overlay.get("selected_text") or "").strip(),
    )
    if not asset_path or not preview_url:
        return None
    normalized_overlay = dict(overlay)
    normalized_overlay["preview_url"] = preview_url
    link_markdown = build_overlay_markdown_block(normalized_overlay)
    return KnowledgeDocInteractiveSelectionResponse(
        overlay_id=str(overlay.get("overlay_id") or ""),
        anchor_id=str(overlay.get("anchor_id") or ""),
        title=str(overlay.get("title") or "交互演示"),
        asset_path=asset_path,
        preview_url=preview_url,
        link_markdown=link_markdown,
        version_no=int(overlay.get("version_no") or fallback_version_no or 0),
    )


def _storage_scope_for_course_record(course: Course) -> CourseStorageScope:
    """Build storage scope from the already-authorized course record."""

    return build_course_storage_scope(user_id=course.user_id, course_id=course.id)


def _suffix(value: str | None, *, length: int = 8) -> str | None:
    normalized = str(value or "").strip()
    return normalized[-length:] if normalized else None


def _request_id(request: Request | object) -> str:
    state = getattr(request, "state", None)
    value = getattr(state, "request_id", None)
    return str(value or "").strip() or uuid.uuid4().hex


def _planner_plan_analytics_properties(plan: object | None) -> dict[str, object]:
    if plan is None:
        return {
            "chapter_count": 0,
            "has_plan": False,
            "has_suggestion": False,
        }
    return {
        "chapter_count": len(getattr(plan, "chapters", []) or []),
        "digest_mode": getattr(plan, "digest_mode", None),
        "has_planning_note": bool(str(getattr(plan, "planning_note", "") or "").strip()),
        "has_plan": bool(str(getattr(plan, "plan", "") or "").strip()),
        "has_suggestion": bool(str(getattr(plan, "suggestion", "") or "").strip()),
    }


def _planner_response_analytics_properties(response: BuildPlannerSessionResponse) -> dict[str, object]:
    return {
        **_planner_plan_analytics_properties(response.latest_plan),
        "has_planner_session": bool(response.session_id),
        "planner_session_id_suffix": _suffix(response.session_id),
    }


def _capture_course_build_event(
    event: str,
    *,
    course_id: str,
    user_id: str,
    insert_id_parts: list[str],
    properties: dict[str, object] | None = None,
) -> None:
    capture_course_build_event_later(
        event,
        course_id=course_id,
        user_id=user_id,
        insert_id_parts=insert_id_parts,
        properties=properties,
    )


def _planner_stream_response(
    *,
    request: Request,
    user_id: str,
    runner,
    on_success=None,
) -> StreamingResponse:
    emitter = SSEEventEmitter()

    async def workflow_task() -> None:
        logger.info("planner_stream_task_started", user_id=user_id)
        try:
            await emitter.emit_event(
                "status",
                {
                    "stage": "accepted",
                    "detail": "已收到请求，马上开始拆解学习目标和资料边界。",
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
            if on_success is not None:
                on_success(response)
            logger.info(
                "planner_stream_runner_completed",
                user_id=user_id,
                session_id=getattr(response, "session_id", ""),
                status=getattr(response, "status", ""),
            )
            await emitter.emit_event(
                "status",
                {
                    "stage": "completed",
                    "detail": "构建方案已生成。",
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
        headers=sse_headers(),
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
    request: Request,
    course_id: str = Path(...),
    body: BuildPlannerCreateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[BuildPlannerSessionResponse]:
    normalized = normalize_course_id(course_id)
    course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    _capture_course_build_event(
        "course_plan_requested",
        course_id=normalized,
        user_id=user.user_id,
        insert_id_parts=[_request_id(request), "create", "api"],
        properties={
            "file_count": len(body.file_ids or []),
            "has_prompt": bool((body.user_prompt or "").strip()),
            "mode": "create",
            "model_override_present": bool((body.model or "").strip()),
            "source": "api",
        },
    )
    data = await create_build_planner_session(
        course=course_record,
        user_id=user.user_id,
        payload=body,
    )
    _capture_course_build_event(
        "course_plan_generated",
        course_id=normalized,
        user_id=user.user_id,
        insert_id_parts=[data.session_id, str(data.revision), data.updated_at.isoformat()],
        properties={
            **_planner_response_analytics_properties(data),
            "file_count": len(body.file_ids or []),
            "mode": "create",
            "model_override_present": bool(data.model_override),
            "source": "api",
        },
    )
    return ok_response(data)


@router.post(
    "/build/plans/latest",
    response_model=ApiResponse[BuildPlannerSessionResponse | None],
    summary="Get the latest build planner session for this course",
    responses=build_error_responses([400, 404, 500]),
)
def knowledge_build_plan_latest(
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[BuildPlannerSessionResponse | None]:
    normalized = normalize_course_id(course_id)
    logger.info("planner_latest_requested", course_id=normalized, user_id=user.user_id)
    course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    data = get_latest_planner_session(
        session,
        course=course_record,
        user_id=user.user_id,
    )
    logger.info(
        "planner_latest_completed",
        course_id=normalized,
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
    course_id: str = Path(...),
    body: BuildPlannerCreateRequest = Body(...),
) -> StreamingResponse:
    normalized = normalize_course_id(course_id)
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    logger.info(
        "planner_create_stream_requested",
        course_id=normalized,
        user_id=user.user_id,
        file_id_count=len(body.file_ids or []),
        user_prompt_preview=(body.user_prompt or "")[:80],
    )
    _capture_course_build_event(
        "course_plan_requested",
        course_id=normalized,
        user_id=user.user_id,
        insert_id_parts=[_request_id(request), "create", "stream"],
        properties={
            "file_count": len(body.file_ids or []),
            "has_prompt": bool((body.user_prompt or "").strip()),
            "mode": "create",
            "model_override_present": bool((body.model or "").strip()),
            "source": "stream",
        },
    )

    def on_success(data: BuildPlannerSessionResponse) -> None:
        _capture_course_build_event(
            "course_plan_generated",
            course_id=normalized,
            user_id=user.user_id,
            insert_id_parts=[data.session_id, str(data.revision), data.updated_at.isoformat()],
            properties={
                **_planner_response_analytics_properties(data),
                "file_count": len(body.file_ids or []),
                "mode": "create",
                "model_override_present": bool(data.model_override),
                "source": "stream",
            },
        )

    return _planner_stream_response(
        request=request,
        user_id=user.user_id,
        runner=lambda progress_callback, token_callback: create_build_planner_session(
            course=course_record,
            user_id=user.user_id,
            payload=body,
            progress_callback=progress_callback,
            token_callback=token_callback,
        ),
        on_success=on_success,
    )


@router.post(
    "/build/plans/{session_id}/messages",
    response_model=ApiResponse[BuildPlannerSessionResponse],
    summary="Append planner feedback and regenerate the plan",
    responses=build_error_responses([400, 404, 422, 500]),
)
async def knowledge_build_plan_message(
    request: Request,
    course_id: str = Path(...),
    session_id: str = Path(...),
    body: BuildPlannerMessageRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[BuildPlannerSessionResponse]:
    normalized = normalize_course_id(course_id)
    course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    _capture_course_build_event(
        "course_plan_requested",
        course_id=normalized,
        user_id=user.user_id,
        insert_id_parts=[_request_id(request), session_id, "revise", "api"],
        properties={
            "has_prompt": bool((body.message or "").strip()),
            "mode": "revise",
            "model_override_present": bool((body.model or "").strip()),
            "planner_session_id_suffix": _suffix(session_id),
            "source": "api",
        },
    )
    data = await append_build_planner_message(
        course=course_record,
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
    course_id: str = Path(...),
    session_id: str = Path(...),
    body: BuildPlannerMessageRequest = Body(...),
) -> StreamingResponse:
    normalized = normalize_course_id(course_id)
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    logger.info(
        "planner_message_stream_requested",
        course_id=normalized,
        session_id=session_id,
        user_id=user.user_id,
        message_preview=(body.message or "")[:80],
    )
    _capture_course_build_event(
        "course_plan_requested",
        course_id=normalized,
        user_id=user.user_id,
        insert_id_parts=[_request_id(request), session_id, "revise", "stream"],
        properties={
            "has_prompt": bool((body.message or "").strip()),
            "mode": "revise",
            "model_override_present": bool((body.model or "").strip()),
            "planner_session_id_suffix": _suffix(session_id),
            "source": "stream",
        },
    )
    return _planner_stream_response(
        request=request,
        user_id=user.user_id,
        runner=lambda progress_callback, token_callback: append_build_planner_message(
            course=course_record,
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
    course_id: str = Path(...),
    session_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[BuildPlannerAdjustClickResponse]:
    normalized = normalize_course_id(course_id)
    logger.info(
        "planner_adjust_click_requested",
        course_id=normalized,
        session_id=session_id,
        user_id=user.user_id,
    )
    course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    data = record_build_planner_adjust_click(
        session,
        course=course_record,
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
    request: Request,
    course_id: str = Path(...),
    session_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[BuildPlannerConfirmResponse]:
    normalized = normalize_course_id(course_id)
    logger.info(
        "knowledge_build_plan_confirm_requested",
        course_id=normalized,
        session_id=session_id,
        user_id=user.user_id,
    )
    course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    data = confirm_build_planner_session(
        session,
        course=course_record,
        user_id=user.user_id,
        session_id=session_id,
    )
    logger.info(
        "knowledge_build_plan_confirm_completed",
        course_id=normalized,
        session_id=session_id,
        confirmed_plan_id=data.confirmed_plan_id,
        user_id=user.user_id,
    )
    _capture_course_build_event(
        "course_build_plan_confirmed",
        course_id=normalized,
        user_id=user.user_id,
        insert_id_parts=[data.confirmed_plan_id, data.updated_at.isoformat()],
        properties={
            "chapter_count": len(data.chapters or []),
            "confirmed_plan_id_suffix": _suffix(data.confirmed_plan_id),
            "digest_mode": data.digest_mode,
            "has_plan": bool((data.plan or "").strip()),
            "model_override_present": bool(data.model_override),
            "planner_session_id_suffix": _suffix(data.planner_session_id or session_id),
            "selected_file_count": len(data.selected_file_ids or []),
            "version_no": data.version_no,
        },
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
    course_id: str = Path(...),
    body: DocGenBuildRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[DocGenBuildData]:
    normalized = normalize_course_id(course_id)
    logger.info(
        "knowledge_build_request_received",
        course_id=normalized,
        user_id=user.user_id,
        build_type=body.build_type,
        confirmed_plan_id=body.confirmed_plan_id,
        file_id_count=len(body.file_ids or []),
    )
    course_record = get_course_record(
        session,
        normalized,
        owner_user_id=user.user_id,
    )

    data, accepted_file_ids, build_group_id = trigger_docgen_build(
        session,
        course=course_record,
        user_id=user.user_id,
        file_ids=body.file_ids,
        prompt=body.prompt,
        embedding_resolution=body.embedding_resolution,
        confirmed_plan_id=body.confirmed_plan_id,
    )
    _capture_course_build_event(
        "knowledge_build_submitted",
        course_id=normalized,
        user_id=user.user_id,
        insert_id_parts=[
            _request_id(request),
            data.confirmed_plan_id or "",
            data.requested_at.isoformat(),
            "submitted",
        ],
        properties={
            "build_type": body.build_type,
            "confirmed_plan_id_suffix": _suffix(data.confirmed_plan_id),
            "file_count": len(body.file_ids or []),
            "has_confirmed_plan": bool(data.confirmed_plan_id),
            "has_prompt": bool((body.prompt or "").strip()),
            "embedding_resolution": body.embedding_resolution,
        },
    )

    logger.info(
        "knowledge_build_docs_background_spawning",
        course_id=normalized,
        user_id=user.user_id,
        confirmed_plan_id=data.confirmed_plan_id,
        accepted_file_count=len(accepted_file_ids),
        requested_at=data.requested_at.isoformat(),
    )
    request.app.state.background_task_registry.spawn(
        run_docgen_background(
            course_id=normalized,
            course_name=course_record.name,
            file_ids=accepted_file_ids,
            prompt=data.prompt,
            requested_at=data.requested_at,
            build_group_id=build_group_id,
            planner_session_id=data.planner_session_id,
            confirmed_plan_id=data.confirmed_plan_id,
            model_override=data.model_override,
            user_id=user.user_id,
            background_task_registry=getattr(request.app.state, "background_task_registry", None),
        ),
        kind="knowledge.build.docs",
        course_id=normalized,
        name=f"knowledge.build.docs:{normalized}",
    )
    _capture_course_build_event(
        "knowledge_build_started",
        course_id=normalized,
        user_id=user.user_id,
        insert_id_parts=[build_group_id, data.requested_at.isoformat(), "started"],
        properties={
            "accepted_file_count": len(accepted_file_ids),
            "build_group_id_suffix": _suffix(build_group_id),
            "build_type": body.build_type,
            "confirmed_plan_id_suffix": _suffix(data.confirmed_plan_id),
            "digest_mode": data.digest_mode,
            "has_confirmed_plan": bool(data.confirmed_plan_id),
            "has_planner_session": bool(data.planner_session_id),
            "model_override_present": bool(data.model_override),
            "planner_session_id_suffix": _suffix(data.planner_session_id),
            "ready_file_count": data.ready_file_count,
            "vector_mode": data.vector_status.mode,
        },
    )
    logger.info(
        "knowledge_build_request_accepted",
        course_id=normalized,
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
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeGraphBuildData]:
    normalized = normalize_course_id(course_id)
    course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    data = trigger_graph_docs_sync_manual_build(
        session,
        course=course_record,
        background_task_registry=getattr(request.app.state, "background_task_registry", None),
    )
    return ok_response(data)


@router.post(
    "/build/cancel",
    response_model=ApiResponse[DocGenBuildCancelData],
    summary="Cancel the active digest build for this course",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_build_cancel(
    request: Request,
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[DocGenBuildCancelData]:
    normalized = normalize_course_id(course_id)
    course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    data = await cancel_knowledge_build(
        session,
        course=course_record,
        user_id=user.user_id,
        background_task_registry=getattr(request.app.state, "background_task_registry", None),
    )
    return ok_response(data)


@router.post(
    "/build/runtime",
    response_model=ApiResponse[KnowledgeBuildRuntimeResponse],
    summary="Fetch aggregate/docgen/graph runtime state",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_build_runtime(
    request: Request,
    response: Response,
    course_id: str = Path(...),
) -> ApiResponse[KnowledgeBuildRuntimeResponse]:
    normalized = normalize_course_id(course_id)
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
        course_scope = _storage_scope_for_course_record(course_record)
    return ok_response(get_knowledge_build_runtime_result(course_id=normalized, course_scope=course_scope))


@router.get(
    "/build/stream",
    summary="SSE stream for live build progress snapshots",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_build_stream(
    request: Request,
    response: Response,
    course_id: str = Path(...),
) -> StreamingResponse:
    """SSE endpoint for live build runtime, direct deltas and fallback snapshots."""
    import hashlib
    import json

    normalized = normalize_course_id(course_id)
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
        course_scope = _storage_scope_for_course_record(course_record)

    _TERMINAL_STATUSES = {"completed", "failed", "cancelled", "partial_failed", "skipped"}
    snapshot_fallback_interval_s = get_sse_interval(
        "SSE_BUILD_SNAPSHOT_FALLBACK_INTERVAL_S",
        default=2.0,
    )

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
            mode = str(payload.get("mode") or "replace")
            base_length = int(payload.get("base_length") or -1)
            if mode == "append":
                full_length = int(payload.get("full_length") or 0)
                if full_length > 0 and len(previous) >= full_length:
                    return False
                if base_length >= 0 and base_length != len(previous):
                    return False
                next_text = f"{previous}{text}"
            else:
                if text == previous:
                    return False
                next_text = text
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
                status = str(chapter_preview.status or "").strip()
                if status in {"generating", "drafting"} and previous and len(text) < len(previous):
                    continue
                mode = "append" if previous and text.startswith(previous) else "replace"
                payload = {
                    "kind": "chapter_preview",
                    "chapter_index": chapter_index,
                    "title": chapter_preview.title,
                    "status": status,
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
                        course_id=normalized,
                        course_scope=course_scope,
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
                        timeout=snapshot_fallback_interval_s,
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
        headers=sse_headers(),
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
    course_id: str = Path(...),
) -> ApiResponse[DocGenGetResponse]:
    normalized = normalize_course_id(course_id)
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
        course_scope = _storage_scope_for_course_record(course_record)
    return ok_response(get_docgen_result(course_id=normalized, course_scope=course_scope))


@router.post(
    "/docs/interactive-selections",
    response_model=ApiResponse[KnowledgeDocInteractiveSelectionResponse],
    summary="Generate an interactive HTML block from a knowledge-doc text selection",
    responses=build_error_responses([400, 404, 409, 422, 500]),
)
async def knowledge_docs_interactive_selection(
    course_id: str = Path(...),
    body: KnowledgeDocInteractiveSelectionRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeDocInteractiveSelectionResponse]:
    normalized = normalize_course_id(course_id)
    course_record = get_course_record(session, normalized, owner_user_id=user.user_id)
    course_scope = _storage_scope_for_course_record(course_record)
    manifest = ensure_published_knowledge_manifest(session, course_id=normalized, course_scope=course_scope)
    if manifest is None:
        raise HTTPException(status_code=409, detail="请先完成知识文档生成后再创建交互演示。")

    selection_context = body.selection_context
    heading_path = [
        str(item).strip()[:240]
        for item in (selection_context.heading_path if selection_context else [])[:12]
        if str(item).strip()
    ]
    anchor_title = (
        (selection_context.anchor_title if selection_context else None)
        or (selection_context.section_title if selection_context else None)
        or (heading_path[-1] if heading_path else "")
    )
    nearby_context = ""
    if selection_context is not None:
        nearby_context = "\n\n".join(
            item
            for item in [
                selection_context.before_text or "",
                body.selected_text,
                selection_context.after_text or "",
                selection_context.section_excerpt or "",
            ]
            if item.strip()
        )

    version_no = int(manifest.version_no or 0)
    requested_client_reference_id = str(body.client_reference_id or "").strip()
    client_reference_id = requested_client_reference_id or f"selection:{uuid.uuid4().hex[:16]}"
    interactive_origin = _interactive_generation_origin(requested_client_reference_id)
    interactive_batch_id = f"{normalized}:knowledge-docs:v{version_no}:interactive-html"
    build_session_id = (
        f"auto-interactive-v{version_no}"
        if interactive_origin == "planned_auto"
        else f"selection-{uuid.uuid4().hex[:12]}"
    )
    workflow_context = WorkflowContext(
        workflow_name="digest.docgen.selection_interactive",
        course_id=normalized,
        metadata={
            "lane": "docgen",
            "course_id": normalized,
            "user_id": user.user_id,
            "asset_kind": "interactive_html",
            "anchor_id": body.anchor_id,
            "client_reference_id": client_reference_id,
            "interactive_batch_id": interactive_batch_id,
            "interactive_origin": interactive_origin,
            "version_no": version_no,
            "force_regenerate": body.force_regenerate,
            "replace_overlay_id": body.replace_overlay_id or "",
        },
    )
    traced_context = TracedExecutionContext(
        course_id=normalized,
        build_session_id=build_session_id,
        workflow_context=workflow_context,
        teaching_action="selection_interactive_html",
        asset_kind="interactive_html",
        extra_metadata={
            "anchor_id": body.anchor_id,
            "client_reference_id": client_reference_id,
            "interactive_batch_id": interactive_batch_id,
            "interactive_origin": interactive_origin,
            "version_no": version_no,
            "force_regenerate": body.force_regenerate,
            "replace_overlay_id": body.replace_overlay_id or "",
        },
    )

    async def _generate_interactive_asset() -> dict[str, object]:
        trace_metadata = traced_context.trace_metadata(
            docgen_stage="interactive_html_generation",
            selected_chars=len(body.selected_text or ""),
            prompt_chars=len(body.prompt or ""),
        )
        trace_inputs = sanitize_langsmith_input(
            {
                "anchor_id": body.anchor_id,
                "anchor_title": str(anchor_title or ""),
                "heading_path": heading_path,
                "selected_text_preview": body.selected_text[:800],
                "prompt": body.prompt or "",
                "client_reference_id": client_reference_id,
                "interactive_origin": interactive_origin,
                "force_regenerate": body.force_regenerate,
                "replace_overlay_id": body.replace_overlay_id or "",
            },
            field_name="interactive_html_generation_inputs",
        )
        with llm_trace_scope(
            course_id=normalized,
            build_session_id=build_session_id,
            workflow=workflow_context.workflow_name,
            lane="docgen",
            node="knowledge_docs.interactive_html_generation",
        ):
            with langsmith_trace(
                name=(
                    "DocGen：默认交互 HTML 懒加载"
                    if interactive_origin == "planned_auto"
                    else "DocGen：划选交互 HTML 生成"
                ),
                run_type="chain",
                inputs=trace_inputs,
                course_id=normalized,
                build_session_id=build_session_id,
                workflow=workflow_context.workflow_name,
                lane="docgen",
                node="knowledge_docs.interactive_html_generation",
                extra_metadata=trace_metadata,
                extra_tags=[
                    "docgen:interactive_html",
                    f"interactive_origin:{interactive_origin}",
                ],
            ) as trace_run:
                asset = await generate_selection_interactive_html_asset(
                    course_id=normalized,
                    course_scope=course_scope,
                    traced_context=traced_context,
                    anchor_title=str(anchor_title or ""),
                    heading_path=heading_path,
                    selected_text=body.selected_text,
                    user_prompt=body.prompt or "",
                    section_excerpt=nearby_context[:5000],
                )
                if trace_run is not None:
                    trace_run.end(
                        outputs=sanitize_langsmith_output(
                            {
                                "title": asset.get("title"),
                                "asset_path": asset.get("asset_path"),
                                "preview_url": asset.get("preview_url"),
                                "validation_issue_count": len(asset.get("validation_issues") or []),
                            },
                            field_name="interactive_html_generation_outputs",
                        )
                    )
                return asset

    async with interactive_overlay_reference_guard(
        course_scope,
        version_no=version_no,
        client_reference_id=client_reference_id,
    ):
        existing_overlay = await find_interactive_overlay_by_client_reference(
            course_scope,
            version_no=version_no,
            client_reference_id=client_reference_id,
        )
        if existing_overlay is not None and not body.force_regenerate:
            existing_response = _interactive_selection_response_from_overlay(
                existing_overlay,
                fallback_version_no=version_no,
            )
            if existing_response is not None:
                return ok_response(existing_response)

        try:
            asset = (
                await run_llm_tasks(
                    [None],
                    lambda _item: _generate_interactive_asset(),
                )
            )[0]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.warning(
                "knowledge_doc_interactive_generation_failed",
                course_id=normalized,
                anchor_id=body.anchor_id,
                error=str(exc)[:240],
            )
            raise HTTPException(
                status_code=503,
                detail="交互页生成暂时失败，可能是模型服务连接中断。请稍后重试或输入改进要求后重新生成。",
            ) from exc
        overlay_id = f"interactive-{uuid.uuid4().hex}"
        preview_url = overlay_preview_url(
            str(asset["preview_url"]),
            client_reference_id=client_reference_id,
            overlay_id=overlay_id,
            anchor_id=body.anchor_id,
            selected_text=body.selected_text,
        )
        overlay = {
            "overlay_id": overlay_id,
            "version_no": version_no,
            "anchor_id": body.anchor_id,
            "anchor_title": str(anchor_title or ""),
            "heading_path": heading_path,
            "selected_text": body.selected_text,
            "user_prompt": body.prompt or "",
            "client_reference_id": client_reference_id,
            "title": str(asset["title"]),
            "asset_path": str(asset["asset_path"]),
            "preview_url": preview_url,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        link_markdown = build_overlay_markdown_block(overlay)
        overlay["link_markdown"] = link_markdown
        await append_interactive_overlay(
            course_scope,
            overlay=overlay,
            replace_overlay_id=body.replace_overlay_id,
        )

        return ok_response(
            KnowledgeDocInteractiveSelectionResponse(
                overlay_id=overlay_id,
                anchor_id=body.anchor_id,
                title=str(asset["title"]),
                asset_path=str(asset["asset_path"]),
                preview_url=preview_url,
                link_markdown=link_markdown,
                version_no=version_no,
            )
        )


@router.post(
    "/overview",
    response_model=ApiResponse[KnowledgeOverviewResponse],
    summary="Fetch aggregated knowledge overview",
    responses=build_error_responses([400, 404, 500]),
)
async def knowledge_overview(
    course_id: str = Path(...),
    body: KnowledgeOverviewRequest = Body(default=KnowledgeOverviewRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[KnowledgeOverviewResponse]:
    normalized = normalize_course_id(course_id)
    get_course_record(session, normalized, owner_user_id=user.user_id)
    return ok_response(
        get_knowledge_overview(
            session,
            course_id=normalized,
            include=body.include,
            full=body.full,
        )
    )


@router.post(
    "/clear",
    response_model=ApiResponse[ClearKnowledgeResponse],
    summary="Clear knowledge artifacts for one course",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def knowledge_clear(
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ClearKnowledgeResponse]:
    normalized = normalize_course_id(course_id)
    get_course_record(session, normalized, owner_user_id=user.user_id)
    counts = clear_course_knowledge(session, course_id=normalized)
    return ok_response(ClearKnowledgeResponse(course_id=normalized, deleted_counts=counts))
