"""掌握度复习调度：SM-2 纯函数 + ReviewTask 调度。

Reads DB: ``user_knowledge_state`` and existing ``review_task`` rows.
Writes DB: ``review_task`` plus review-related scheduling fields on ``user_knowledge_state``.
Writes FS: none.
Idempotency: reruns reconcile pending tasks for the same user/subject/target instead of creating
unbounded duplicates.
"""

from __future__ import annotations

from datetime import datetime, timezone
from datetime import timedelta

from sqlmodel import Session

from app.models import ReviewTask, UserKnowledgeState, WeaknessReason
from app.repositories import assessment_repo
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
    """计算下一次复习间隔和易度因子（SM-2 启发式）。

    规则：
    - 第一次复习间隔 = 1 天
    - 第二次复习间隔 = 6 天
    - 后续间隔 = 上次间隔 * 新易度因子
    - 易度因子边界：[1.3, 2.5]
    - 间隔下界：1 天
    """

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

    bounded_interval = max(1, next_interval)
    return bounded_interval, bounded_ease_factor


def _compute_forgetting_due_days(*, mastery_score: float, stability_score: float) -> int:
    # 掌握度和稳定性越高，遗忘到期时间越晚；范围保持在 [1, 30] 天。
    mastery = min(1.0, max(0.0, mastery_score))
    stability = min(1.0, max(0.0, stability_score))
    days = int(round(1 + mastery * 11 + stability * 18))
    return max(1, min(30, days))


def _compute_priority(state: UserKnowledgeState, *, now) -> float:
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


def _infer_reason(state: UserKnowledgeState, *, now) -> str:
    if state.forgetting_due_at is not None and _as_utc(state.forgetting_due_at) <= now:
        return WeaknessReason.FORGETTING_DUE.value
    if state.total_attempts <= 2:
        return WeaknessReason.NEWLY_LEARNED.value
    return WeaknessReason.REPEATED_WRONG.value


def _expire_outdated_pending_tasks(
    session: Session,
    *,
    user_id: str,
    subject: str,
) -> None:
    now = utcnow()
    changed = False
    for task in assessment_repo.list_pending_reviews(session, user_id=user_id, subject=subject):
        if _as_utc(task.scheduled_at) + timedelta(days=7) <= now:
            task.status = "expired"
            task.expired_at = now
            session.add(task)
            changed = True
    if changed:
        session.commit()


def schedule_reviews(
    session: Session,
    user_id: str,
    subject: str,
    updated_state_ids: list[int],
) -> list[ReviewTask]:
    """根据更新后的知识状态生成/更新复习任务。"""

    _expire_outdated_pending_tasks(session, user_id=user_id, subject=subject)

    now = utcnow()
    persisted_tasks: list[ReviewTask] = []
    deduped_state_ids = sorted({int(state_id) for state_id in updated_state_ids})

    for state_id in deduped_state_ids:
        state = session.get(UserKnowledgeState, state_id)
        if state is None:
            continue
        if state.user_id != user_id or state.subject != subject:
            continue

        # review_scheduler 是 forgetting_due_at 的唯一写入者
        due_days = _compute_forgetting_due_days(
            mastery_score=state.mastery_score,
            stability_score=state.stability_score,
        )
        state.forgetting_due_at = now + timedelta(days=due_days)
        state.updated_at = now
        session.add(state)
        session.commit()
        session.refresh(state)

        if state.mastery_score >= 0.8:
            continue

        existing_pending = assessment_repo.find_pending_review(
            session,
            user_id=user_id,
            subject=subject,
            target_id=state.target_id,
            target_granularity=state.granularity,
        )
        repetition_count = existing_pending.repetition_count if existing_pending is not None else 0
        interval_days = existing_pending.interval_days if existing_pending is not None else 1
        ease_factor = existing_pending.ease_factor if existing_pending is not None else 2.5

        next_interval, next_ease_factor = compute_sm2_interval(
            repetition_count=repetition_count,
            current_ease_factor=ease_factor,
            current_interval_days=interval_days,
            accuracy=state.mastery_score,
        )
        scheduled_at = now + timedelta(days=next_interval)
        if state.forgetting_due_at is not None and _as_utc(state.forgetting_due_at) <= now:
            scheduled_at = now

        task = ReviewTask(
            user_id=user_id,
            subject=subject,
            task_type=("review_unit" if state.granularity == "unit" else "review_node"),
            target_id=state.target_id,
            target_granularity=state.granularity,
            priority=_compute_priority(state, now=now),
            scheduled_at=scheduled_at,
            status="pending",
            interval_days=next_interval,
            ease_factor=next_ease_factor,
            repetition_count=repetition_count + 1,
            reason=_infer_reason(state, now=now),
            source_state_id=state.id,
            source_exam_paper_id=None,
        )
        persisted_tasks.append(assessment_repo.upsert_review_task(session, task))

    return persisted_tasks
