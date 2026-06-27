"""Weakness analysis over mastery states and recent exam items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.models import ExamPaper, ExamPaperItem, UserKnowledgeState, WeaknessReason
from app.repositories import exams_repo, profile_repo
from app.utils.time import utcnow


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class WeaknessItem:
    knowledge_unit_id: int
    priority: float
    reason: str
    mastery_score: float
    recent_wrong_rate: float
    exam_weight: float


def _recent_error_stats_by_knowledge_unit(
    session: Session,
    *,
    user_id: str,
    course_id: str,
) -> dict[int, tuple[int, int]]:
    now = utcnow()
    since = now - timedelta(days=30)
    rows = list(
        session.exec(
            select(ExamPaperItem)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(
                ExamPaper.user_id == user_id,
                ExamPaper.course_id == course_id,
                ExamPaperItem.is_correct.is_not(None),
                ExamPaperItem.answered_at >= since,
            )
        ).all()
    )

    stats: dict[int, tuple[int, int]] = {}
    links_by_item_id = exams_repo.list_links_for_exam_items(session, [int(item.id or 0) for item in rows])
    for item in rows:
        knowledge_unit_ids = [
            int(ref["knowledge_unit_id"])
            for ref in links_by_item_id.get(int(item.id or 0), [])
            if int(ref.get("knowledge_unit_id", 0) or 0) > 0
        ]
        for knowledge_unit_id in knowledge_unit_ids:
            total, wrong = stats.get(knowledge_unit_id, (0, 0))
            total += 1
            if item.is_correct is False:
                wrong += 1
            stats[knowledge_unit_id] = (total, wrong)
    return stats


def _forgetting_risk(state: UserKnowledgeState, *, now: datetime) -> float:
    if state.forgetting_due_at is None:
        return 0.0
    due_at = _as_utc(state.forgetting_due_at)
    if due_at <= now:
        return 1.0
    days_left = (due_at - now).total_seconds() / 86400.0
    return max(0.0, min(1.0, 1.0 - (days_left / 30.0)))


def _pick_reason(
    *,
    state: UserKnowledgeState,
    recent_total: int,
    recent_wrong_rate: float,
    now: datetime,
) -> str:
    if state.forgetting_due_at is not None and _as_utc(state.forgetting_due_at) <= now:
        return WeaknessReason.FORGETTING_DUE.value
    if recent_total >= 2 and recent_wrong_rate >= 0.5:
        return WeaknessReason.REPEATED_WRONG.value
    return WeaknessReason.NEWLY_LEARNED.value


def analyze_weakness(
    session: Session,
    user_id: str,
    course_id: str,
    top_n: int = 20,
) -> list[WeaknessItem]:
    if top_n <= 0:
        return []

    states = list(profile_repo.list_knowledge_states(
        session,
        user_id=user_id,
        course_id=course_id,
        target_kind="knowledge_unit",
    ))
    if not states:
        return []

    error_stats = _recent_error_stats_by_knowledge_unit(session, user_id=user_id, course_id=course_id)
    now = utcnow()
    items: list[WeaknessItem] = []
    for state in states:
        if state.knowledge_unit_id is None:
            continue
        knowledge_unit_id = int(state.knowledge_unit_id)
        total, wrong = error_stats.get(knowledge_unit_id, (0, 0))
        wrong_rate = (wrong / total) if total > 0 else 0.0
        mastery_component = (1.0 - state.mastery_score) * 0.65
        wrong_component = wrong_rate * 0.25
        forgetting_component = _forgetting_risk(state, now=now) * 0.10
        priority = mastery_component + wrong_component + forgetting_component

        items.append(
            WeaknessItem(
                knowledge_unit_id=knowledge_unit_id,
                priority=priority,
                reason=_pick_reason(
                    state=state,
                    recent_total=total,
                    recent_wrong_rate=wrong_rate,
                    now=now,
                ),
                mastery_score=state.mastery_score,
                recent_wrong_rate=wrong_rate,
                exam_weight=0.0,
            )
        )

    ordered = sorted(items, key=lambda x: (-x.priority, x.knowledge_unit_id))
    return ordered[:top_n]
