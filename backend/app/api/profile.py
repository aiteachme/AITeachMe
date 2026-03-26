"""Profile API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, ok_response
from app.schemas.profile import MasteryOverviewResponse, MasteryStateResponse, ReviewTaskResponse
from app.services.profile_service import complete_review_task, get_mastery_detail, get_mastery_overview, get_review_tasks
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/profile", tags=["profile"])


def _to_mastery_state_response(state) -> MasteryStateResponse:
    return MasteryStateResponse(
        id=state.id or 0,
        granularity=state.granularity,
        target_id=state.target_id,
        mastery_score=state.mastery_score,
        confidence_score=state.confidence_score,
        stability_score=state.stability_score,
        forgetting_due_at=state.forgetting_due_at,
        review_priority=state.review_priority,
        total_attempts=state.total_attempts,
        correct_attempts=state.correct_attempts,
        last_attempt_at=state.last_attempt_at,
        state_version=state.state_version,
        updated_at=state.updated_at,
    )


def _to_mastery_overview_response(overview) -> MasteryOverviewResponse:
    return MasteryOverviewResponse(
        subject=overview.subject,
        user_id=overview.user_id,
        weak_unit_count=overview.weak_unit_count,
        weak_node_count=overview.weak_node_count,
        unit_states=[_to_mastery_state_response(item) for item in overview.unit_states],
        node_states=[_to_mastery_state_response(item) for item in overview.node_states],
    )


def _to_review_task_response(task) -> ReviewTaskResponse:
    return ReviewTaskResponse(
        id=task.id or 0,
        user_id=task.user_id,
        subject=task.subject,
        task_type=task.task_type,
        target_id=task.target_id,
        target_granularity=task.target_granularity,
        priority=task.priority,
        scheduled_at=task.scheduled_at,
        status=task.status,
        interval_days=task.interval_days,
        ease_factor=task.ease_factor,
        repetition_count=task.repetition_count,
        reason=task.reason,
        source_state_id=task.source_state_id,
        source_exam_paper_id=task.source_exam_paper_id,
        created_at=task.created_at,
        completed_at=task.completed_at,
        expired_at=task.expired_at,
    )


@router.get(
    "/mastery",
    response_model=ApiResponse[MasteryOverviewResponse],
    summary="Mastery overview",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_mastery_overview(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[MasteryOverviewResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    overview = await get_mastery_overview(session, subject=normalized, user_id=user.user_id)
    return ok_response(_to_mastery_overview_response(overview))


@router.get(
    "/mastery/unit/{target_id:int}",
    response_model=ApiResponse[MasteryStateResponse],
    summary="Unit mastery detail",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_unit_mastery_detail(
    subject: str = Path(...),
    target_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[MasteryStateResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    state = await get_mastery_detail(
        session,
        subject=normalized,
        user_id=user.user_id,
        target_id=target_id,
        granularity="unit",
    )
    return ok_response(_to_mastery_state_response(state))


@router.get(
    "/mastery/node/{target_id:int}",
    response_model=ApiResponse[MasteryStateResponse],
    summary="Node mastery detail",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_node_mastery_detail(
    subject: str = Path(...),
    target_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[MasteryStateResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    state = await get_mastery_detail(
        session,
        subject=normalized,
        user_id=user.user_id,
        target_id=target_id,
        granularity="node",
    )
    return ok_response(_to_mastery_state_response(state))


@router.get(
    "/review/tasks",
    response_model=ApiResponse[list[ReviewTaskResponse]],
    summary="Pending review tasks",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_review_tasks(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[ReviewTaskResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    tasks = await get_review_tasks(session, subject=normalized, user_id=user.user_id)
    return ok_response([_to_review_task_response(item) for item in tasks])


@router.post(
    "/review/tasks/{task_id:int}/complete",
    response_model=ApiResponse[ReviewTaskResponse],
    summary="Complete review task",
    responses=build_error_responses([400, 404, 500]),
)
async def api_complete_review_task(
    subject: str = Path(...),
    task_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ReviewTaskResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    task = await complete_review_task(
        session,
        subject=normalized,
        task_id=task_id,
        user_id=user.user_id,
    )
    return ok_response(_to_review_task_response(task))
