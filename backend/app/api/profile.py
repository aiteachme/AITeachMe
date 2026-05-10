"""Profile API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Path
from sqlmodel import Session, select

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_course_id
from app.api.openapi import build_error_responses
from app.models.knowledge_unit import KnowledgeUnit
from app.models.course import Course
from app.repositories import profile_repo
from app.schemas.common import ApiResponse, ok_response
from app.schemas.profile import (
    CourseProfileSummary,
    MasteryOverviewResponse,
    MasteryStateResponse,
    ReviewTaskResponse,
    StudyPlanStepResponse,
    UserProfileSummary,
)
from app.shared.infra.exceptions import AITeachMeError
from app.workflows.profile import run_profile_snapshot_workflow, run_profile_study_plan_workflow

router = APIRouter(prefix="/api/v1/courses/{course_id}/profile", tags=["profile"])


def _ensure_course(session: Session, course_id: str, user_id: str) -> Course:
    record = session.exec(select(Course).where(Course.id == course_id, Course.user_id == user_id)).first()
    if record is None:
        raise AITeachMeError(
            detail=f"Course `{course_id}` not found.",
            error_code="COURSE_NOT_FOUND",
            status_code=404,
        )
    return record


def _knowledge_unit_map(
    session: Session,
    *,
    course_id: str,
    knowledge_unit_ids: list[int],
) -> dict[int, KnowledgeUnit]:
    ids = sorted({knowledge_unit_id for knowledge_unit_id in knowledge_unit_ids if knowledge_unit_id > 0})
    if not ids:
        return {}
    units = session.exec(
        select(KnowledgeUnit).where(
            KnowledgeUnit.course_id == course_id,
            KnowledgeUnit.id.in_(ids),
        )
    ).all()
    return {unit.id: unit for unit in units if unit.id is not None}


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
        course_id=state.course_id,
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
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[MasteryOverviewResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    profile_result = await run_profile_snapshot_workflow(
        course_id=normalized,
        user_id=user.user_id,
        session=session,
    )
    if profile_result.failed:
        raise AITeachMeError(
            detail=f"Profile snapshot failed: {profile_result.error}",
            error_code="PROFILE_WORKFLOW_FAILED",
            status_code=500,
        )
    profile_state = profile_result.require_value()
    if profile_state.get("error"):
        raise AITeachMeError(
            detail=f"Profile snapshot failed: {profile_state['error']}",
            error_code="PROFILE_WORKFLOW_FAILED",
            status_code=500,
        )

    course_profile = profile_state.get("course_profile")
    user_profile = profile_state.get("user_profile")
    return ok_response(
        MasteryOverviewResponse(
            course_id=normalized,
            user_id=user.user_id,
            weak_knowledge_unit_count=int(profile_state.get("weak_knowledge_unit_count") or 0),
            knowledge_unit_states=[
                MasteryStateResponse.model_validate(item)
                for item in list(profile_state.get("knowledge_unit_states") or [])
            ],
            course_profile=(
                CourseProfileSummary.model_validate(course_profile)
                if course_profile
                else None
            ),
            user_profile=(
                UserProfileSummary.model_validate(user_profile)
                if user_profile
                else None
            ),
        )
    )


@router.get(
    "/study-plan",
    response_model=ApiResponse[list[StudyPlanStepResponse]],
    summary="Generate current study plan",
    responses=build_error_responses([400, 404, 500]),
)
async def study_plan(
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[StudyPlanStepResponse]]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    profile_result = await run_profile_study_plan_workflow(
        course_id=normalized,
        user_id=user.user_id,
        session=session,
    )
    if profile_result.failed:
        raise AITeachMeError(
            detail=f"Profile study plan failed: {profile_result.error}",
            error_code="PROFILE_WORKFLOW_FAILED",
            status_code=500,
        )
    profile_state = profile_result.require_value()
    if profile_state.get("error"):
        raise AITeachMeError(
            detail=f"Profile study plan failed: {profile_state['error']}",
            error_code="PROFILE_WORKFLOW_FAILED",
            status_code=500,
        )

    return ok_response(
        [
            StudyPlanStepResponse.model_validate(item)
            for item in list(profile_state.get("study_plan") or [])
        ]
    )


@router.get(
    "/reviews",
    response_model=ApiResponse[list[ReviewTaskResponse]],
    summary="Fetch pending review tasks",
    responses=build_error_responses([400, 404, 500]),
)
async def review_tasks(
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[ReviewTaskResponse]]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    tasks = profile_repo.list_pending_reviews(session, user_id=user.user_id, course_id=normalized)
    knowledge_unit_by_id = _knowledge_unit_map(
        session,
        course_id=normalized,
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
    course_id: str = Path(...),
    task_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ReviewTaskResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    task = profile_repo.complete_review_task(
        session,
        task_id=task_id,
        user_id=user.user_id,
        course_id=normalized,
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
