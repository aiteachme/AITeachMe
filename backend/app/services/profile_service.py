"""Profile service layer."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus

from sqlmodel import Session

from app.core.exceptions import AITeachMeError
from app.models import ReviewTask, UserKnowledgeState
from app.repositories.exams_repo import list_mistakes_by_subject
from app.repositories.profile_repo import (
    complete_review_task as complete_review_task_repo,
    get_knowledge_state,
    get_weak_points,
    list_knowledge_states,
    list_pending_reviews,
    list_profiles_by_subject,
)
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.profile import MistakeItem, ProfileItem, ReportData
from app.services.presenters import mastery_to_text
from app.workflows.profile import generate_report_suggestions


@dataclass(frozen=True)
class MasteryOverview:
    subject: str
    user_id: str
    unit_states: list[UserKnowledgeState]
    node_states: list[UserKnowledgeState]
    weak_unit_count: int
    weak_node_count: int


def _raise_not_found(detail: str, *, error_code: str = "NOT_FOUND") -> None:
    raise AITeachMeError(
        detail=detail,
        status_code=HTTPStatus.NOT_FOUND,
        error_code=error_code,
    )


def list_profiles(
    session: Session,
    *,
    subject: str,
    page: int,
    size: int,
) -> PaginatedData[ProfileItem]:
    items, total = list_profiles_by_subject(
        session,
        subject,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(
        items=[
            ProfileItem(
                knowledge_point=item.knowledge_point,
                mastery=item.mastery,
                attempts=item.attempts,
                correct=item.correct,
            )
            for item in items
        ],
        page=page,
        size=size,
        total=total,
    )


async def get_report(session: Session, *, subject: str) -> ReportData:
    all_profiles, _ = list_profiles_by_subject(session, subject, limit=10000, offset=0)
    tested_profiles = [item for item in all_profiles if item.mastery is not None and item.attempts > 0]
    overall_mastery = None
    if tested_profiles:
        total_attempts = sum(item.attempts for item in tested_profiles)
        if total_attempts > 0:
            overall_mastery = sum(item.correct for item in tested_profiles) / total_attempts

    weak_profiles = get_weak_points(session, subject, limit=5)
    suggestions = await generate_report_suggestions(
        subject=subject,
        overall_mastery=overall_mastery,
        weak_points=[
            {
                "knowledge_point": item.knowledge_point,
                "mastery_text": mastery_to_text(item.mastery),
            }
            for item in weak_profiles
        ],
    )
    return ReportData(
        overall_mastery=overall_mastery,
        weak_points_top5=[
            ProfileItem(
                knowledge_point=item.knowledge_point,
                mastery=item.mastery,
                attempts=item.attempts,
                correct=item.correct,
            )
            for item in weak_profiles
        ],
        suggestions=suggestions,
    )


def list_mistakes(
    session: Session,
    *,
    subject: str,
    page: int,
    size: int,
) -> PaginatedData[MistakeItem]:
    items, total = list_mistakes_by_subject(
        session,
        subject,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(
        items=[
            MistakeItem(
                id=item["id"],
                question_stem=item["question_stem"],
                question_type=item["question_type"],
                user_answer=item["user_answer"],
                correct_answer=item["correct_answer"],
                analysis=item["analysis"],
                knowledge_point=item["knowledge_point"],
                created_at=item["created_at"],
            )
            for item in items
        ],
        page=page,
        size=size,
        total=total,
    )


async def get_mastery_overview(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> MasteryOverview:
    states = list_knowledge_states(session, user_id=user_id, subject=subject)
    unit_states = [item for item in states if item.granularity == "unit"]
    node_states = [item for item in states if item.granularity == "node"]
    return MasteryOverview(
        subject=subject,
        user_id=user_id,
        unit_states=unit_states,
        node_states=node_states,
        weak_unit_count=sum(1 for item in unit_states if item.mastery_score < 0.8),
        weak_node_count=sum(1 for item in node_states if item.mastery_score < 0.8),
    )


async def get_mastery_detail(
    session: Session,
    *,
    subject: str,
    user_id: str,
    target_id: int,
    granularity: str,
):
    state = get_knowledge_state(
        session,
        user_id=user_id,
        subject=subject,
        granularity=granularity,
        target_id=target_id,
    )
    if state is None:
        _raise_not_found(
            f"未找到掌握度记录：user_id={user_id}, subject={subject}, granularity={granularity}, target_id={target_id}。",
            error_code="MASTERY_STATE_NOT_FOUND",
        )
    return state


async def get_review_tasks(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> list[ReviewTask]:
    return list_pending_reviews(session, user_id=user_id, subject=subject)


async def complete_review_task(
    session: Session,
    *,
    subject: str,
    task_id: int,
    user_id: str,
) -> ReviewTask:
    task = complete_review_task_repo(
        session,
        task_id=task_id,
        user_id=user_id,
        subject=subject,
    )
    if task is None:
        _raise_not_found(f"复习任务 `{task_id}` 不存在。", error_code="REVIEW_TASK_NOT_FOUND")
    return task
