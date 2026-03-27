"""Profile service layer."""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus

from sqlmodel import Session

from app.core.exceptions import AITeachMeError
from app.models import UserKnowledgeState
from app.repositories.profile_repo import complete_review_task as complete_review_task_repo
from app.repositories.profile_repo import get_knowledge_state, list_knowledge_states, list_pending_reviews


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


async def get_mastery_overview(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> MasteryOverview:
    unit_states = list_knowledge_states(session, user_id=user_id, subject=subject, target_kind="unit")
    node_states = list_knowledge_states(session, user_id=user_id, subject=subject, target_kind="node")
    return MasteryOverview(
        subject=subject,
        user_id=user_id,
        unit_states=unit_states,
        node_states=node_states,
        weak_unit_count=sum(1 for item in unit_states if item.mastery_score < 0.8),
        weak_node_count=sum(1 for item in node_states if item.mastery_score < 0.8),
    )


async def get_unit_mastery_detail(
    session: Session,
    *,
    subject: str,
    user_id: str,
    teaching_unit_id: int,
) -> UserKnowledgeState:
    state = get_knowledge_state(
        session,
        user_id=user_id,
        subject=subject,
        teaching_unit_id=teaching_unit_id,
    )
    if state is None:
        _raise_not_found(
            f"未找到掌握度记录：user_id={user_id}, subject={subject}, teaching_unit_id={teaching_unit_id}。",
            error_code="MASTERY_STATE_NOT_FOUND",
        )
    return state


async def get_node_mastery_detail(
    session: Session,
    *,
    subject: str,
    user_id: str,
    knowledge_node_id: int,
) -> UserKnowledgeState:
    state = get_knowledge_state(
        session,
        user_id=user_id,
        subject=subject,
        knowledge_node_id=knowledge_node_id,
    )
    if state is None:
        _raise_not_found(
            f"未找到掌握度记录：user_id={user_id}, subject={subject}, knowledge_node_id={knowledge_node_id}。",
            error_code="MASTERY_STATE_NOT_FOUND",
        )
    return state


async def get_review_tasks(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> list[UserKnowledgeState]:
    return list_pending_reviews(session, user_id=user_id, subject=subject)


async def complete_review_task(
    session: Session,
    *,
    subject: str,
    task_id: int,
    user_id: str,
) -> UserKnowledgeState:
    task = complete_review_task_repo(
        session,
        task_id=task_id,
        user_id=user_id,
        subject=subject,
    )
    if task is None:
        _raise_not_found(f"复习任务 `{task_id}` 不存在。", error_code="REVIEW_TASK_NOT_FOUND")
    return task
