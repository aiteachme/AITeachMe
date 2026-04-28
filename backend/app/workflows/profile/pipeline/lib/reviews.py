"""Mastery review scheduling based on fields embedded in UserKnowledgeState."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from app.models import UserKnowledgeState, WeaknessReason
from app.repositories import profile_repo
from app.utils.time import utcnow


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def compute_sm2_interval(
    *,
    repetition_count: int,
    current_ease_factor: float,
    current_interval_days: int,
    accuracy: float,
) -> tuple[int, float]:
    normalized_repetition = max(0, repetition_count)
    normalized_interval = max(1, current_interval_days)
    normalized_accuracy = min(1.0, max(0.0, accuracy))

    if normalized_accuracy > 0.8:
        updated_ease_factor = current_ease_factor + 0.15
    elif normalized_accuracy < 0.6:
        updated_ease_factor = current_ease_factor - 0.2
    else:
        updated_ease_factor = current_ease_factor

    bounded_ease_factor = min(2.5, max(1.3, updated_ease_factor))

    if normalized_repetition <= 0:
        next_interval = 1
    elif normalized_repetition == 1:
        next_interval = 6
    else:
        next_interval = int(round(normalized_interval * bounded_ease_factor))

    return max(1, next_interval), bounded_ease_factor


def _compute_forgetting_due_days(*, mastery_score: float, stability_score: float) -> int:
    mastery = min(1.0, max(0.0, mastery_score))
    stability = min(1.0, max(0.0, stability_score))
    days = int(round(1 + mastery * 11 + stability * 18))
    return max(1, min(30, days))


def _compute_priority(state: UserKnowledgeState, *, now: datetime) -> float:
    mastery = min(1.0, max(0.0, state.mastery_score))
    stability = min(1.0, max(0.0, state.stability_score))
    incorrect_rate = 1.0 - (
        (state.correct_attempts / state.total_attempts) if state.total_attempts > 0 else 0.0
    )
    due_bonus = 0.0
    if state.forgetting_due_at is not None:
        due_bonus = 0.3 if _as_utc(state.forgetting_due_at) <= now else 0.0
    return (
        (1.0 - mastery) * 0.5
        + (1.0 - stability) * 0.25
        + incorrect_rate * 0.25
        + due_bonus
    )


def _infer_reason(state: UserKnowledgeState, *, now: datetime) -> str:
    if state.forgetting_due_at is not None and _as_utc(state.forgetting_due_at) <= now:
        return WeaknessReason.FORGETTING_DUE.value
    if state.total_attempts <= 2:
        return WeaknessReason.NEWLY_LEARNED.value
    return WeaknessReason.REPEATED_WRONG.value


def _expire_outdated_pending_reviews(
    session: Session,
    *,
    user_id: str,
    subject_id: str,
    auto_commit: bool = True,
) -> None:
    now = utcnow()
    changed = False
    for state in profile_repo.list_pending_reviews(session, user_id=user_id, subject_id=subject_id):
        if state.scheduled_review_at is None:
            continue
        if _as_utc(state.scheduled_review_at) + timedelta(days=7) > now:
            continue
        state.review_status = "expired"
        state.updated_at = now
        session.add(state)
        changed = True
    if changed:
        if auto_commit:
            session.commit()
        else:
            session.flush()


def schedule_reviews(
    session: Session,
    user_id: str,
    subject_id: str,
    updated_state_ids: list[int],
    *,
    auto_commit: bool = True,
) -> list[UserKnowledgeState]:
    """Update review fields on mastery states."""

    _expire_outdated_pending_reviews(
        session,
        user_id=user_id,
        subject_id=subject_id,
        auto_commit=auto_commit,
    )

    now = utcnow()
    persisted_states: list[UserKnowledgeState] = []
    deduped_state_ids = sorted({int(state_id) for state_id in updated_state_ids})

    for state_id in deduped_state_ids:
        state = session.get(UserKnowledgeState, state_id)
        if state is None:
            continue
        if state.user_id != user_id or state.subject_id != subject_id:
            continue

        due_days = _compute_forgetting_due_days(
            mastery_score=state.mastery_score,
            stability_score=state.stability_score,
        )
        state.forgetting_due_at = now + timedelta(days=due_days)

        if state.mastery_score >= 0.8:
            state.review_status = "idle"
            state.scheduled_review_at = None
            state.review_reason = None
            state.updated_at = now
            session.add(state)
            persisted_states.append(state)
            continue

        next_interval, next_ease_factor = compute_sm2_interval(
            repetition_count=state.review_repetition_count,
            current_ease_factor=state.review_ease_factor,
            current_interval_days=state.review_interval_days,
            accuracy=state.mastery_score,
        )
        scheduled_at = now + timedelta(days=next_interval)
        if state.forgetting_due_at is not None and _as_utc(state.forgetting_due_at) <= now:
            scheduled_at = now

        state.review_priority = _compute_priority(state, now=now)
        state.review_status = "pending"
        state.scheduled_review_at = scheduled_at
        state.review_interval_days = next_interval
        state.review_ease_factor = next_ease_factor
        state.review_repetition_count += 1
        state.review_reason = _infer_reason(state, now=now)
        state.updated_at = now
        session.add(state)
        persisted_states.append(state)

    if auto_commit:
        session.commit()
        for state in persisted_states:
            session.refresh(state)
    else:
        session.flush()
    return persisted_states
