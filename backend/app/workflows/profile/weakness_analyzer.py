"""薄弱分析：多维度优先级排序。

Reads DB: ``user_knowledge_state``, ``user_answer_attempt``, ``exam_paper_item`` and current
curriculum snapshot structures.
Writes DB: none.
Writes FS: none.
Idempotency: read-only analysis over the current persisted mastery and answer history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from datetime import timedelta

from sqlmodel import Session, select

from app.models import ExamPaper, ExamPaperItem, UnitDependency, UnitTreeMembership, UserAnswerAttempt, UserKnowledgeState, WeaknessReason
from app.repositories import exams_repo, profile_repo
from app.utils.time import utcnow


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class WeaknessItem:
    target_id: int
    priority: float
    reason: str
    mastery_score: float
    recent_wrong_rate: float
    exam_weight: float


def _recent_error_stats_by_unit(
    session: Session,
    *,
    user_id: str,
    subject: str,
) -> dict[int, tuple[int, int]]:
    now = utcnow()
    since = now - timedelta(days=30)
    rows = list(
        session.exec(
            select(UserAnswerAttempt, ExamPaperItem)
            .join(ExamPaperItem, UserAnswerAttempt.exam_paper_item_id == ExamPaperItem.id)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(
                ExamPaper.user_id == user_id,
                ExamPaper.subject == subject,
                UserAnswerAttempt.is_correct.is_not(None),  # type: ignore[union-attr]
                UserAnswerAttempt.created_at >= since,  # type: ignore[operator]
            )
        ).all()
    )

    stats: dict[int, tuple[int, int]] = {}
    for attempt, item in rows:
        unit_id = int(item.snapshot_teaching_unit_id)
        total, wrong = stats.get(unit_id, (0, 0))
        total += 1
        if attempt.is_correct is False:
            wrong += 1
        stats[unit_id] = (total, wrong)
    return stats


def _exam_weight_by_unit(
    session: Session,
    *,
    subject: str,
) -> dict[int, float]:
    snapshot = exams_repo.get_published_curriculum_snapshot(session, subject)
    if snapshot is None or snapshot.theme_tree_version_id is None:
        return {}

    rows = list(
        session.exec(
            select(UnitTreeMembership.teaching_unit_id).where(
                UnitTreeMembership.tree_version_id == snapshot.theme_tree_version_id
            )
        ).all()
    )
    if not rows:
        return {}

    counts: dict[int, int] = {}
    for unit_id in rows:
        key = int(unit_id)
        counts[key] = counts.get(key, 0) + 1
    total = sum(counts.values())
    if total <= 0:
        return {}
    return {unit_id: cnt / total for unit_id, cnt in counts.items()}


def _prereq_gap_units(
    session: Session,
    *,
    subject: str,
    unit_states: dict[int, UserKnowledgeState],
) -> set[int]:
    snapshot = exams_repo.get_published_curriculum_snapshot(session, subject)
    if snapshot is None or snapshot.prereq_dag_version_id is None:
        return set()

    rows = list(
        session.exec(
            select(UnitDependency.source_unit_id, UnitDependency.target_unit_id).where(
                UnitDependency.dag_version_id == snapshot.prereq_dag_version_id,
                UnitDependency.dependency_type == "prerequisite",
            )
        ).all()
    )

    gaps: set[int] = set()
    for source_unit_id, _ in rows:
        source_state = unit_states.get(int(source_unit_id))
        if source_state is not None and source_state.mastery_score < 0.6:
            gaps.add(int(source_unit_id))
    return gaps


def _forgetting_risk(state: UserKnowledgeState, *, now) -> float:
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
    prereq_gap: bool,
    recent_total: int,
    recent_wrong_rate: float,
    now,
) -> str:
    if prereq_gap:
        return WeaknessReason.PREREQ_GAP.value
    if state.forgetting_due_at is not None and _as_utc(state.forgetting_due_at) <= now:
        return WeaknessReason.FORGETTING_DUE.value
    if recent_total >= 2 and recent_wrong_rate >= 0.5:
        return WeaknessReason.REPEATED_WRONG.value
    return WeaknessReason.NEWLY_LEARNED.value


def analyze_weakness(
    session: Session,
    user_id: str,
    subject: str,
    top_n: int = 20,
) -> list[WeaknessItem]:
    """综合 5 个维度输出薄弱单元优先级。"""

    if top_n <= 0:
        return []

    states = [
        item
        for item in profile_repo.list_knowledge_states(session, user_id=user_id, subject=subject, granularity="unit")
    ]
    if not states:
        return []

    state_by_unit = {state.target_id: state for state in states}
    error_stats = _recent_error_stats_by_unit(session, user_id=user_id, subject=subject)
    exam_weight = _exam_weight_by_unit(session, subject=subject)
    prereq_gaps = _prereq_gap_units(session, subject=subject, unit_states=state_by_unit)

    now = utcnow()
    items: list[WeaknessItem] = []
    for state in states:
        total, wrong = error_stats.get(state.target_id, (0, 0))
        wrong_rate = (wrong / total) if total > 0 else 0.0
        mastery_component = (1.0 - state.mastery_score) * 0.45
        wrong_component = wrong_rate * 0.20
        prereq_component = (0.20 if state.target_id in prereq_gaps else 0.0)
        forgetting_component = _forgetting_risk(state, now=now) * 0.10
        exam_weight_component = exam_weight.get(state.target_id, 0.0) * 0.05
        priority = mastery_component + wrong_component + prereq_component + forgetting_component + exam_weight_component

        items.append(
            WeaknessItem(
                target_id=state.target_id,
                priority=priority,
                reason=_pick_reason(
                    state=state,
                    prereq_gap=(state.target_id in prereq_gaps),
                    recent_total=total,
                    recent_wrong_rate=wrong_rate,
                    now=now,
                ),
                mastery_score=state.mastery_score,
                recent_wrong_rate=wrong_rate,
                exam_weight=exam_weight.get(state.target_id, 0.0),
            )
        )

    ordered = sorted(items, key=lambda x: (-x.priority, x.target_id))
    return ordered[:top_n]
