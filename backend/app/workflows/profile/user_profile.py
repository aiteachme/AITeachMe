"""User-level profile aggregation shared by profile and examine services."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.models import (
    ExamMode,
    ExamPaper,
    ExamPaperItem,
    Subject,
    User,
    UserKnowledgeState,
    exam_mode_value,
)
from app.utils.time import is_at_or_after, is_at_or_before, utcnow
from app.workflows.profile.subject_profile import SubjectProfileSummary

_RECENT_EXAM_ITEM_LIMIT = 300
_RECENT_EXAM_PAPER_LIMIT = 80


class UserProfileSummary(BaseModel):
    user_id: str
    generated_at: datetime
    active_subject_count: int = 0
    active_subject_ids: list[str] = Field(default_factory=list)
    recent_subject_ids: list[str] = Field(default_factory=list)
    preferred_question_types: list[str] = Field(default_factory=list)
    preferred_exam_modes: list[str] = Field(default_factory=list)
    dominant_exam_mode: str = ExamMode.WEB_PRACTICE.value
    explanation_style: str = "balanced"
    pace_preference: str = "steady"
    consistency_level: str = "building"
    pending_review_count: int = 0
    due_review_count: int = 0
    notes: list[str] = Field(default_factory=list)


def _parse_json_object(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _load_user_record(session: Session, *, user_id: str) -> User | None:
    return session.get(User, user_id)


def _load_active_subjects(session: Session, *, user_id: str) -> list[Subject]:
    stmt = (
        select(Subject)
        .where(
            Subject.user_id == user_id,
            Subject.status == "active",
        )
        .order_by(Subject.updated_at.desc(), Subject.id.desc())
    )
    return list(session.exec(stmt).all())


def _load_recent_exam_papers(session: Session, *, user_id: str) -> list[ExamPaper]:
    stmt = (
        select(ExamPaper)
        .where(ExamPaper.user_id == user_id)
        .order_by(ExamPaper.created_at.desc(), ExamPaper.id.desc())
        .limit(_RECENT_EXAM_PAPER_LIMIT)
    )
    return list(session.exec(stmt).all())


def _load_recent_exam_items(session: Session, *, user_id: str) -> list[ExamPaperItem]:
    stmt = (
        select(ExamPaperItem)
        .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
        .where(
            ExamPaper.user_id == user_id,
            ExamPaperItem.is_correct.is_not(None),
        )
        .order_by(ExamPaperItem.answered_at.desc(), ExamPaperItem.id.desc())
        .limit(_RECENT_EXAM_ITEM_LIMIT)
    )
    return list(session.exec(stmt).all())


def _pick_top_keys(counter: Counter[str], *, limit: int) -> list[str]:
    if not counter:
        return []
    ordered = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [key for key, _ in ordered[:limit]]


def _pick_recent_subject_ids(recent_papers: list[ExamPaper]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for paper in recent_papers:
        subject = (paper.subject or "").strip()
        if not subject or subject in seen:
            continue
        seen.add(subject)
        ordered.append(subject)
        if len(ordered) >= 5:
            break
    return ordered


def _load_subject_profiles(subjects: list[Subject]) -> list[SubjectProfileSummary]:
    profiles: list[SubjectProfileSummary] = []
    for subject in subjects:
        payload = _parse_json_object(subject.profile_json)
        if not payload:
            continue
        try:
            profiles.append(SubjectProfileSummary.model_validate(payload))
        except Exception:
            continue
    return profiles


def _pick_explanation_style(type_totals: Counter[str]) -> str:
    short_answer_total = type_totals.get("short_answer", 0)
    choice_total = type_totals.get("single_choice", 0)
    blank_total = type_totals.get("fill_blank", 0)
    if short_answer_total > max(choice_total, blank_total):
        return "guided"
    if choice_total + blank_total >= max(2, short_answer_total * 2):
        return "concise"
    return "balanced"


def _pick_pace_preference(
    *,
    recent_papers: list[ExamPaper],
    generated_at: datetime,
) -> str:
    recent_window_start = generated_at - timedelta(days=14)
    recent_window = [
        paper
        for paper in recent_papers
        if is_at_or_after(paper.created_at, recent_window_start)
    ]
    recent_count = len(recent_window)
    if recent_count >= 6:
        return "quick_cycle"

    durations = [
        int(paper.duration_seconds)
        for paper in recent_window
        if paper.duration_seconds is not None
    ]
    if durations:
        avg_duration = sum(durations) / len(durations)
        if avg_duration >= 2400:
            return "deep_dive"

    return "steady"


def _pick_consistency_level(
    *,
    recent_papers: list[ExamPaper],
    generated_at: datetime,
) -> str:
    active_days = {
        paper.created_at.date().isoformat()
        for paper in recent_papers
        if is_at_or_after(paper.created_at, generated_at - timedelta(days=30))
    }
    if len(active_days) >= 10:
        return "high"
    if len(active_days) >= 4:
        return "steady"
    return "building"


def _build_notes(
    *,
    active_subject_count: int,
    dominant_exam_mode: str,
    due_review_count: int,
    preferred_question_types: list[str],
) -> list[str]:
    notes = [
        f"Active subjects: {active_subject_count}",
        f"Dominant exam mode: {dominant_exam_mode}",
        f"Due reviews across subjects: {due_review_count}",
    ]
    if preferred_question_types:
        notes.append("Preferred question types: " + ", ".join(preferred_question_types))
    return notes


def build_user_profile_summary(
    session: Session,
    *,
    user_id: str,
) -> UserProfileSummary:
    generated_at = utcnow()
    subjects = _load_active_subjects(session, user_id=user_id)
    subject_profiles = _load_subject_profiles(subjects)
    recent_papers = _load_recent_exam_papers(session, user_id=user_id)
    recent_items = _load_recent_exam_items(session, user_id=user_id)

    question_type_totals = Counter(item.question_type for item in recent_items if item.question_type)
    exam_mode_totals = Counter(
        exam_mode_value(paper.exam_mode)
        for paper in recent_papers
        if paper.exam_mode
    )

    if not question_type_totals:
        question_type_totals.update(
            question_type
            for profile in subject_profiles
            for question_type in profile.preferred_question_types
        )
    if not exam_mode_totals:
        exam_mode_totals.update(
            profile.recommended_exam_mode
            for profile in subject_profiles
            if profile.recommended_exam_mode
        )

    pending_reviews = list(
        session.exec(
            select(UserKnowledgeState).where(
                UserKnowledgeState.user_id == user_id,
                UserKnowledgeState.review_status == "pending",
            )
        ).all()
    )
    due_review_count = sum(
        1
        for state in pending_reviews
        if state.scheduled_review_at is None or is_at_or_before(state.scheduled_review_at, generated_at)
    )

    preferred_question_types = _pick_top_keys(question_type_totals, limit=3)
    preferred_exam_modes = _pick_top_keys(exam_mode_totals, limit=3)
    dominant_exam_mode = preferred_exam_modes[0] if preferred_exam_modes else ExamMode.WEB_PRACTICE.value

    return UserProfileSummary(
        user_id=user_id,
        generated_at=generated_at,
        active_subject_count=len(subjects),
        active_subject_ids=[subject.slug for subject in subjects if subject.slug],
        recent_subject_ids=_pick_recent_subject_ids(recent_papers),
        preferred_question_types=preferred_question_types,
        preferred_exam_modes=preferred_exam_modes,
        dominant_exam_mode=dominant_exam_mode,
        explanation_style=_pick_explanation_style(question_type_totals),
        pace_preference=_pick_pace_preference(
            recent_papers=recent_papers,
            generated_at=generated_at,
        ),
        consistency_level=_pick_consistency_level(
            recent_papers=recent_papers,
            generated_at=generated_at,
        ),
        pending_review_count=len(pending_reviews),
        due_review_count=due_review_count,
        notes=_build_notes(
            active_subject_count=len(subjects),
            dominant_exam_mode=dominant_exam_mode,
            due_review_count=due_review_count,
            preferred_question_types=preferred_question_types,
        ),
    )


def load_user_profile_summary(
    session: Session,
    *,
    user_id: str,
) -> UserProfileSummary | None:
    user = _load_user_record(session, user_id=user_id)
    if user is None:
        return None

    payload = _parse_json_object(user.profile_json)
    if not payload:
        return None

    try:
        return UserProfileSummary.model_validate(payload)
    except Exception:
        return None


def refresh_user_profile_summary(
    session: Session,
    *,
    user_id: str,
    auto_commit: bool = True,
) -> UserProfileSummary:
    user = _load_user_record(session, user_id=user_id)
    if user is None:
        raise ValueError(f"User `{user_id}` not found.")

    summary = build_user_profile_summary(session, user_id=user_id)
    user.profile_json = summary.model_dump_json()
    user.updated_at = utcnow()
    session.add(user)
    if auto_commit:
        session.commit()
        session.refresh(user)
    else:
        session.flush()
    return summary
