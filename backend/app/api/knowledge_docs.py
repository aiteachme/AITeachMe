"""Knowledge docs API routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, Depends, Path, Request
from fastapi.responses import StreamingResponse
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
    DocGenBuildData,
    DocGenBuildRequest,
    DocGenGetResponse,
    KnowledgeOverviewRequest,
    KnowledgeOverviewResponse,
    StudyPlanRequest,
    StudyPlanResponse,
)
from app.services.knowledge_docs.build_planner_service import (
    append_build_planner_message_service,
    confirm_build_planner_session_service,
    create_build_planner_session_service,
    get_latest_planner_session_service,
)
from app.services.auth_service import set_guest_cookie_for_user
from app.services.knowledge_docs.cleanup_service import clear_subject_knowledge
from app.services.knowledge_docs.digest_service import (
    get_docgen_result,
    run_docgen_background,
    run_unified_build_background,
    trigger_docgen_build,
)
from app.services.knowledge_docs.overview_service import get_knowledge_overview
from app.services.knowledge_docs.study_plan_service import handle_study_plan_request
from app.services.knowledge_graph.digest_service import run_graph_build_background
from app.services.subject_service import get_subject_record
from app.workflows.interact.chat.lib.streaming import SSEEventEmitter

router = APIRouter(tags=["knowledge"])


def _planner_status_detail(payload: dict[str, object]) -> str:
    node_name = str(payload.get("node_name") or "").strip()
    elapsed_ms = int(payload.get("elapsed_ms", 0) or 0)
    status = str(payload.get("status") or "ok").strip() or "ok"
    if node_name:
        if status == "failed":
            return f"{node_name} failed in {elapsed_ms} ms."
        return f"{node_name} finished in {elapsed_ms} ms."
    return "Generating build plan..."


def _planner_stream_response(
    *,
    request: Request,
    user_id: str,
    runner,
) -> StreamingResponse:
    emitter = SSEEventEmitter()

    async def workflow_task() -> None:
        try:
            await emitter.emit_event(
                "status",
                {
                    "stage": "accepted",
                    "detail": "Request accepted. Reading files and user goal.",
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
                        f"Plan generated in {elapsed_ms} ms."
                        if runtime_stats is not None
                        else "Plan generated."
                    ),
                    "elapsed_ms": elapsed_ms,
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
    data = await create_build_planner_session_service(
        session,
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
    subject_record = get_subject_record(session, normalized, owner_user_id=user.user_id)
    data = get_latest_planner_session_service(
        session,
        subject=subject_record,
        user_id=user.user_id,
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
        user_id=user.user_id,
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
        user_id=user.user_id,
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
