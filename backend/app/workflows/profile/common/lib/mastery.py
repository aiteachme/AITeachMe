"""Mastery updater driven by graded exam paper items."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from math import exp

from sqlmodel import Session

from app.models import ExamPaper, UserKnowledgeState
from app.repositories import exams_repo, profile_repo
from app.utils.time import utcnow

_DIFFICULTY_WEIGHT = {
    "easy": 0.8,
    "medium": 1.0,
    "hard": 1.2,
}
_CONSUMED_EXAM_PAPER_IDS_KEY = "consumed_exam_paper_ids"
_MAX_STATE_WRITE_ATTEMPTS = 5


@dataclass(frozen=True)
class _WeightedAttempt:
    is_correct: bool
    difficulty: str
    answered_at: datetime
    score_ratio: float = 1.0
    coverage_weight: float = 1.0
    question_type: str = ""
    time_spent_seconds: int | None = None
    hint_used: bool = False
    confidence_self_report: int | None = None
    error_cause_label: str | None = None


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
        weighted_correct += weight * min(1.0, max(0.0, item.score_ratio))

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
            continue
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


def _parse_json_object(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _to_counter(raw: object) -> Counter[str]:
    if not isinstance(raw, dict):
        return Counter()

    counter: Counter[str] = Counter()
    for key, value in raw.items():
        if not isinstance(key, str):
            continue
        try:
            counter[key] = int(value)
        except (TypeError, ValueError):
            continue
    return counter


def _consumed_exam_paper_ids(payload: dict[str, object]) -> set[int]:
    raw = payload.get(_CONSUMED_EXAM_PAPER_IDS_KEY)
    if not isinstance(raw, list):
        return set()

    consumed: set[int] = set()
    for value in raw:
        try:
            paper_id = int(value)
        except (TypeError, ValueError):
            continue
        if paper_id > 0:
            consumed.add(paper_id)
    return consumed


def _state_has_consumed_exam(
    state: UserKnowledgeState | None,
    exam_paper_id: int | None,
) -> bool:
    if state is None or not exam_paper_id or exam_paper_id <= 0:
        return False

    payload = _parse_json_object(state.stats_json)
    if int(exam_paper_id) in _consumed_exam_paper_ids(payload):
        return True

    # Backfill idempotency for states written before stats_json tracked
    # explicit consumed paper ids.
    return state.source_exam_paper_id == int(exam_paper_id)


def _merge_attempt_stats(
    *,
    existing: UserKnowledgeState | None,
    attempts: list[_WeightedAttempt],
    source_exam_paper_id: int | None = None,
) -> str:
    payload = _parse_json_object(existing.stats_json if existing is not None else None)
    question_type_counts = _to_counter(payload.get("question_type_counts"))
    difficulty_counts = _to_counter(payload.get("difficulty_counts"))
    error_cause_counts = _to_counter(payload.get("error_cause_counts"))

    hint_used_count = int(payload.get("hint_used_count", 0) or 0)
    timed_attempt_count = int(payload.get("timed_attempt_count", 0) or 0)
    total_time_spent_seconds = int(payload.get("total_time_spent_seconds", 0) or 0)
    confidence_self_report_count = int(payload.get("confidence_self_report_count", 0) or 0)
    confidence_self_report_sum = int(payload.get("confidence_self_report_sum", 0) or 0)
    consumed_exam_paper_ids = _consumed_exam_paper_ids(payload)
    if source_exam_paper_id is not None and source_exam_paper_id > 0:
        consumed_exam_paper_ids.add(int(source_exam_paper_id))

    latest_attempt = max(attempts, key=lambda item: _to_utc(item.answered_at)) if attempts else None
    for item in attempts:
        if item.question_type:
            question_type_counts[item.question_type] += 1
        if item.difficulty:
            difficulty_counts[item.difficulty] += 1
        if (
            not item.is_correct
            and item.error_cause_label
            and item.error_cause_label != "unknown"
        ):
            error_cause_counts[item.error_cause_label] += 1
        if item.hint_used:
            hint_used_count += 1
        if item.time_spent_seconds is not None and item.time_spent_seconds >= 0:
            timed_attempt_count += 1
            total_time_spent_seconds += int(item.time_spent_seconds)
        if item.confidence_self_report is not None:
            confidence_self_report_count += 1
            confidence_self_report_sum += int(item.confidence_self_report)

    payload.update(
        {
            "question_type_counts": dict(sorted(question_type_counts.items())),
            "difficulty_counts": dict(sorted(difficulty_counts.items())),
            "error_cause_counts": dict(sorted(error_cause_counts.items())),
            "hint_used_count": hint_used_count,
            "timed_attempt_count": timed_attempt_count,
            "total_time_spent_seconds": total_time_spent_seconds,
            "avg_time_spent_seconds": (
                round(total_time_spent_seconds / timed_attempt_count, 2)
                if timed_attempt_count > 0
                else None
            ),
            "confidence_self_report_count": confidence_self_report_count,
            "confidence_self_report_sum": confidence_self_report_sum,
            "avg_confidence_self_report": (
                round(confidence_self_report_sum / confidence_self_report_count, 2)
                if confidence_self_report_count > 0
                else None
            ),
            "last_question_type": (latest_attempt.question_type if latest_attempt is not None else None),
            "last_difficulty": (latest_attempt.difficulty if latest_attempt is not None else None),
            "last_error_cause_label": (
                latest_attempt.error_cause_label
                if latest_attempt is not None and not latest_attempt.is_correct
                else None
            ),
            _CONSUMED_EXAM_PAPER_IDS_KEY: sorted(consumed_exam_paper_ids),
        }
    )
    return json.dumps(payload, ensure_ascii=False)


def _normalize_knowledge_unit_links(payload: list[dict[str, object]]) -> list[tuple[int, float]]:
    links: list[tuple[int, float]] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        node_id = row.get("knowledge_unit_id")
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


def _score_ratio(score_obtained: float | None, score_max: float | None, is_correct: bool) -> float:
    if score_obtained is None or score_max is None or score_max <= 0:
        return 1.0 if is_correct else 0.0
    return min(1.0, max(0.0, float(score_obtained) / float(score_max)))


def _upsert_state_from_attempts(
    session: Session,
    *,
    user_id: str,
    course_id: str,
    knowledge_unit_id: int | None = None,
    attempts: list[_WeightedAttempt],
    now: datetime,
    source_exam_paper_id: int | None = None,
    auto_commit: bool = True,
) -> UserKnowledgeState | None:
    if not attempts:
        return None
    if knowledge_unit_id is None:
        raise ValueError("knowledge_unit_id must be provided.")

    for _attempt in range(_MAX_STATE_WRITE_ATTEMPTS):
        existing = profile_repo.get_knowledge_state(
            session,
            user_id=user_id,
            course_id=course_id,
            knowledge_unit_id=knowledge_unit_id,
        )
        if _state_has_consumed_exam(existing, source_exam_paper_id):
            return None

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
            course_id=course_id,
            knowledge_unit_id=knowledge_unit_id,
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
            stats_json=_merge_attempt_stats(
                existing=existing,
                attempts=attempts,
                source_exam_paper_id=source_exam_paper_id,
            ),
            updated_at=now,
        )
        persisted = profile_repo.compare_and_set_knowledge_state(
            session,
            state,
            expected_state_version=(existing.state_version if existing is not None else None),
            auto_commit=auto_commit,
        )
        if persisted is not None:
            return persisted

    raise RuntimeError(
        "UserKnowledgeState changed repeatedly while applying one exam; please retry the profile update."
    )


def update_mastery_from_exam(
    session: Session,
    exam_paper_id: int,
    *,
    auto_commit: bool = True,
) -> MasteryUpdateResult:
    """Update mastery from graded exam paper items."""

    exam_paper = session.get(ExamPaper, exam_paper_id)
    if exam_paper is None:
        raise ValueError(f"ExamPaper `{exam_paper_id}` not found.")

    items = exams_repo.list_items_by_paper(session, exam_paper_id)
    links_by_item_id = exams_repo.list_links_for_exam_items(session, [int(item.id or 0) for item in items])

    node_attempts: dict[int, list[_WeightedAttempt]] = {}

    for item in items:
        if item.is_correct is None:
            continue
        answered_at = item.answered_at or item.updated_at or item.created_at
        knowledge_unit_links = _normalize_knowledge_unit_links(links_by_item_id.get(int(item.id or 0), []))
        for node_id, normalized_weight in knowledge_unit_links:
            node_attempts.setdefault(node_id, []).append(
                _WeightedAttempt(
                    is_correct=item.is_correct,
                    difficulty=item.difficulty,
                    answered_at=answered_at,
                    score_ratio=_score_ratio(item.score_obtained, item.score_max, item.is_correct),
                    coverage_weight=normalized_weight,
                    question_type=item.question_type,
                    time_spent_seconds=item.time_spent_seconds,
                    hint_used=item.hint_used,
                    confidence_self_report=item.confidence_self_report,
                    error_cause_label=item.error_cause_label,
                )
            )

    now = utcnow()
    updated_state_ids: list[int] = []
    consumed_state_count = 0

    for target_id, target_attempts in sorted(node_attempts.items()):
        persisted = _upsert_state_from_attempts(
            session,
            user_id=exam_paper.user_id,
            course_id=exam_paper.course_id,
            knowledge_unit_id=target_id,
            attempts=target_attempts,
            now=now,
            source_exam_paper_id=exam_paper_id,
            auto_commit=auto_commit,
        )
        if persisted is None:
            consumed_state_count += 1
        elif persisted.id is not None:
            updated_state_ids.append(persisted.id)

    return MasteryUpdateResult(
        exam_paper_id=exam_paper_id,
        states_updated=len(set(updated_state_ids)),
        updated_state_ids=sorted(set(updated_state_ids)),
        already_consumed=bool(node_attempts) and consumed_state_count == len(node_attempts),
    )
