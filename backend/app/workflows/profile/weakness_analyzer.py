"""Weakness analysis over mastery states and recent exam items."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.models import ExamPaper, ExamPaperItem, ThemeTreeNode, UnitDependency, UserKnowledgeState, WeaknessReason
from app.repositories import exams_repo, profile_repo
from app.utils.time import utcnow


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _extract_unit_ids(unit_refs_json: str) -> list[int]:
    try:
        payload = json.loads(unit_refs_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    unit_ids: list[int] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("teaching_unit_id")
        if isinstance(raw_id, int):
            unit_ids.append(raw_id)
        elif isinstance(raw_id, str) and raw_id.isdigit():
            unit_ids.append(int(raw_id))
    return unit_ids


@dataclass(frozen=True)
class WeaknessItem:
    teaching_unit_id: int
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
            select(ExamPaperItem)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(
                ExamPaper.user_id == user_id,
                ExamPaper.subject == subject,
                ExamPaperItem.is_correct.is_not(None),
                ExamPaperItem.answered_at >= since,
            )
        ).all()
    )

    stats: dict[int, tuple[int, int]] = {}
    for item in rows:
        unit_id = int(item.teaching_unit_id)
        total, wrong = stats.get(unit_id, (0, 0))
        total += 1
        if item.is_correct is False:
            wrong += 1
        stats[unit_id] = (total, wrong)
    return stats


def _exam_weight_by_unit(
    session: Session,
    *,
    subject: str,
) -> dict[int, float]:
    version = exams_repo.get_published_curriculum_version(session, subject)
    if version is None or version.theme_tree_version_id is None:
        return {}

    nodes = list(
        session.exec(
            select(ThemeTreeNode).where(ThemeTreeNode.tree_version_id == version.theme_tree_version_id)
        ).all()
    )
    counts: dict[int, int] = {}
    for node in nodes:
        for unit_id in _extract_unit_ids(node.unit_refs_json):
            counts[unit_id] = counts.get(unit_id, 0) + 1

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
    version = exams_repo.get_published_curriculum_version(session, subject)
    if version is None or version.prereq_dag_version_id is None:
        return set()

    rows = list(
        session.exec(
            select(UnitDependency.source_unit_id, UnitDependency.target_unit_id).where(
                UnitDependency.dag_version_id == version.prereq_dag_version_id,
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
    prereq_gap: bool,
    recent_total: int,
    recent_wrong_rate: float,
    now: datetime,
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
    if top_n <= 0:
        return []

    states = list(profile_repo.list_knowledge_states(session, user_id=user_id, subject=subject, target_kind="unit"))
    if not states:
        return []

    state_by_unit = {int(state.teaching_unit_id): state for state in states if state.teaching_unit_id is not None}
    error_stats = _recent_error_stats_by_unit(session, user_id=user_id, subject=subject)
    exam_weight = _exam_weight_by_unit(session, subject=subject)
    prereq_gaps = _prereq_gap_units(session, subject=subject, unit_states=state_by_unit)

    now = utcnow()
    items: list[WeaknessItem] = []
    for state in states:
        if state.teaching_unit_id is None:
            continue
        teaching_unit_id = int(state.teaching_unit_id)
        total, wrong = error_stats.get(teaching_unit_id, (0, 0))
        wrong_rate = (wrong / total) if total > 0 else 0.0
        mastery_component = (1.0 - state.mastery_score) * 0.45
        wrong_component = wrong_rate * 0.20
        prereq_component = 0.20 if teaching_unit_id in prereq_gaps else 0.0
        forgetting_component = _forgetting_risk(state, now=now) * 0.10
        exam_weight_component = exam_weight.get(teaching_unit_id, 0.0) * 0.05
        priority = mastery_component + wrong_component + prereq_component + forgetting_component + exam_weight_component

        items.append(
            WeaknessItem(
                teaching_unit_id=teaching_unit_id,
                priority=priority,
                reason=_pick_reason(
                    state=state,
                    prereq_gap=(teaching_unit_id in prereq_gaps),
                    recent_total=total,
                    recent_wrong_rate=wrong_rate,
                    now=now,
                ),
                mastery_score=state.mastery_score,
                recent_wrong_rate=wrong_rate,
                exam_weight=exam_weight.get(teaching_unit_id, 0.0),
            )
        )

    ordered = sorted(items, key=lambda x: (-x.priority, x.teaching_unit_id))
    return ordered[:top_n]
