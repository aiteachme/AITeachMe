"""Profile API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlmodel import Session, select

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.models.knowledge_unit import KnowledgeUnit
from app.models.subject import Subject
from app.repositories import profile_repo
from app.schemas.common import ApiResponse, ok_response
from app.schemas.profile import MasteryOverviewResponse, MasteryStateResponse, ReviewTaskResponse
from app.shared.infra.exceptions import AITeachMeError
from app.workflows.profile import build_subject_profile_summary, build_user_profile_summary

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


def _knowledge_unit_map(
    session: Session,
    *,
    subject: str,
    knowledge_unit_ids: list[int],
) -> dict[int, KnowledgeUnit]:
    ids = sorted({knowledge_unit_id for knowledge_unit_id in knowledge_unit_ids if knowledge_unit_id > 0})
    if not ids:
        return {}
    units = session.exec(
        select(KnowledgeUnit).where(
            KnowledgeUnit.subject == subject,
            KnowledgeUnit.id.in_(ids),
        )
    ).all()
    return {unit.id: unit for unit in units if unit.id is not None}


def _state_response(state, knowledge_unit: KnowledgeUnit | None = None) -> MasteryStateResponse:
    if state.knowledge_unit_id is None:
        raise AITeachMeError(
            detail="Encountered legacy unit-level mastery state.",
            error_code="LEGACY_MASTERY_STATE",
            status_code=500,
        )
    return MasteryStateResponse(
        id=state.id,
        knowledge_unit_id=state.knowledge_unit_id,
        knowledge_unit_name=knowledge_unit.canonical_name if knowledge_unit is not None else None,
        knowledge_unit_type=knowledge_unit.knowledge_unit_type if knowledge_unit is not None else None,
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


def _review_response(state, knowledge_unit: KnowledgeUnit | None = None) -> ReviewTaskResponse:
    if state.knowledge_unit_id is None:
        raise AITeachMeError(
            detail="Encountered legacy unit-level review task.",
            error_code="LEGACY_REVIEW_TASK",
            status_code=500,
        )
    return ReviewTaskResponse(
        id=state.id,
        user_id=state.user_id,
        subject=state.subject,
        knowledge_unit_id=state.knowledge_unit_id,
        knowledge_unit_name=knowledge_unit.canonical_name if knowledge_unit is not None else None,
        knowledge_unit_type=knowledge_unit.knowledge_unit_type if knowledge_unit is not None else None,
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
    knowledge_unit_states = profile_repo.list_knowledge_states(
        session,
        user_id=user.user_id,
        subject=normalized,
        target_kind="knowledge_unit",
    )
    knowledge_unit_by_id = _knowledge_unit_map(
        session,
        subject=normalized,
        knowledge_unit_ids=[
            int(item.knowledge_unit_id)
            for item in knowledge_unit_states
            if item.knowledge_unit_id is not None
        ],
    )
    return ok_response(
        MasteryOverviewResponse(
            subject=normalized,
            user_id=user.user_id,
            weak_knowledge_unit_count=sum(1 for item in knowledge_unit_states if item.mastery_score < 0.8),
            knowledge_unit_states=[
                _state_response(item, knowledge_unit_by_id.get(int(item.knowledge_unit_id)))
                for item in knowledge_unit_states
            ],
            subject_profile=build_subject_profile_summary(
                session,
                subject=normalized,
                user_id=user.user_id,
            ),
            user_profile=build_user_profile_summary(
                session,
                user_id=user.user_id,
            ),
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
    knowledge_unit_by_id = _knowledge_unit_map(
        session,
        subject=normalized,
        knowledge_unit_ids=[
            int(item.knowledge_unit_id)
            for item in tasks
            if item.knowledge_unit_id is not None
        ],
    )
    return ok_response(
        [
            _review_response(item, knowledge_unit_by_id.get(int(item.knowledge_unit_id)))
            for item in tasks
        ]
    )


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
    knowledge_unit = None
    if task.knowledge_unit_id is not None:
        knowledge_unit = session.get(KnowledgeUnit, int(task.knowledge_unit_id))
    return ok_response(_review_response(task, knowledge_unit))
