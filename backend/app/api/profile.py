"""Profile API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlmodel import Session, select

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.models.subject import Subject
from app.repositories import profile_repo
from app.schemas.common import ApiResponse, ok_response
from app.schemas.profile import MasteryOverviewResponse, MasteryStateResponse, ReviewTaskResponse
from app.shared.infra.exceptions import AITeachMeError

router = APIRouter(prefix="/api/v1/subjects/{subject}/profile", tags=["profile"])


def _ensure_subject(session: Session, subject: str, user_id: str) -> Subject:
    record = session.exec(select(Subject).where(Subject.slug == subject, Subject.user_id == user_id)).first()
    if record is None:
        raise AITeachMeError(
            detail=f"Subject `{subject}` not found.",
            error_code="SUBJECT_NOT_FOUND",
            status_code=404,
        )
    return record


def _state_response(state) -> MasteryStateResponse:
    return MasteryStateResponse(
        id=state.id,
        target_kind="node" if state.knowledge_node_id is not None else "unit",
        teaching_unit_id=state.teaching_unit_id,
        knowledge_node_id=state.knowledge_node_id,
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


def _review_response(state) -> ReviewTaskResponse:
    return ReviewTaskResponse(
        id=state.id,
        user_id=state.user_id,
        subject=state.subject,
        target_kind="node" if state.knowledge_node_id is not None else "unit",
        teaching_unit_id=state.teaching_unit_id,
        knowledge_node_id=state.knowledge_node_id,
        priority=state.review_priority,
        scheduled_at=state.scheduled_review_at,
        status=state.review_status,
        interval_days=state.review_interval_days,
        ease_factor=state.review_ease_factor,
        repetition_count=state.review_repetition_count,
        reason=state.review_reason,
        source_exam_paper_id=state.source_exam_paper_id,
        updated_at=state.updated_at,
    )


@router.get(
    "/mastery",
    response_model=ApiResponse[MasteryOverviewResponse],
    summary="Fetch mastery overview",
    responses=build_error_responses([400, 404, 500]),
)
async def mastery_overview(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[MasteryOverviewResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    unit_states = profile_repo.list_knowledge_states(
        session,
        user_id=user.user_id,
        subject=normalized,
        target_kind="unit",
    )
    node_states = profile_repo.list_knowledge_states(
        session,
        user_id=user.user_id,
        subject=normalized,
        target_kind="node",
    )
    return ok_response(
        MasteryOverviewResponse(
            subject=normalized,
            user_id=user.user_id,
            weak_unit_count=sum(1 for item in unit_states if item.mastery_score < 0.8),
            weak_node_count=sum(1 for item in node_states if item.mastery_score < 0.8),
            unit_states=[_state_response(item) for item in unit_states],
            node_states=[_state_response(item) for item in node_states],
        )
    )


@router.get(
    "/reviews",
    response_model=ApiResponse[list[ReviewTaskResponse]],
    summary="Fetch pending review tasks",
    responses=build_error_responses([400, 404, 500]),
)
async def review_tasks(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[ReviewTaskResponse]]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    tasks = profile_repo.list_pending_reviews(session, user_id=user.user_id, subject=normalized)
    return ok_response([_review_response(item) for item in tasks])


@router.post(
    "/reviews/{task_id}/complete",
    response_model=ApiResponse[ReviewTaskResponse],
    summary="Mark one review task as completed",
    responses=build_error_responses([400, 404, 500]),
)
async def complete_review(
    subject: str = Path(...),
    task_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ReviewTaskResponse]:
    normalized = normalize_subject_slug(subject)
    _ensure_subject(session, normalized, user.user_id)
    task = profile_repo.complete_review_task(
        session,
        task_id=task_id,
        user_id=user.user_id,
        subject=normalized,
    )
    if task is None:
        raise AITeachMeError(
            detail=f"Review task `{task_id}` not found.",
            error_code="REVIEW_TASK_NOT_FOUND",
            status_code=404,
        )
    return ok_response(_review_response(task))
