"""Mastery updater driven by graded exam paper items."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp

from sqlmodel import Session

from app.models import ExamPaper, ExamPaperItem, UserKnowledgeState
from app.repositories import exams_repo, profile_repo
from app.utils.time import utcnow

_DIFFICULTY_WEIGHT = {
    "easy": 0.8,
    "medium": 1.0,
    "hard": 1.2,
}


@dataclass(frozen=True)
class _WeightedAttempt:
    is_correct: bool
    difficulty: str
    answered_at: datetime
    coverage_weight: float = 1.0


@dataclass(frozen=True)
class MasteryUpdateResult:
    exam_paper_id: int
    states_updated: int
    updated_state_ids: list[int]
    already_consumed: bool


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _difficulty_weight(difficulty: str) -> float:
    return _DIFFICULTY_WEIGHT.get((difficulty or "").lower(), 1.0)


def _time_decay_weight(*, answered_at: datetime, now: datetime, half_life_days: float) -> float:
    if half_life_days <= 0:
        return 1.0
    age_seconds = max(0.0, (now - answered_at).total_seconds())
    age_days = age_seconds / 86400.0
    return exp(-age_days / half_life_days)


def _compute_weighted_mastery_score(
    *,
    attempts: list[_WeightedAttempt],
    now: datetime,
    half_life_days: float = 30.0,
) -> float:
    if not attempts:
        return 0.0

    weighted_total = 0.0
    weighted_correct = 0.0
    for item in attempts:
        base_weight = _difficulty_weight(item.difficulty) * _time_decay_weight(
            answered_at=_to_utc(item.answered_at),
            now=now,
            half_life_days=half_life_days,
        )
        weight = base_weight * max(0.0, item.coverage_weight)
        weighted_total += weight
        if item.is_correct:
            weighted_correct += weight

    if weighted_total <= 0:
        return 0.0
    return min(1.0, max(0.0, weighted_correct / weighted_total))


def compute_confidence_score(*, total_attempts: int) -> float:
    bounded_attempts = max(0, total_attempts)
    return min(1.0, bounded_attempts / 10.0)


def compute_stability_score(*, consecutive_correct: int) -> float:
    bounded_streak = max(0, consecutive_correct)
    return min(1.0, bounded_streak / 5.0)


def _compute_consecutive_correct(
    *,
    existing_stability_score: float,
    new_attempts: list[_WeightedAttempt],
) -> int:
    streak = max(0, int(round(existing_stability_score * 5)))
    for item in sorted(new_attempts, key=lambda x: _to_utc(x.answered_at)):
        if item.is_correct:
            streak += 1
        else:
            streak = 0
    return streak


def _merge_mastery_score(
    *,
    existing: UserKnowledgeState | None,
    current_exam_score: float,
    current_exam_weight: float,
) -> float:
    if existing is None:
        return current_exam_score

    history_weight = float(max(1, existing.total_attempts))
    fresh_weight = max(1.0, current_exam_weight * 1.5)
    alpha = fresh_weight / (history_weight + fresh_weight)
    alpha = min(0.85, max(0.25, alpha))
    merged = existing.mastery_score * (1.0 - alpha) + current_exam_score * alpha
    return min(1.0, max(0.0, merged))


def _parse_node_links(node_refs_json: str) -> list[tuple[int, float]]:
    try:
        payload = json.loads(node_refs_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []

    links: list[tuple[int, float]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        node_id = row.get("knowledge_node_id")
        coverage_weight = row.get("coverage_weight", 0.0)
        if not isinstance(node_id, int):
            continue
        try:
            weight = float(coverage_weight)
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        links.append((node_id, weight))

    total_weight = sum(weight for _, weight in links)
    if total_weight <= 0:
        return []
    return [(node_id, weight / total_weight) for node_id, weight in links]


def _upsert_state_from_attempts(
    session: Session,
    *,
    user_id: str,
    subject: str,
    teaching_unit_id: int | None = None,
    knowledge_node_id: int | None = None,
    attempts: list[_WeightedAttempt],
    now: datetime,
    source_exam_paper_id: int | None = None,
) -> UserKnowledgeState | None:
    if not attempts:
        return None
    if (teaching_unit_id is None) == (knowledge_node_id is None):
        raise ValueError("Exactly one mastery target must be provided.")

    existing = profile_repo.get_knowledge_state(
        session,
        user_id=user_id,
        subject=subject,
        teaching_unit_id=teaching_unit_id,
        knowledge_node_id=knowledge_node_id,
    )

    current_exam_score = _compute_weighted_mastery_score(attempts=attempts, now=now)
    current_exam_weight = sum(max(0.0, item.coverage_weight) for item in attempts)
    mastery_score = _merge_mastery_score(
        existing=existing,
        current_exam_score=current_exam_score,
        current_exam_weight=current_exam_weight,
    )

    delta_total = len(attempts)
    delta_correct = sum(1 for item in attempts if item.is_correct)
    total_attempts = (existing.total_attempts if existing is not None else 0) + delta_total
    correct_attempts = (existing.correct_attempts if existing is not None else 0) + delta_correct

    consecutive_correct = _compute_consecutive_correct(
        existing_stability_score=(existing.stability_score if existing is not None else 0.0),
        new_attempts=attempts,
    )
    confidence_score = compute_confidence_score(total_attempts=total_attempts)
    stability_score = compute_stability_score(consecutive_correct=consecutive_correct)
    last_attempt_at = max(_to_utc(item.answered_at) for item in attempts)

    state = UserKnowledgeState(
        user_id=user_id,
        subject=subject,
        teaching_unit_id=teaching_unit_id,
        knowledge_node_id=knowledge_node_id,
        mastery_score=mastery_score,
        confidence_score=confidence_score,
        stability_score=stability_score,
        forgetting_due_at=(existing.forgetting_due_at if existing is not None else None),
        review_priority=1.0 - mastery_score,
        total_attempts=total_attempts,
        correct_attempts=correct_attempts,
        last_attempt_at=last_attempt_at,
        review_status=(existing.review_status if existing is not None else "idle"),
        scheduled_review_at=(existing.scheduled_review_at if existing is not None else None),
        review_interval_days=(existing.review_interval_days if existing is not None else 1),
        review_ease_factor=(existing.review_ease_factor if existing is not None else 2.5),
        review_repetition_count=(existing.review_repetition_count if existing is not None else 0),
        review_reason=(existing.review_reason if existing is not None else None),
        source_exam_paper_id=source_exam_paper_id,
        state_version=((existing.state_version + 1) if existing is not None else 1),
        last_recomputed_at=now,
        stats_json=(existing.stats_json if existing is not None else "{}"),
        updated_at=now,
    )
    return profile_repo.upsert_knowledge_state(session, state)


def update_mastery_from_exam(session: Session, exam_paper_id: int) -> MasteryUpdateResult:
    """Update mastery from graded exam paper items."""

    exam_paper = session.get(ExamPaper, exam_paper_id)
    if exam_paper is None:
        raise ValueError(f"ExamPaper `{exam_paper_id}` not found.")

    items = exams_repo.list_items_by_paper(session, exam_paper_id)

    unit_attempts: dict[int, list[_WeightedAttempt]] = {}
    node_attempts: dict[int, list[_WeightedAttempt]] = {}

    for item in items:
        if item.is_correct is None:
            continue
        answered_at = item.answered_at or item.updated_at or item.created_at
        base = _WeightedAttempt(
            is_correct=item.is_correct,
            difficulty=item.difficulty,
            answered_at=answered_at,
            coverage_weight=1.0,
        )
        unit_attempts.setdefault(item.teaching_unit_id, []).append(base)

        for node_id, normalized_weight in _parse_node_links(item.node_refs_json):
            node_attempts.setdefault(node_id, []).append(
                _WeightedAttempt(
                    is_correct=item.is_correct,
                    difficulty=item.difficulty,
                    answered_at=answered_at,
                    coverage_weight=normalized_weight,
                )
            )

    now = utcnow()
    updated_state_ids: list[int] = []

    for target_id, target_attempts in unit_attempts.items():
        persisted = _upsert_state_from_attempts(
            session,
            user_id=exam_paper.user_id,
            subject=exam_paper.subject,
            teaching_unit_id=target_id,
            attempts=target_attempts,
            now=now,
            source_exam_paper_id=exam_paper_id,
        )
        if persisted is not None and persisted.id is not None:
            updated_state_ids.append(persisted.id)

    for target_id, target_attempts in node_attempts.items():
        persisted = _upsert_state_from_attempts(
            session,
            user_id=exam_paper.user_id,
            subject=exam_paper.subject,
            knowledge_node_id=target_id,
            attempts=target_attempts,
            now=now,
            source_exam_paper_id=exam_paper_id,
        )
        if persisted is not None and persisted.id is not None:
            updated_state_ids.append(persisted.id)

    return MasteryUpdateResult(
        exam_paper_id=exam_paper_id,
        states_updated=len(set(updated_state_ids)),
        updated_state_ids=sorted(set(updated_state_ids)),
        already_consumed=False,
    )
