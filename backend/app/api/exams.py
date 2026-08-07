"""Exams API endpoints."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from datetime import timedelta

import structlog
from fastapi import APIRouter, BackgroundTasks, Body, Depends, Path, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_course_id
from app.api.openapi import build_error_responses
from app.api.sse import get_sse_interval, sse_headers
from app.models import (
    ExamPaper,
    ExamPaperItem,
    ExamProfileSync,
    MasteryDrillAttempt,
    MasteryDrillSession,
    QuestionTemplate,
    QuestionTypeRegistry,
    User,
    exam_mode_value,
)
from app.models.knowledge_unit import KnowledgeUnit
from app.models.course import Course
from app.repositories import exams_repo, knowledge_relation_repo
from app.repositories import profile_repo
from app.schemas.common import ApiResponse, PageParams, PaginatedData, build_paginated_data, ok_response
from app.schemas.exams import (
    ExamGenerateRequest,
    ExamGenerateResponse,
    ExamGenerationProgress,
    ExamGradeResponse,
    ExamHistoryItem,
    MasteryDrillHistorySummary,
    ExamPaperDeleteResponse,
    ExamPaperDetailResponse,
    ExamPaperItemResponse,
    ExamProfileSyncResponse,
    ExamPrewarmStatusResponse,
    QuestionTemplateAnswerHistoryItem,
    QuestionTemplateGradeRequest,
    QuestionTemplateGradeResponse,
    QuestionTemplateMarkRequest,
    QuestionTemplateMarkResponse,
    QuestionTemplateItemResponse,
    QuestionTypeRegistryItemResponse,
    PaperPreview,
    ExamStudyGuideFocusUnit,
    ExamStudyGuideResponse,
    ExamSubmitRequest,
    MasteryDrillAttemptRequest,
    MasteryDrillAttemptResponse,
    MasteryDrillCompleteRequest,
    MasteryDrillSessionResponse,
    MasteryDrillStartRequest,
)
from app.shared.infra.analytics.posthog import capture_product_event_later
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.database import managed_session
from app.shared.kernel.question_types import (
    UnsupportedQuestionTypeError,
    is_supported_question_type,
    require_supported_question_type_key,
)
from app.shared.infra.workflow.live_stream import (
    format_sse_event,
    publish_workflow_stream_event,
    subscribe_workflow_stream,
)
from app.utils.time import ensure_utc_datetime, utcnow
from app.workflows.examine import (
    run_exam_grade_workflow,
    run_exam_study_guide_workflow,
    run_question_build_workflow,
)
from app.workflows.profile.sync import (
    is_exam_profile_sync_recoverable_now,
    run_exam_profile_sync_background,
    schedule_exam_profile_sync_task,
)
from app.workflows.support.auth import set_guest_cookie_for_user
from app.workflows.support.courses.learning_context import load_course_llm_context

router = APIRouter(prefix="/api/v1/courses/{course_id}/exams", tags=["exams"])
logger = structlog.get_logger(__name__)

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")
PAPER_PREVIEW_ROW_LIMIT = 7
RECENT_EXAM_STEM_AVOID_LIMIT = 18
_SYNC_EDGE_MARKER_PREFIX = "markdown_anchor_sync:"
EXAM_PREWARM_CONFIG_VERSION = 1
EXAM_PREWARM_TTL_DAYS = 2
DEFAULT_AUTO_PREWARM_EXAM_MODE = "web_practice"
DEFAULT_AUTO_PREWARM_QUESTION_COUNT = 10
EXAM_GENERATION_STALE_AFTER = timedelta(minutes=20)
EXAM_GRADING_LEASE_DURATION = timedelta(minutes=5)
EXAM_GRADING_HEARTBEAT_SECONDS = 60.0
EXAM_GRADING_RECOVERY_INTERVAL_SECONDS = 30.0
EXAM_GRADING_RETRY_MAX_SECONDS = 300.0
EXAM_GRADING_MAX_ATTEMPTS = 3
MASTERY_DRILL_ATTEMPT_LEASE_DURATION = timedelta(minutes=5)
MASTERY_DRILL_ATTEMPT_HEARTBEAT_SECONDS = 60.0
EXAM_GENERATION_STALE_MESSAGE = "生成超时，请重新生成。"
EXAM_GENERATION_INCOMPLETE_MESSAGE = "题目生成未完成，请重新生成。"
PAPER_LAYOUT_CONFIG_VERSION = 1
PAPER_LAYOUT_MODES = {
    "auto",
    "standard_two_page",
    "gaokao_four_page",
    "gaokao_six_page",
    "gaokao_eight_page",
}
_PROFILE_UPDATE_CONTEXT_KEY = "profile_update"


def _require_supported_question_type_for_api(value: object) -> str:
    try:
        return require_supported_question_type_key(value)
    except UnsupportedQuestionTypeError as exc:
        question_type = exc.question_type or "<empty>"
        raise AITeachMeError(
            detail=f"当前版本不支持题型 `{question_type}`。",
            error_code="UNSUPPORTED_QUESTION_TYPE",
            status_code=409,
            data={"question_type": exc.question_type},
        ) from exc


def _require_generic_exam_mode(mode: str) -> str:
    if mode == "mastery_drill":
        raise AITeachMeError(
            detail="Mastery drills must use the dedicated start, attempt, and complete endpoints.",
            error_code="MASTERY_DRILL_DEDICATED_ENDPOINT_REQUIRED",
            status_code=409,
        )
    return mode


def _require_supported_exam_items(items: list[ExamPaperItem]) -> None:
    for item in items:
        _require_supported_question_type_for_api(item.question_type)


def _resolve_exam_submission_answers(
    items: list[ExamPaperItem],
    body: ExamSubmitRequest,
) -> tuple[dict[int, str], str, str]:
    answer_by_id = {
        int(item.exam_paper_item_id): str(item.answer or "")
        for item in body.answers
        if item.exam_paper_item_id is not None
    }
    answer_by_order = {
        int(item.item_order): str(item.answer or "")
        for item in body.answers
        if item.item_order is not None
    }
    resolved: dict[int, str] = {}
    canonical_items: list[dict[str, object]] = []
    for item in items:
        item_id = int(item.id or 0)
        answer = answer_by_id[item_id] if item_id in answer_by_id else answer_by_order.get(item.item_order, "")
        resolved[item_id] = answer
        canonical_items.append(
            {
                "exam_paper_item_id": item_id,
                "item_order": int(item.item_order),
                "answer": answer,
            }
        )
    canonical_json = json.dumps(canonical_items, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    submission_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    submission_key = str(body.submission_key or "").strip() or submission_hash
    return resolved, submission_hash, submission_key


def _exam_profile_sync_response(
    session: Session,
    paper: ExamPaper,
    *,
    task: ExamProfileSync | None = None,
) -> ExamProfileSyncResponse:
    current = task or exams_repo.get_exam_profile_sync(session, paper_id=int(paper.id or 0))
    if current is not None:
        status = str(current.status or "pending")
        if status not in {"pending", "processing", "retry_wait", "completed", "failed"}:
            status = "failed"
        return ExamProfileSyncResponse(
            exam_paper_id=int(paper.id or 0),
            status=status,
            attempt_count=max(0, int(current.attempt_count or 0)),
            manual_retry_count=max(0, int(current.manual_retry_count or 0)),
            next_attempt_at=current.next_attempt_at,
            last_error_code=str(current.last_error_code or "").strip() or None,
            states_updated=max(0, int(current.states_updated or 0)),
            review_task_count=max(0, int(current.review_task_count or 0)),
            can_retry=status in {"retry_wait", "failed"},
            updated_at=current.updated_at,
        )

    legacy = _json_dict(paper.selection_context_json).get(_PROFILE_UPDATE_CONTEXT_KEY)
    legacy_payload = legacy if isinstance(legacy, dict) else {}
    legacy_status = str(legacy_payload.get("status") or "")
    status = "completed" if legacy_status == "completed" else "not_tracked"
    return ExamProfileSyncResponse(
        exam_paper_id=int(paper.id or 0),
        status=status,
        attempt_count=max(0, int(legacy_payload.get("attempt_count") or 0)),
        last_error_code=str(legacy_payload.get("last_error_code") or "").strip() or None,
        states_updated=max(0, int(legacy_payload.get("states_updated") or 0)),
        review_task_count=max(0, int(legacy_payload.get("review_task_count") or 0)),
        can_retry=legacy_status in {"failed", "running"},
        updated_at=paper.updated_at,
    )


def _ensure_legacy_exam_profile_sync(session: Session, paper: ExamPaper) -> ExamProfileSync | None:
    if paper.status != "graded":
        return None
    existing = exams_repo.get_exam_profile_sync(session, paper_id=int(paper.id or 0))
    if existing is not None:
        return existing
    legacy = _json_dict(paper.selection_context_json).get(_PROFILE_UPDATE_CONTEXT_KEY)
    if not isinstance(legacy, dict):
        return None
    legacy_status = str(legacy.get("status") or "")
    if legacy_status == "completed":
        return exams_repo.ensure_exam_profile_sync(
            session,
            paper=paper,
            status="completed",
            trigger="legacy_profile_update",
            states_updated=int(legacy.get("states_updated") or 0),
            review_task_count=int(legacy.get("review_task_count") or 0),
            auto_commit=True,
        )
    if legacy_status in {"failed", "running"}:
        return exams_repo.ensure_exam_profile_sync(
            session,
            paper=paper,
            status="pending",
            trigger="legacy_profile_recovery",
            auto_commit=True,
        )
    return None


def _exam_grade_response_from_paper(session: Session, paper: ExamPaper) -> ExamGradeResponse:
    profile_sync = _exam_profile_sync_response(session, paper)
    return ExamGradeResponse(
        id=int(paper.id or 0),
        status="completed" if paper.status == "graded" else paper.status,
        error_message=paper.grading_last_error or None,
        created_at=paper.created_at,
        updated_at=paper.updated_at,
        exam_paper_id=int(paper.id or 0),
        score=paper.score_obtained,
        states_updated=profile_sync.states_updated,
        tasks_created=profile_sync.review_task_count,
        mastery_consumed=profile_sync.status == "completed",
        profile_sync=profile_sync,
    )


def _is_exam_grading_recoverable_now(paper: ExamPaper, *, as_of=None) -> bool:
    now = ensure_utc_datetime(as_of) or utcnow()
    if int(paper.grading_attempts or 0) >= EXAM_GRADING_MAX_ATTEMPTS:
        return False
    if paper.status == "grading":
        lease_expires_at = ensure_utc_datetime(paper.grading_lease_expires_at)
        return lease_expires_at is None or lease_expires_at <= now
    if paper.status != "submitted":
        return False
    if not str(paper.grading_last_error or "").strip():
        return True
    attempts = max(1, int(paper.grading_attempts or 0))
    retry_delay_seconds = min(EXAM_GRADING_RETRY_MAX_SECONDS, 15.0 * (2 ** min(attempts, 5)))
    updated_at = ensure_utc_datetime(paper.updated_at)
    return updated_at is None or updated_at + timedelta(seconds=retry_delay_seconds) <= now


def _exam_stream_channel(course_id: str, paper_id: int) -> str:
    return f"exam:{course_id}:{paper_id}"


def default_auto_prewarm_exam_config() -> dict[str, object]:
    return {
        "exam_mode": DEFAULT_AUTO_PREWARM_EXAM_MODE,
        "question_count": DEFAULT_AUTO_PREWARM_QUESTION_COUNT,
        "user_prompt": None,
        "sample_file_ids": [],
        "paper_layout_mode": None,
    }


def _publish_exam_event(course_id: str, paper_id: int, event: str, data: dict[str, object]) -> None:
    publish_workflow_stream_event(_exam_stream_channel(course_id, paper_id), event, data)


def _suffix(value: object, *, length: int = 8) -> str | None:
    normalized = str(value or "").strip()
    return normalized[-length:] if normalized else None


def _duration_ms(started_at, finished_at) -> int | None:
    start = ensure_utc_datetime(started_at)
    finish = ensure_utc_datetime(finished_at)
    if start is None or finish is None:
        return None
    return max(0, int((finish - start).total_seconds() * 1000))


def _capture_exam_event(
    event: str,
    *,
    course_id: str,
    user: CurrentUserContext,
    paper: ExamPaper | None = None,
    insert_id_parts: list[str] | None = None,
    properties: dict[str, object] | None = None,
) -> None:
    paper_id = int(paper.id or 0) if paper is not None and paper.id is not None else None
    event_properties = dict(properties or {})
    if paper is not None:
        event_properties.update(
            {
                "exam_paper_id_present": paper_id is not None,
                "exam_paper_id_suffix": _suffix(paper_id),
                "exam_mode": paper.exam_mode,
                "exam_status": paper.status,
                "question_count": int(paper.total_items or 0),
                "score_obtained": paper.score_obtained,
                "total_score": paper.total_score,
                "submitted_at_present": paper.submitted_at is not None,
                "graded_at_present": paper.graded_at is not None,
                "created_to_submitted_ms": _duration_ms(paper.created_at, paper.submitted_at),
                "submitted_to_graded_ms": _duration_ms(paper.submitted_at, paper.graded_at),
            }
        )
    capture_product_event_later(
        event,
        user_id=user.user_id,
        course_id=course_id,
        device_key=user.device_key,
        email=user.email,
        is_authenticated=user.is_authenticated,
        insert_id_parts=[
            str(paper_id or ""),
            *(insert_id_parts or []),
        ],
        properties=event_properties,
    )


def _analytics_user_context_from_db(session: Session, user_id: str) -> CurrentUserContext:
    user = session.get(User, user_id)
    if user is None:
        return CurrentUserContext(user_id=user_id, email=None, is_local=False)
    return CurrentUserContext(
        user_id=user.id,
        email=user.email,
        is_local=False,
        device_key=user.device_key,
        is_authenticated=bool(user.is_registered),
        auth_source="token" if user.is_registered else "device",
    )


def _capture_exam_generated_event(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    paper: ExamPaper,
    requested_question_count: int,
    sample_file_count: int,
    paper_layout_mode: str | None,
) -> None:
    if str(paper.status or "") != "ready" or str(paper.visibility or "visible") != "visible":
        return
    user = _analytics_user_context_from_db(session, user_id)
    _capture_exam_event(
        "exam_generated",
        course_id=course_id,
        user=user,
        paper=paper,
        insert_id_parts=["ready", str(paper.updated_at.isoformat())],
        properties={
            "served_from_prepared": str(paper.generation_origin or "") == "prewarm",
            "requested_question_count": requested_question_count,
            "sample_file_count": sample_file_count,
            "paper_layout_mode": paper_layout_mode,
            "generation_origin": paper.generation_origin,
        },
    )


def _ensure_course(session: Session, course_id: str, user_id: str) -> Course:
    record = session.exec(select(Course).where(Course.id == course_id, Course.user_id == user_id)).first()
    if record is None:
        _raise_not_found(f"Course `{course_id}` not found.", error_code="COURSE_NOT_FOUND")
    return record


def _json_list(raw: str | None) -> list[dict[str, object]]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in payload if isinstance(item, dict)] if isinstance(payload, list) else []


def _json_dict(raw: str | None) -> dict[str, object]:
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _hash_stem(stem: str) -> str:
    return hashlib.sha1(stem.encode("utf-8")).hexdigest()


def _raise_not_found(detail: str, error_code: str = "EXAM_NOT_FOUND") -> None:
    raise AITeachMeError(detail=detail, error_code=error_code, status_code=404)


def _clean_exam_text(value: str | None) -> str:
    text = str(value or "")
    text = _HTML_COMMENT_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _build_exam_diversity_prompt(*, run_id: str, recent_stems: list[str]) -> str:
    lines = [
        "Generation diversity constraints:",
        f"- This exam generation run id is `{run_id}`. Use it only to vary scenarios, numbers, wording, examples, and distractors.",
        "- Do not reuse exact or near-duplicate stems, options, answers, or worked examples from recent exams.",
        "- Prefer fresh surface contexts while preserving the requested knowledge units, difficulty, and question types.",
    ]
    if recent_stems:
        lines.append("- Recent stems to avoid:")
        lines.extend(f"  {index}. {stem}" for index, stem in enumerate(recent_stems, start=1))
    return "\n".join(lines)


def _build_exam_title(paper: ExamPaper) -> str:
    return f"{paper.exam_mode} · {paper.created_at.strftime('%m/%d %H:%M')}"


def _normalized_sample_file_ids(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values or []:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return sorted(normalized)


def _normalize_exam_user_prompt(value: str | None) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()


def _stable_json_hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _exam_mastery_fingerprint(session: Session, *, course_id: str, user_id: str) -> str:
    states = profile_repo.list_knowledge_states(
        session,
        user_id=user_id,
        course_id=course_id,
        target_kind="knowledge_unit",
    )
    payload = [
        {
            "knowledge_unit_id": int(state.knowledge_unit_id),
            "mastery_score": round(float(state.mastery_score), 4),
            "total_attempts": int(state.total_attempts),
            "correct_attempts": int(state.correct_attempts),
            "updated_at": state.updated_at.isoformat() if state.updated_at else "",
        }
        for state in states
        if state.knowledge_unit_id is not None
    ]
    payload.sort(key=lambda item: int(item["knowledge_unit_id"]))
    return _stable_json_hash(payload)


def _build_exam_config_snapshot(
    *,
    course_id: str,
    user_id: str,
    exam_mode: str,
    question_count: int,
    user_prompt: str | None,
    sample_file_ids: list[str] | None,
    knowledge_unit_ids: list[int],
    mastery_fingerprint: str,
    paper_layout_mode: str | None = None,
) -> dict[str, object]:
    return {
        "version": EXAM_PREWARM_CONFIG_VERSION,
        "course_id": course_id,
        "user_id": user_id,
        "exam_mode": exam_mode,
        "num_questions": int(question_count),
        "user_prompt": _normalize_exam_user_prompt(user_prompt),
        "sample_file_ids": _normalized_sample_file_ids(sample_file_ids),
        "knowledge_unit_ids": sorted({int(unit_id) for unit_id in knowledge_unit_ids if int(unit_id or 0) > 0}),
        "mastery_fingerprint": mastery_fingerprint,
        "paper_layout_mode": _normalize_paper_layout_mode(
            paper_layout_mode,
            exam_mode=exam_mode,
            question_count=question_count,
        ),
    }


def _exam_config_hash(config_snapshot: dict[str, object]) -> str:
    return _stable_json_hash(config_snapshot)


def _is_default_auto_prewarm_request(
    *,
    exam_mode: str,
    question_count: int,
    user_prompt: str | None,
    sample_file_ids: list[str] | None,
    paper_layout_mode: str | None,
) -> bool:
    default_config = default_auto_prewarm_exam_config()
    default_mode = exam_mode_value(str(default_config.get("exam_mode") or "web_practice"))
    default_question_count = int(default_config.get("question_count") or DEFAULT_AUTO_PREWARM_QUESTION_COUNT)
    default_layout = _normalize_paper_layout_mode(
        default_config.get("paper_layout_mode") if isinstance(default_config.get("paper_layout_mode"), str) else None,
        exam_mode=default_mode,
        question_count=default_question_count,
    )
    return (
        exam_mode == default_mode
        and int(question_count) == default_question_count
        and not _normalize_exam_user_prompt(user_prompt)
        and not _normalized_sample_file_ids(sample_file_ids)
        and paper_layout_mode == default_layout
    )


def _default_exam_question_count_for_mode(exam_mode: str) -> int:
    mode = exam_mode_value(exam_mode)
    if mode == "paper_exam":
        return 24
    if mode == DEFAULT_AUTO_PREWARM_EXAM_MODE:
        return DEFAULT_AUTO_PREWARM_QUESTION_COUNT
    return 8


def _prepared_snapshot_matches_default_auto_prewarm(
    paper: ExamPaper,
    *,
    exam_mode: str,
    question_count: int,
    paper_layout_mode: str | None,
) -> bool:
    snapshot = _json_dict(paper.config_snapshot_json)
    raw_mode = str(snapshot.get("exam_mode") or "")
    raw_count = snapshot.get("num_questions")
    try:
        snapshot_question_count = int(raw_count or 0)
    except (TypeError, ValueError):
        snapshot_question_count = 0
    raw_sample_file_ids = snapshot.get("sample_file_ids")
    sample_file_ids = raw_sample_file_ids if isinstance(raw_sample_file_ids, list) else []
    raw_layout = snapshot.get("paper_layout_mode")
    snapshot_layout = _normalize_paper_layout_mode(
        raw_layout if isinstance(raw_layout, str) else None,
        exam_mode=exam_mode,
        question_count=question_count,
    )
    return (
        raw_mode == exam_mode
        and snapshot_question_count == int(question_count)
        and not _normalize_exam_user_prompt(str(snapshot.get("user_prompt") or ""))
        and not _normalized_sample_file_ids([str(item) for item in sample_file_ids])
        and snapshot_layout == paper_layout_mode
    )


def _find_default_auto_prewarm_candidate(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    exam_mode: str,
    question_count: int,
    user_prompt: str | None,
    sample_file_ids: list[str] | None,
    paper_layout_mode: str | None,
) -> ExamPaper | None:
    if not _is_default_auto_prewarm_request(
        exam_mode=exam_mode,
        question_count=question_count,
        user_prompt=user_prompt,
        sample_file_ids=sample_file_ids,
        paper_layout_mode=paper_layout_mode,
    ):
        return None

    candidates = [
        paper
        for paper in exams_repo.list_prewarm_exam_candidates_by_shape(
            session,
            course_id=course_id,
            user_id=user_id,
            exam_mode=exam_mode,
            question_count=question_count,
        )
        if _prepared_snapshot_matches_default_auto_prewarm(
            paper,
            exam_mode=exam_mode,
            question_count=question_count,
            paper_layout_mode=paper_layout_mode,
        )
    ]
    if not candidates:
        return None

    for status in ("ready", "generating"):
        match = next((paper for paper in candidates if paper.status == status and _is_active_prewarm_exam_candidate(paper)), None)
        if match is not None:
            return match

    failed = next((paper for paper in candidates if paper.status == "failed"), None)
    if failed is not None:
        return failed

    stale = next((paper for paper in candidates if not _is_active_prewarm_exam_candidate(paper)), None)
    return stale or candidates[0]


def _claim_default_auto_prewarm_candidate(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    exam_mode: str,
    question_count: int,
    user_prompt: str | None,
    sample_file_ids: list[str] | None,
    paper_layout_mode: str | None,
) -> ExamPaper | None:
    candidate = _find_default_auto_prewarm_candidate(
        session,
        course_id=course_id,
        user_id=user_id,
        exam_mode=exam_mode,
        question_count=question_count,
        user_prompt=user_prompt,
        sample_file_ids=sample_file_ids,
        paper_layout_mode=paper_layout_mode,
    )
    if candidate is None or not _is_active_prewarm_exam_candidate(candidate):
        return None
    if not _is_hidden_exam_paper(candidate):
        return candidate
    return exams_repo.claim_prepared_exam_paper_by_id(session, paper_id=int(candidate.id or 0))


def _is_hidden_exam_paper(paper: ExamPaper | None) -> bool:
    return paper is None or str(getattr(paper, "visibility", "visible") or "visible") == "hidden"


def _is_active_prepared_exam_candidate(paper: ExamPaper | None) -> bool:
    if paper is None or str(getattr(paper, "visibility", "visible") or "visible") != "hidden":
        return False
    if paper.status not in {"ready", "generating"}:
        return False
    expires_at = ensure_utc_datetime(paper.expires_at)
    return expires_at is None or expires_at > utcnow()


def _is_active_prewarm_exam_candidate(paper: ExamPaper | None) -> bool:
    if paper is None or str(getattr(paper, "generation_origin", "") or "") != "prewarm":
        return False
    if paper.status not in {"ready", "generating"}:
        return False
    if paper.status == "generating":
        updated_at = ensure_utc_datetime(paper.updated_at)
        return updated_at is not None and updated_at > utcnow() - EXAM_GENERATION_STALE_AFTER
    expires_at = ensure_utc_datetime(paper.expires_at)
    return expires_at is None or expires_at > utcnow()


def _visible_active_exam_candidate(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    config_hash: str,
    question_count: int,
) -> ExamPaper | None:
    return exams_repo.get_visible_active_exam_candidate(
        session,
        course_id=course_id,
        user_id=user_id,
        config_hash=config_hash,
        question_count=question_count,
        stale_before=utcnow() - EXAM_GENERATION_STALE_AFTER,
    )


def _preview_density(difficulty: str | None) -> int:
    normalized = str(difficulty or "").lower()
    if normalized == "easy":
        return 1
    if normalized == "hard":
        return 3
    return 2


def _preview_result_status(is_correct: bool | None) -> str:
    if is_correct is True:
        return "correct"
    if is_correct is False:
        return "incorrect"
    return "ungraded"


def _preview_shape(question_type: str | None) -> str:
    normalized = str(question_type or "").lower()
    if "choice" in normalized or normalized in {"single", "multiple"}:
        return "choice"
    if "blank" in normalized or "fill" in normalized:
        return "blank"
    if "judge" in normalized or "true_false" in normalized or "boolean" in normalized:
        return "judge"
    if "chart" in normalized or "graph" in normalized:
        return "chart"
    if "formula" in normalized or "calc" in normalized or "math" in normalized:
        return "formula"
    if "code" in normalized or "program" in normalized:
        return "code"
    if "short" in normalized or "essay" in normalized or "answer" in normalized:
        return "short"
    return "text"


def _dedupe_preview_keywords(values: list[str]) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for value in values:
        cleaned = _clean_exam_text(value)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(cleaned[:18])
        if len(keywords) >= 3:
            break
    return keywords


def _build_paper_preview(
    items: list[ExamPaperItem],
    *,
    knowledge_unit_by_id: dict[int, KnowledgeUnit],
    links_by_item_id: dict[int, list[dict[str, object]]],
) -> PaperPreview:
    ordered_items = sorted(items, key=lambda item: item.item_order)
    keyword_candidates: list[str] = []
    for item in ordered_items:
        for ref in links_by_item_id.get(int(item.id or 0), []):
            knowledge_unit_id = int(ref.get("knowledge_unit_id", 0) or 0)
            unit = knowledge_unit_by_id.get(knowledge_unit_id)
            if unit is not None:
                keyword_candidates.append(unit.canonical_name)

    return PaperPreview(
        keywords=_dedupe_preview_keywords(keyword_candidates),
        question_types=_dedupe_preview_keywords([item.question_type for item in ordered_items]),
        rows=[
            {
                "order": item.item_order,
                "type": item.question_type,
                "shape": _preview_shape(item.question_type),
                "difficulty": item.difficulty,
                "density": _preview_density(item.difficulty),
                "result_status": _preview_result_status(item.is_correct),
                "generation_status": "generated",
            }
            for item in ordered_items[:PAPER_PREVIEW_ROW_LIMIT]
        ],
        overflow_count=max(0, len(ordered_items) - PAPER_PREVIEW_ROW_LIMIT),
    )


def _build_placeholder_paper_preview(*, question_count: int) -> PaperPreview:
    count = max(1, int(question_count or 1))
    return PaperPreview(
        rows=[
            {
                "order": order,
                "type": "pending",
                "shape": "text",
                "difficulty": "medium",
                "density": 2,
                "result_status": "ungraded",
                "generation_status": "pending",
            }
            for order in range(1, min(count, PAPER_PREVIEW_ROW_LIMIT) + 1)
        ],
        overflow_count=max(0, count - PAPER_PREVIEW_ROW_LIMIT),
    )


def _build_blueprint_paper_preview(
    blueprints: list[dict[str, object]],
    *,
    question_count: int,
    unit_name_by_id: dict[int, str],
) -> PaperPreview:
    blueprints = _normalize_blueprint_item_orders(blueprints)

    def blueprint_order(item: dict[str, object]) -> int:
        try:
            return int(item.get("item_order", 0) or 0)
        except (TypeError, ValueError):
            return 0

    ordered_blueprints = sorted(
        [item for item in blueprints if isinstance(item, dict)],
        key=blueprint_order,
    )
    rows: list[dict[str, object]] = []
    keyword_candidates: list[str] = []
    question_types: list[str] = []
    blueprint_by_order: dict[int, dict[str, object]] = {}
    for blueprint in ordered_blueprints:
        try:
            order = int(blueprint.get("item_order", 0) or 0)
        except (TypeError, ValueError):
            continue
        if order <= 0:
            continue
        blueprint_by_order[order] = blueprint
        question_type = str(blueprint.get("question_type") or "").strip()
        if question_type:
            question_types.append(question_type)
        for unit_id in list(blueprint.get("knowledge_unit_ids") or []):
            try:
                name = unit_name_by_id.get(int(unit_id))
            except (TypeError, ValueError):
                name = None
            if name:
                keyword_candidates.append(name)

    count = max(1, int(question_count or len(blueprint_by_order) or 1))
    for order in range(1, min(count, PAPER_PREVIEW_ROW_LIMIT) + 1):
        blueprint = blueprint_by_order.get(order, {})
        question_type = str(blueprint.get("question_type") or "pending")
        difficulty = str(blueprint.get("difficulty") or "medium")
        rows.append(
            {
                "order": order,
                "type": question_type,
                "shape": _preview_shape(question_type),
                "difficulty": difficulty,
                "density": _preview_density(difficulty),
                "result_status": "ungraded",
                "generation_status": "planned",
            }
        )

    return PaperPreview(
        keywords=_dedupe_preview_keywords(keyword_candidates),
        question_types=_dedupe_preview_keywords(question_types),
        rows=rows,
        overflow_count=max(0, count - PAPER_PREVIEW_ROW_LIMIT),
    )


def _build_question_requirement_paper_preview(
    requirement_plans: list[dict[str, object]],
    *,
    question_count: int,
) -> PaperPreview:
    plans = _normalize_blueprint_item_orders(requirement_plans)

    plan_by_order: dict[int, dict[str, object]] = {}
    question_types: list[str] = []
    for plan in plans:
        try:
            order = int(plan.get("item_order", 0) or 0)
        except (TypeError, ValueError):
            continue
        if order <= 0:
            continue
        plan_by_order[order] = plan
        question_type = str(plan.get("question_type") or "").strip()
        if question_type:
            question_types.append(question_type)

    count = max(1, int(question_count or len(plan_by_order) or 1))
    rows: list[dict[str, object]] = []
    for order in range(1, min(count, PAPER_PREVIEW_ROW_LIMIT) + 1):
        plan = plan_by_order.get(order, {})
        question_type = str(plan.get("question_type") or "pending")
        rows.append(
            {
                "order": order,
                "type": question_type,
                "shape": _preview_shape(question_type),
                "difficulty": "medium",
                "density": 2,
                "result_status": "ungraded",
                "generation_status": "planned",
            }
        )

    return PaperPreview(
        keywords=[],
        question_types=_dedupe_preview_keywords(question_types),
        rows=rows,
        overflow_count=max(0, count - PAPER_PREVIEW_ROW_LIMIT),
    )


def _normalize_blueprint_item_orders(
    blueprints: list[dict[str, object]],
) -> list[dict[str, object]]:
    normalized_blueprints = [dict(item) for item in blueprints if isinstance(item, dict)]
    if not normalized_blueprints:
        return []

    orders: list[int] = []
    for item in normalized_blueprints:
        try:
            orders.append(int(item.get("item_order", 0) or 0))
        except (TypeError, ValueError):
            return normalized_blueprints

    if set(orders) != set(range(len(normalized_blueprints))):
        return normalized_blueprints

    for item in normalized_blueprints:
        item["item_order"] = int(item.get("item_order", 0) or 0) + 1
    return normalized_blueprints


def _blueprints_by_one_based_order(
    blueprints: object,
) -> dict[int, dict[str, object]]:
    if not isinstance(blueprints, list):
        return {}
    normalized = _normalize_blueprint_item_orders(
        [item for item in blueprints if isinstance(item, dict)]
    )
    by_order: dict[int, dict[str, object]] = {}
    for item in normalized:
        try:
            order = int(item.get("item_order", 0) or 0)
        except (TypeError, ValueError):
            continue
        if order > 0:
            by_order[order] = item
    return by_order


def _positive_int(value: object) -> int:
    try:
        parsed = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return parsed if parsed > 0 else 0


def _merge_generated_question_into_preview(
    preview: PaperPreview,
    generated_question: dict[str, object],
    *,
    question_count: int,
    unit_name_by_id: dict[int, str],
) -> PaperPreview:
    order = _positive_int(generated_question.get("item_order"))
    if order <= 0:
        return preview

    count = max(1, int(question_count or len(preview.rows) or order or 1))
    rows_by_order = {
        int(row.order): row.model_dump(mode="json")
        for row in preview.rows
        if _positive_int(row.order) > 0
    }
    for pending_order in range(1, min(count, PAPER_PREVIEW_ROW_LIMIT) + 1):
        rows_by_order.setdefault(
            pending_order,
            {
                "order": pending_order,
                "type": "pending",
                "shape": "text",
                "difficulty": "medium",
                "density": 2,
                "result_status": "ungraded",
                "generation_status": "pending",
            },
        )

    if order <= PAPER_PREVIEW_ROW_LIMIT:
        existing = rows_by_order.get(order, {})
        question_type = str(generated_question.get("question_type") or existing.get("type") or "text")
        difficulty = str(generated_question.get("difficulty") or existing.get("difficulty") or "medium")
        rows_by_order[order] = {
            **existing,
            "order": order,
            "type": question_type,
            "shape": _preview_shape(question_type),
            "difficulty": difficulty,
            "density": _preview_density(difficulty),
            "result_status": str(existing.get("result_status") or "ungraded"),
            "generation_status": "generated",
        }

    keyword_candidates = list(preview.keywords or [])
    for ref in list(generated_question.get("knowledge_unit_refs") or []):
        if not isinstance(ref, dict):
            continue
        unit_name = unit_name_by_id.get(_positive_int(ref.get("knowledge_unit_id")))
        if unit_name:
            keyword_candidates.append(unit_name)

    question_types = list(preview.question_types or [])
    generated_type = str(generated_question.get("question_type") or "").strip()
    if generated_type:
        question_types.append(generated_type)

    return PaperPreview(
        keywords=_dedupe_preview_keywords(keyword_candidates),
        question_types=_dedupe_preview_keywords(question_types),
        rows=[
            rows_by_order[row_order]
            for row_order in range(1, min(count, PAPER_PREVIEW_ROW_LIMIT) + 1)
            if row_order in rows_by_order
        ],
        overflow_count=max(0, count - PAPER_PREVIEW_ROW_LIMIT),
    )


def _merge_failed_question_into_preview(
    preview: PaperPreview,
    failed_question: dict[str, object],
    *,
    question_count: int,
) -> PaperPreview:
    order = _positive_int(failed_question.get("item_order"))
    if order <= 0:
        return preview

    count = max(1, int(question_count or len(preview.rows) or order or 1))
    rows_by_order = {
        int(row.order): row.model_dump(mode="json")
        for row in preview.rows
        if _positive_int(row.order) > 0
    }
    for pending_order in range(1, min(count, PAPER_PREVIEW_ROW_LIMIT) + 1):
        rows_by_order.setdefault(
            pending_order,
            {
                "order": pending_order,
                "type": "pending",
                "shape": "text",
                "difficulty": "medium",
                "density": 2,
                "result_status": "ungraded",
                "generation_status": "pending",
            },
        )

    if order <= PAPER_PREVIEW_ROW_LIMIT:
        existing = rows_by_order.get(order, {})
        question_type = str(failed_question.get("question_type") or existing.get("type") or "text")
        difficulty = str(failed_question.get("difficulty") or existing.get("difficulty") or "medium")
        rows_by_order[order] = {
            **existing,
            "order": order,
            "type": question_type,
            "shape": _preview_shape(question_type),
            "difficulty": difficulty,
            "density": _preview_density(difficulty),
            "result_status": "ungraded",
            "generation_status": "failed",
        }

    return PaperPreview(
        keywords=list(preview.keywords or []),
        question_types=list(preview.question_types or []),
        rows=[
            rows_by_order[row_order]
            for row_order in range(1, min(count, PAPER_PREVIEW_ROW_LIMIT) + 1)
            if row_order in rows_by_order
        ],
        overflow_count=max(0, count - PAPER_PREVIEW_ROW_LIMIT),
    )


def _merge_generated_question_into_context(
    context: dict[str, object],
    generated_question: dict[str, object],
    *,
    question_count: int,
) -> dict[str, object]:
    order = _positive_int(generated_question.get("item_order"))
    if order <= 0:
        return context

    existing_items = context.get("generated_questions")
    generated_by_order: dict[int, dict[str, object]] = {}
    if isinstance(existing_items, list):
        for item in existing_items:
            if not isinstance(item, dict):
                continue
            item_order = _positive_int(item.get("item_order"))
            if item_order > 0:
                generated_by_order[item_order] = item
    generated_by_order[order] = generated_question

    max_order = max(1, int(question_count or order or 1))
    context["generated_questions"] = [
        generated_by_order[item_order]
        for item_order in range(1, max_order + 1)
        if item_order in generated_by_order
    ]
    context["generated_question_count"] = len(generated_by_order)
    return context


def _merge_failed_question_into_context(
    context: dict[str, object],
    failed_question: dict[str, object],
    *,
    question_count: int,
) -> dict[str, object]:
    order = _positive_int(failed_question.get("item_order"))
    if order <= 0:
        return context

    existing_items = context.get("failed_questions")
    failed_by_order: dict[int, dict[str, object]] = {}
    if isinstance(existing_items, list):
        for item in existing_items:
            if not isinstance(item, dict):
                continue
            item_order = _positive_int(item.get("item_order"))
            if item_order > 0:
                failed_by_order[item_order] = item
    failed_by_order[order] = failed_question

    max_order = max(1, int(question_count or order or 1))
    context["failed_questions"] = [
        failed_by_order[item_order]
        for item_order in range(1, max_order + 1)
        if item_order in failed_by_order
    ]
    context["failed_question_count"] = len(failed_by_order)
    return context


def _paper_preview_from_json(raw: str | None) -> PaperPreview:
    payload = _json_dict(raw)
    if not payload:
        return PaperPreview()
    try:
        return PaperPreview.model_validate(payload)
    except Exception:
        return PaperPreview()


def _paper_preview_for_response(
    paper: ExamPaper,
    items: list[ExamPaperItem],
    *,
    knowledge_unit_by_id: dict[int, KnowledgeUnit],
    links_by_item_id: dict[int, list[dict[str, object]]],
) -> PaperPreview:
    saved_preview = _paper_preview_from_json(getattr(paper, "paper_preview_json", "{}"))
    expected_row_count = min(len(items), PAPER_PREVIEW_ROW_LIMIT)
    saved_preview_is_complete = not items or len(saved_preview.rows) >= expected_row_count
    graded_orders = {item.item_order for item in items if item.is_correct is not None}
    saved_result_by_order = {row.order: row.result_status for row in saved_preview.rows}
    saved_preview_has_current_results = not graded_orders or all(
        saved_result_by_order.get(order) in {"correct", "incorrect"}
        for order in graded_orders
        if order <= PAPER_PREVIEW_ROW_LIMIT
    )
    if (
        (saved_preview.rows or saved_preview.keywords or saved_preview.question_types)
        and saved_preview_is_complete
        and saved_preview_has_current_results
    ):
        return saved_preview
    if not items:
        return saved_preview
    return _build_paper_preview(
        items,
        knowledge_unit_by_id=knowledge_unit_by_id,
        links_by_item_id=links_by_item_id,
    )


def _build_final_paper_preview(
    items: list[ExamPaperItem],
    *,
    existing_preview: PaperPreview,
    knowledge_unit_by_id: dict[int, KnowledgeUnit],
    links_by_item_id: dict[int, list[dict[str, object]]],
) -> PaperPreview:
    base = _build_paper_preview(
        items,
        knowledge_unit_by_id=knowledge_unit_by_id,
        links_by_item_id=links_by_item_id,
    )
    rows_by_order = {row.order: row.model_dump(mode="json") for row in base.rows}
    for row in existing_preview.rows:
        if row.generation_status == "failed" and row.order <= PAPER_PREVIEW_ROW_LIMIT:
            rows_by_order[row.order] = row.model_dump(mode="json")

    visible_orders = sorted(rows_by_order)[:PAPER_PREVIEW_ROW_LIMIT]
    return PaperPreview(
        keywords=base.keywords,
        question_types=base.question_types,
        rows=[rows_by_order[order] for order in visible_orders],
        overflow_count=max(0, len(rows_by_order) - PAPER_PREVIEW_ROW_LIMIT),
    )


def _exam_generation_progress_for_response(
    paper: ExamPaper,
    *,
    context: dict[str, object] | None = None,
    preview: PaperPreview | None = None,
) -> ExamGenerationProgress:
    context = context if context is not None else _json_dict(getattr(paper, "selection_context_json", None))
    total = max(0, int(getattr(paper, "total_items", 0) or 0))
    if total <= 0 and preview is not None:
        total = max(0, len(preview.rows or []) + int(preview.overflow_count or 0))

    generated_questions = context.get("generated_questions")
    failed_questions = context.get("failed_questions")
    generated_count = len(generated_questions) if isinstance(generated_questions, list) else 0
    failed_count = len(failed_questions) if isinstance(failed_questions, list) else 0

    if not generated_count and isinstance(context.get("generated_question_count"), int):
        generated_count = max(0, int(context["generated_question_count"]))
    if not failed_count and isinstance(context.get("failed_question_count"), int):
        failed_count = max(0, int(context["failed_question_count"]))

    status = str(getattr(paper, "status", "") or "")
    if status in {"ready", "submitted", "grading", "graded"}:
        generated_count = max(generated_count, total)
        failed_count = 0

    completed_count = min(total, generated_count + failed_count) if total else generated_count + failed_count
    return ExamGenerationProgress(
        completed_items=completed_count,
        generated_items=max(0, min(total, generated_count) if total else generated_count),
        failed_items=max(0, min(total, failed_count) if total else failed_count),
        total_items=total,
    )


def _paper_generation_event_payload(
    paper: ExamPaper,
    *,
    preview: PaperPreview | None = None,
    stage: str | None = None,
    error_message: str | None = None,
) -> dict[str, object]:
    context = _json_dict(paper.selection_context_json)
    effective_preview = preview or _paper_preview_from_json(getattr(paper, "paper_preview_json", "{}"))
    payload: dict[str, object] = {
        "exam_paper_id": int(paper.id or 0),
        "status": _effective_exam_paper_status(paper, context=context),
        "num_questions": paper.total_items,
        "paper_preview": effective_preview.model_dump(mode="json"),
        "selection_context": context,
        "error_message": error_message if error_message is not None else context.get("error_message"),
        "updated_at": paper.updated_at,
        "generation_progress": _exam_generation_progress_for_response(
            paper,
            context=context,
            preview=effective_preview,
        ).model_dump(mode="json"),
    }
    generated_questions = context.get("generated_questions")
    if isinstance(generated_questions, list):
        payload["generated_questions"] = [
            item for item in generated_questions if isinstance(item, dict)
        ]
        payload["generated_question_count"] = len(payload["generated_questions"])
    failed_questions = context.get("failed_questions")
    if isinstance(failed_questions, list):
        payload["failed_questions"] = [
            item for item in failed_questions if isinstance(item, dict)
        ]
        payload["failed_question_count"] = len(payload["failed_questions"])
    if stage:
        payload["stage"] = stage
    return payload


def _links_for_items(session: Session, items: list[ExamPaperItem]) -> dict[int, list[dict[str, object]]]:
    return exams_repo.list_links_for_exam_items(session, [int(item.id or 0) for item in items])


def _knowledge_units_for_item_links(
    session: Session,
    links_by_item_id: dict[int, list[dict[str, object]]],
) -> dict[int, KnowledgeUnit]:
    knowledge_unit_ids = {
        knowledge_unit_id
        for refs in links_by_item_id.values()
        for ref in refs
        for knowledge_unit_id in [int(ref.get("knowledge_unit_id", 0) or 0)]
        if knowledge_unit_id > 0
    }
    return {
        unit.id: unit
        for unit in session.exec(
            select(KnowledgeUnit).where(KnowledgeUnit.id.in_(knowledge_unit_ids))
        ).all()
        if unit.id is not None
    } if knowledge_unit_ids else {}


def _is_exam_eligible_unit(unit: KnowledgeUnit) -> bool:
    name = _clean_exam_text(unit.canonical_name)
    summary = _clean_exam_text(unit.summary)
    if not name or len(name) <= 1:
        return False
    if len(name) > 80:
        return False
    if summary and len(summary) > 1000:
        return False
    return True


def _list_exam_eligible_units(
    session: Session,
    *,
    course_id: str,
) -> list[KnowledgeUnit]:
    stmt = select(KnowledgeUnit).where(
        KnowledgeUnit.course_id == course_id,
        KnowledgeUnit.status == "active",
    )
    units = list(session.exec(stmt.order_by(KnowledgeUnit.id)).all())
    return [unit for unit in units if _is_exam_eligible_unit(unit)]


def _exam_knowledge_graph_edges(
    session: Session,
    *,
    course_id: str,
    unit_ids: list[int],
) -> list[dict[str, object]]:
    allowed_ids = {int(unit_id) for unit_id in unit_ids if int(unit_id or 0) > 0}
    if not allowed_ids:
        return []
    edges: list[dict[str, object]] = []
    for edge in knowledge_relation_repo.list_all_edges_by_course(session, course_id):
        source_id = int(edge.source_node_id or 0)
        target_id = int(edge.target_node_id or 0)
        if source_id not in allowed_ids or target_id not in allowed_ids:
            continue
        description = _clean_exam_text(edge.description or "")
        if description.startswith(_SYNC_EDGE_MARKER_PREFIX):
            description = description[len(_SYNC_EDGE_MARKER_PREFIX) :].strip()
        edges.append(
            {
                "edge_id": int(edge.id or 0),
                "source_id": source_id,
                "target_id": target_id,
                "edge_type": str(edge.edge_type or "").strip(),
                "description": description[:240],
                "weight": round(float(edge.weight or 0.0), 3),
                "confidence": round(float(edge.confidence or 0.0), 3),
            }
        )
    return edges


def _exam_priority_unit_ids(
    session: Session,
    *,
    user_id: str,
    course_id: str,
    exam_mode: str,
) -> list[int]:
    priority_ids: list[int] = []
    if exam_mode in {"web_practice", "mastery_drill"}:
        due_states = profile_repo.list_due_knowledge_states(
            session,
            user_id=user_id,
            course_id=course_id,
            as_of=utcnow(),
            target_kind="knowledge_unit",
        )
        weak_states = profile_repo.list_weak_knowledge_states(
            session,
            user_id=user_id,
            course_id=course_id,
            target_kind="knowledge_unit",
        )
        for state in [*due_states, *weak_states]:
            if state.knowledge_unit_id is not None:
                priority_ids.append(int(state.knowledge_unit_id))

    if exam_mode == "paper_exam":
        weak_states = profile_repo.list_weak_knowledge_states(
            session,
            user_id=user_id,
            course_id=course_id,
            target_kind="knowledge_unit",
        )
        priority_ids.extend(
            int(state.knowledge_unit_id)
            for state in weak_states
            if state.knowledge_unit_id is not None
        )

    deduped: list[int] = []
    seen: set[int] = set()
    for unit_id in priority_ids:
        if unit_id <= 0 or unit_id in seen:
            continue
        seen.add(unit_id)
        deduped.append(unit_id)
    return deduped


def _mastery_by_unit_id(session: Session, *, user_id: str, course_id: str) -> dict[int, float]:
    return {
        int(state.knowledge_unit_id): float(state.mastery_score)
        for state in profile_repo.list_knowledge_states(
            session,
            user_id=user_id,
            course_id=course_id,
            target_kind="knowledge_unit",
        )
        if state.knowledge_unit_id is not None
    }


def _question_type_for_order(*, exam_mode: str, difficulty: str, item_order: int) -> str:
    del exam_mode, difficulty
    cycle = ["single_choice", "fill_blank"]
    return cycle[(item_order - 1) % len(cycle)]


def _normalize_paper_layout_mode(
    value: str | None,
    *,
    exam_mode: str,
    question_count: int,
) -> str:
    """Resolve the persisted paper-layout mode used by the frontend canvas."""

    if exam_mode != "paper_exam":
        return "practice_scroll"
    normalized = str(value or "auto").strip().lower().replace("-", "_")
    aliases = {
        "two_page": "standard_two_page",
        "two_pages": "standard_two_page",
        "normal_two_page": "standard_two_page",
        "standard": "standard_two_page",
        "gaokao_4": "gaokao_four_page",
        "four_page": "gaokao_four_page",
        "four_pages": "gaokao_four_page",
        "gaokao_6": "gaokao_six_page",
        "six_page": "gaokao_six_page",
        "six_pages": "gaokao_six_page",
        "gaokao_8": "gaokao_eight_page",
        "eight_page": "gaokao_eight_page",
        "eight_pages": "gaokao_eight_page",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in PAPER_LAYOUT_MODES:
        normalized = "auto"
    if normalized != "auto":
        return normalized
    if question_count >= 36:
        return "gaokao_eight_page"
    if question_count >= 28:
        return "gaokao_six_page"
    if question_count >= 12:
        return "gaokao_four_page"
    return "standard_two_page"


def _paper_layout_base(mode: str, question_count: int) -> dict[str, object]:
    if mode == "gaokao_six_page":
        base_pages = 6
        pages_per_side = 3
        display_name = "高考六页仿真"
        paper_style = "gaokao"
        items_per_page = 7
    elif mode == "gaokao_eight_page":
        base_pages = 8
        pages_per_side = 4
        display_name = "高考八页仿真"
        paper_style = "gaokao"
        items_per_page = 7
    elif mode == "gaokao_four_page":
        base_pages = 4
        pages_per_side = 2
        display_name = "高考四页仿真"
        paper_style = "gaokao"
        items_per_page = 7
    else:
        base_pages = 2
        pages_per_side = 2
        display_name = "标准两页测试"
        paper_style = "standard"
        items_per_page = 5

    estimated_pages = max(base_pages, (max(1, question_count) + items_per_page - 1) // items_per_page)
    if estimated_pages % pages_per_side != 0:
        estimated_pages += pages_per_side - (estimated_pages % pages_per_side)
    return {
        "base_pages": base_pages,
        "total_pages": estimated_pages,
        "pages_per_side": pages_per_side,
        "display_name": display_name,
        "paper_style": paper_style,
    }


def _question_layout_weight(question_type: str, difficulty: str | None = None) -> float:
    normalized_type = str(question_type or "").lower()
    normalized_difficulty = str(difficulty or "").lower()
    if normalized_type in {"single_choice", "true_false"}:
        weight = 0.8
    elif normalized_type in {"multiple_choice", "multi_choice", "fill_blank"}:
        weight = 1.0
    elif normalized_type in {"short_answer", "essay"}:
        weight = 1.75
    else:
        weight = 1.2
    if normalized_difficulty == "hard":
        weight += 0.35
    elif normalized_difficulty == "easy":
        weight -= 0.15
    return max(0.5, weight)


def _score_for_question(*, exam_mode: str, question_type: str, difficulty: str | None = None) -> float:
    if exam_mode != "paper_exam":
        return 1.0
    normalized_type = str(question_type or "").lower()
    if normalized_type in {"single_choice", "true_false"}:
        score = 5.0
    elif normalized_type in {"multiple_choice", "multi_choice"}:
        score = 6.0
    elif normalized_type == "fill_blank":
        score = 5.0
    elif normalized_type in {"short_answer", "essay"}:
        score = 12.0
    else:
        score = 8.0
    if str(difficulty or "").lower() == "hard" and normalized_type in {"short_answer", "essay"}:
        score += 2.0
    return score


def _question_type_group(question_type: str) -> tuple[str, str]:
    normalized = str(question_type or "").lower()
    if normalized in {"single_choice", "multiple_choice", "multi_choice", "true_false"}:
        return "choice", "选择题"
    if normalized == "fill_blank":
        return "blank", "填空题"
    if normalized in {"short_answer", "essay"}:
        return "answer", "解答题"
    return "mixed", "综合题"


def _section_number_label(index: int) -> str:
    labels = ["一", "二", "三", "四", "五", "六", "七", "八"]
    if 1 <= index <= len(labels):
        return labels[index - 1]
    return str(index)


def _build_paper_layout(
    *,
    exam_mode: str,
    question_count: int,
    paper_layout_mode: str | None = None,
    rows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    mode = _normalize_paper_layout_mode(
        paper_layout_mode,
        exam_mode=exam_mode,
        question_count=question_count,
    )
    count = max(1, int(question_count or len(rows or []) or 1))
    if exam_mode != "paper_exam":
        return {
            "version": PAPER_LAYOUT_CONFIG_VERSION,
            "mode": mode,
            "paper_style": "practice",
            "display_name": "专项练习",
            "total_pages": 1,
            "pages_per_side": 1,
            "sides": [{"side_number": 1, "label": "练习页", "pages": [1]}],
            "pages": [{"page_number": 1, "question_orders": list(range(1, count + 1)), "section_numbers": [1]}],
            "sections": [
                {
                    "section_number": 1,
                    "title": "练习题",
                    "question_type_group": "practice",
                    "question_orders": list(range(1, count + 1)),
                    "page_start": 1,
                    "page_end": 1,
                    "total_score": float(count),
                }
            ],
            "question_allocations": [
                {"item_order": order, "page_number": 1, "section_number": 1, "score": 1.0}
                for order in range(1, count + 1)
            ],
        }

    base = _paper_layout_base(mode, count)
    pages_per_side = int(base["pages_per_side"])
    row_by_order: dict[int, dict[str, object]] = {}
    for row in rows or []:
        order = _positive_int(row.get("item_order") or row.get("order"))
        if order > 0:
            row_by_order[order] = dict(row)

    normalized_rows: list[dict[str, object]] = []
    for order in range(1, count + 1):
        row = row_by_order.get(order, {})
        question_type = str(row.get("question_type") or row.get("type") or "text")
        difficulty = str(row.get("difficulty") or "medium")
        score = row.get("score")
        try:
            score_value = float(score)
        except (TypeError, ValueError):
            score_value = _score_for_question(
                exam_mode=exam_mode,
                question_type=question_type,
                difficulty=difficulty,
            )
        normalized_rows.append(
            {
                "item_order": order,
                "question_type": question_type,
                "difficulty": difficulty,
                "score": score_value,
                "weight": _question_layout_weight(question_type, difficulty),
            }
        )

    sections: list[dict[str, object]] = []
    question_allocations: list[dict[str, object]] = []
    active_section: dict[str, object] | None = None
    for row in normalized_rows:
        group, label = _question_type_group(str(row["question_type"]))
        if active_section is None or active_section["question_type_group"] != group:
            section_number = len(sections) + 1
            active_section = {
                "section_number": section_number,
                "title": f"{_section_number_label(section_number)}、{label}",
                "question_type_group": group,
                "question_orders": [],
                "page_start": 1,
                "page_end": 1,
                "total_score": 0.0,
            }
            sections.append(active_section)
        order = int(row["item_order"])
        active_section["question_orders"].append(order)
        active_section["page_start"] = 1
        active_section["page_end"] = 1
        active_section["total_score"] = round(float(active_section["total_score"]) + float(row["score"]), 1)
        question_allocations.append(
            {
                "item_order": order,
                "page_number": 1,
                "section_number": int(active_section["section_number"]),
                "score": float(row["score"]),
            }
        )

    section_by_order = {
        order: int(section["section_number"])
        for section in sections
        for order in list(section["question_orders"])
    }
    page_orders = [int(row["item_order"]) for row in normalized_rows]
    pages: list[dict[str, object]] = [
        {
            "page_number": 1,
            "question_orders": page_orders,
            "section_numbers": sorted({
                section_by_order[order]
                for order in page_orders
                if order in section_by_order
            }),
        }
    ]

    return {
        "version": PAPER_LAYOUT_CONFIG_VERSION,
        "mode": mode,
        "paper_style": base["paper_style"],
        "display_name": base["display_name"],
        "pagination_strategy": "content_flow",
        "total_pages": 1,
        "pages_per_side": pages_per_side,
        "sides": [{"side_number": 1, "label": "正面", "pages": [1]}],
        "pages": pages,
        "sections": sections,
        "question_allocations": question_allocations,
    }


def _build_exam_selection_context(
    *,
    source: str,
    knowledge_unit_ids: list[int],
    user_prompt: str | None,
    sample_file_ids: list[str],
    exam_mode: str = "web_practice",
    question_count: int = 1,
    paper_layout_mode: str | None = None,
    paper_layout: dict[str, object] | None = None,
    config_hash: str | None = None,
    config_snapshot: dict[str, object] | None = None,
    generation_origin: str = "user",
    generation_status: str = "generating",
    error_message: str | None = None,
) -> str:
    payload: dict[str, object] = {
        "source": source,
        "knowledge_unit_ids": knowledge_unit_ids,
        "user_prompt": user_prompt,
        "sample_file_ids": sample_file_ids,
        "generation_origin": generation_origin,
        "generation_status": generation_status,
        "paper_layout_mode": _normalize_paper_layout_mode(
            paper_layout_mode,
            exam_mode=exam_mode,
            question_count=question_count,
        ),
        "paper_layout": paper_layout
        or _build_paper_layout(
            exam_mode=exam_mode,
            question_count=question_count,
            paper_layout_mode=paper_layout_mode,
        ),
    }
    if config_hash:
        payload["config_hash"] = config_hash
    if config_snapshot:
        payload["config_snapshot"] = config_snapshot
    if error_message:
        payload["error_message"] = error_message
    return json.dumps(payload, ensure_ascii=False)


def _effective_exam_paper_status(
    paper: ExamPaper,
    *,
    context: dict[str, object] | None = None,
) -> str:
    status = str(paper.status or "")
    if status != "generating":
        return status

    effective_context = context if context is not None else _json_dict(paper.selection_context_json)
    generation_status = str(effective_context.get("generation_status") or "").strip()
    has_error_message = bool(str(effective_context.get("error_message") or "").strip())
    if generation_status == "failed" or has_error_message:
        return "failed"
    return status


def _set_exam_generation_status(
    session: Session,
    paper: ExamPaper,
    *,
    status: str,
    error_message: str | None = None,
) -> ExamPaper:
    context = _json_dict(paper.selection_context_json)
    context["generation_status"] = status
    if error_message:
        context["error_message"] = error_message
    else:
        context.pop("error_message", None)
    paper.selection_context_json = json.dumps(context, ensure_ascii=False)
    paper.status = status
    now = utcnow()
    if status == "ready" and str(getattr(paper, "visibility", "visible") or "visible") == "hidden":
        paper.prepared_at = paper.prepared_at or now
        paper.expires_at = paper.expires_at or now + timedelta(days=EXAM_PREWARM_TTL_DAYS)
    paper.updated_at = now
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def _fail_stale_visible_exam_generations(
    session: Session,
    *,
    course_id: str,
    user_id: str,
) -> int:
    stale_before = utcnow() - EXAM_GENERATION_STALE_AFTER
    stale_papers = exams_repo.list_stale_visible_generating_exam_papers(
        session,
        course_id=course_id,
        user_id=user_id,
        stale_before=stale_before,
    )
    failed_count = 0
    for paper in stale_papers:
        paper_id = int(paper.id or 0)
        if paper_id <= 0:
            continue
        failed_paper = _set_exam_generation_status(
            session,
            paper,
            status="failed",
            error_message=EXAM_GENERATION_STALE_MESSAGE,
        )
        _publish_exam_event(
            course_id,
            paper_id,
            "done",
            _paper_generation_event_payload(
                failed_paper,
                stage="failed",
                error_message=EXAM_GENERATION_STALE_MESSAGE,
            ),
        )
        failed_count += 1
    return failed_count


def _require_generated_questions_by_order(
    *,
    build_result,
    expected_orders: list[int],
) -> dict[int, dict[str, object]]:
    if build_result.failed:
        detail = str(build_result.error.detail if build_result.error is not None else "").strip()
        raise AITeachMeError(
            detail=detail or "Exam question generation failed.",
            error_code="EXAM_QUESTION_BUILD_FAILED",
            status_code=502,
        )

    state = build_result.require_value()
    build_error = str(state.get("error") or "").strip()
    if build_error:
        raise AITeachMeError(
            detail=build_error,
            error_code="EXAM_QUESTION_BUILD_FAILED",
            status_code=502,
        )

    generated_questions = state.get("generated_questions") or []
    generated_by_order: dict[int, dict[str, object]] = {}
    invalid_orders: list[object] = []
    for item in generated_questions:
        if not isinstance(item, dict):
            invalid_orders.append(item)
            continue
        try:
            item_order = int(item["item_order"])
        except (KeyError, TypeError, ValueError):
            invalid_orders.append(item.get("item_order"))
            continue
        generated_by_order[item_order] = item

    if invalid_orders:
        logger.warning(
            "exam_question_generation_invalid_item_orders_ignored",
            invalid_orders=invalid_orders,
            expected_orders=expected_orders,
        )

    missing_orders = [order for order in expected_orders if order not in generated_by_order]
    failed_questions = state.get("failed_questions") or []
    failed_orders = {
        _positive_int(item.get("item_order"))
        for item in failed_questions
        if isinstance(item, dict)
    }
    unresolved_missing_orders = [
        order for order in missing_orders if order not in failed_orders
    ]
    if unresolved_missing_orders:
        logger.warning(
            "exam_question_generation_missing_terminal_items",
            missing_orders=unresolved_missing_orders,
            expected_orders=expected_orders,
        )

    return generated_by_order


def _failed_questions_by_order(state: dict[str, object] | None) -> dict[int, dict[str, object]]:
    failed_questions = (state or {}).get("failed_questions") if isinstance(state, dict) else []
    if not isinstance(failed_questions, list):
        return {}

    by_order: dict[int, dict[str, object]] = {}
    for item in failed_questions:
        if not isinstance(item, dict):
            continue
        order = _positive_int(item.get("item_order"))
        if order > 0:
            by_order[order] = dict(item)
    return by_order


def _build_inferred_failed_question(
    *,
    order: int,
    blueprint_by_order: dict[int, dict[str, object]],
) -> dict[str, object]:
    blueprint = blueprint_by_order.get(order, {})
    knowledge_unit_ids: list[int] = []
    for raw_unit_id in list(blueprint.get("knowledge_unit_ids") or []):
        unit_id = _positive_int(raw_unit_id)
        if unit_id > 0:
            knowledge_unit_ids.append(unit_id)
    return {
        "item_order": order,
        "question_type": str(blueprint.get("question_type") or "text"),
        "difficulty": str(blueprint.get("difficulty") or "medium"),
        "knowledge_unit_ids": knowledge_unit_ids,
        "error_message": "Question generation reached the terminal workflow state without a generated item.",
        "inferred": True,
    }


def _upsert_generated_template(
    session: Session,
    *,
    course_id: str,
    unit: KnowledgeUnit | None,
    question_type: str,
    difficulty: str,
    stem: str,
    answer: str,
    explanation: str,
    options: list[str] | None,
    knowledge_unit_refs: list[dict[str, object]] | None = None,
    rationale: str = "",
) -> QuestionTemplate:
    question_type = require_supported_question_type_key(question_type)
    stem_hash = _hash_stem(stem)
    refs = (
        list(knowledge_unit_refs)
        if knowledge_unit_refs is not None
        else ([{"knowledge_unit_id": unit.id, "coverage_weight": 1.0}] if unit is not None else [])
    )
    selection_hints = {"rationale": rationale.strip()} if rationale.strip() else {}
    existing = (
        exams_repo.find_template_by_stem_hash(session, course_id, int(unit.id or 0), stem_hash)
        if unit is not None
        else None
    )
    if existing is None:
        existing = exams_repo.find_template_by_course_stem_hash(session, course_id, stem_hash)
    if existing is not None:
        existing_refs = exams_repo.find_knowledge_unit_links_by_template(session, int(existing.id or 0))
        refs_by_unit_id: dict[int, dict[str, object]] = {}
        for ref in [*existing_refs, *refs]:
            unit_id = _positive_int(ref.get("knowledge_unit_id") if isinstance(ref, dict) else None)
            if unit_id <= 0:
                continue
            try:
                weight = float(ref.get("coverage_weight", 1.0) if isinstance(ref, dict) else 1.0)
            except (TypeError, ValueError):
                weight = 1.0
            current = refs_by_unit_id.get(unit_id)
            if current is None or weight > float(current.get("coverage_weight", 0.0) or 0.0):
                refs_by_unit_id[unit_id] = {
                    "knowledge_unit_id": unit_id,
                    "coverage_weight": max(0.0, min(weight, 1.0)),
                }
        existing.question_type = question_type
        existing.difficulty = difficulty
        existing.stem = stem
        existing.answer = answer
        existing.explanation = explanation
        existing.options_json = json.dumps(options, ensure_ascii=False) if options else None
        existing_hints = _json_dict(existing.selection_hints_json)
        if selection_hints:
            existing_hints.update(selection_hints)
            existing.selection_hints_json = json.dumps(existing_hints, ensure_ascii=False)
        existing.updated_at = utcnow()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        merged_refs = sorted(
            refs_by_unit_id.values(),
            key=lambda item: float(item.get("coverage_weight", 0.0) or 0.0),
            reverse=True,
        )
        exams_repo.replace_question_template_links(session, template_id=int(existing.id or 0), refs=merged_refs)
        return existing

    template = QuestionTemplate(
        course_id=course_id,
        question_type=question_type,
        difficulty=difficulty,
        stem=stem,
        stem_hash=stem_hash,
        answer=answer,
        explanation=explanation,
        options_json=json.dumps(options, ensure_ascii=False) if options else None,
        selection_hints_json=json.dumps(selection_hints, ensure_ascii=False),
    )
    template = exams_repo.create_question_template(session, template)
    exams_repo.replace_question_template_links(session, template_id=int(template.id or 0), refs=refs)
    return template


def _create_exam_generation_paper(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    exam_mode: str,
    question_count: int,
    user_prompt: str | None,
    sample_file_ids: list[str] | None,
    unit_ids: list[int],
    config_snapshot: dict[str, object],
    config_hash: str,
    visibility: str,
    generation_origin: str,
    paper_layout_mode: str | None = None,
) -> ExamPaper:
    now = utcnow()
    initial_preview = _build_placeholder_paper_preview(question_count=question_count)
    hidden = visibility == "hidden"
    return exams_repo.create_exam_paper(
        session,
        ExamPaper(
            course_id=course_id,
            user_id=user_id,
            exam_mode=exam_mode,
            status="generating",
            visibility=visibility,
            generation_origin=generation_origin,
            config_hash=config_hash,
            config_snapshot_json=json.dumps(config_snapshot, ensure_ascii=False),
            total_items=question_count,
            total_score=float(question_count),
            paper_preview_json=initial_preview.model_dump_json(),
            selection_context_json=_build_exam_selection_context(
                source="knowledge_unit_pool",
                knowledge_unit_ids=unit_ids,
                user_prompt=user_prompt,
                sample_file_ids=_normalized_sample_file_ids(sample_file_ids),
                exam_mode=exam_mode,
                question_count=question_count,
                paper_layout_mode=paper_layout_mode,
                config_hash=config_hash,
                config_snapshot=config_snapshot,
                generation_origin=generation_origin,
            ),
            expires_at=now + timedelta(days=EXAM_PREWARM_TTL_DAYS) if hidden else None,
        ),
    )


def _reserve_exam_prewarm_paper(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    exam_mode: str,
    question_count: int,
    user_prompt: str | None,
    sample_file_ids: list[str] | None,
    unit_ids: list[int],
    config_snapshot: dict[str, object],
    config_hash: str,
    paper_layout_mode: str | None = None,
) -> tuple[ExamPaper, bool]:
    visible_candidate = _visible_active_exam_candidate(
        session,
        course_id=course_id,
        user_id=user_id,
        config_hash=config_hash,
        question_count=question_count,
    )
    if visible_candidate is not None:
        return visible_candidate, False

    candidate = exams_repo.get_prepared_exam_candidate(
        session,
        course_id=course_id,
        user_id=user_id,
        config_hash=config_hash,
        question_count=question_count,
    )
    if _is_active_prepared_exam_candidate(candidate):
        return candidate, False

    paper = _create_exam_generation_paper(
        session,
        course_id=course_id,
        user_id=user_id,
        exam_mode=exam_mode,
        question_count=question_count,
        user_prompt=user_prompt,
        sample_file_ids=sample_file_ids,
        unit_ids=unit_ids,
        config_snapshot=config_snapshot,
        config_hash=config_hash,
        paper_layout_mode=paper_layout_mode,
        visibility="hidden",
        generation_origin="prewarm",
    )
    return paper, True


def _delete_stale_hidden_exams(*, course_id: str, user_id: str) -> None:
    with managed_session() as session:
        stale_ids = exams_repo.list_stale_hidden_exam_paper_ids(
            session,
            course_id=course_id,
            user_id=user_id,
        )
        for paper_id in stale_ids:
            exams_repo.delete_exam_paper_cascade(session, paper_id=paper_id)


def _schedule_exam_prewarm_task(
    background_task_registry,
    *,
    course_id: str,
    user_id: str,
    exam_mode: str,
    unit_ids: list[int],
    question_count: int,
    user_prompt: str | None,
    sample_file_ids: list[str] | None,
    config_snapshot: dict[str, object],
    config_hash: str,
    paper_layout_mode: str | None = None,
) -> None:
    if background_task_registry is None:
        return
    background_task_registry.spawn(
        _run_exam_prewarm_background(
            course_id=course_id,
            user_id=user_id,
            exam_mode=exam_mode,
            unit_ids=unit_ids,
            question_count=question_count,
            user_prompt=user_prompt,
            sample_file_ids=sample_file_ids,
            config_snapshot=config_snapshot,
            config_hash=config_hash,
            paper_layout_mode=paper_layout_mode,
        ),
        kind="exam.prewarm",
        course_id=course_id,
        name=f"exam.prewarm:{course_id}:{config_hash[:12]}",
        dedupe_key=f"exam.prewarm:{course_id}:{config_hash}",
    )


async def _run_exam_prewarm_background(
    *,
    course_id: str,
    user_id: str,
    exam_mode: str,
    unit_ids: list[int],
    question_count: int,
    user_prompt: str | None,
    sample_file_ids: list[str] | None,
    config_snapshot: dict[str, object],
    config_hash: str,
    paper_layout_mode: str | None = None,
) -> int | None:
    _delete_stale_hidden_exams(course_id=course_id, user_id=user_id)
    with managed_session() as session:
        paper, reserved = _reserve_exam_prewarm_paper(
            session,
            course_id=course_id,
            user_id=user_id,
            exam_mode=exam_mode,
            question_count=question_count,
            user_prompt=user_prompt,
            sample_file_ids=sample_file_ids,
            unit_ids=unit_ids,
            config_snapshot=config_snapshot,
            config_hash=config_hash,
            paper_layout_mode=paper_layout_mode,
        )
        if not reserved:
            return int(paper.id or 0) or None
        paper_id = int(paper.id or 0)

    await _run_exam_generation_background(
        course_id=course_id,
        user_id=user_id,
        paper_id=paper_id,
        exam_mode=exam_mode,
        unit_ids=unit_ids,
        question_count=question_count,
        user_prompt=user_prompt,
        sample_file_ids=sample_file_ids,
        config_snapshot=config_snapshot,
        config_hash=config_hash,
        paper_layout_mode=paper_layout_mode,
        schedule_replacement=False,
        background_task_registry=None,
    )
    return paper_id


async def _run_initial_exam_from_published_docs_background(
    *,
    course_id: str,
    user_id: str,
) -> int | None:
    """Generate the one default initial quiz when KnowledgeUnits are unavailable."""

    from app.repositories.knowledge.docgen_repo import get_current_published_docs
    from app.workflows.examine.question_build.lib.generator import generate_exam_from_text

    default_config = default_auto_prewarm_exam_config()
    exam_mode = exam_mode_value(str(default_config.get("exam_mode") or DEFAULT_AUTO_PREWARM_EXAM_MODE))
    question_count = int(default_config.get("question_count") or DEFAULT_AUTO_PREWARM_QUESTION_COUNT)
    with managed_session() as session:
        course = _ensure_course(session, course_id, user_id)
        docs = get_current_published_docs(session, course_id)
        if not docs:
            return None
        existing = _find_default_auto_prewarm_candidate(
            session,
            course_id=course_id,
            user_id=user_id,
            exam_mode=exam_mode,
            question_count=question_count,
            user_prompt=None,
            sample_file_ids=[],
            paper_layout_mode=_normalize_paper_layout_mode(
                None,
                exam_mode=exam_mode,
                question_count=question_count,
            ),
        )
        if _is_active_prewarm_exam_candidate(existing):
            return int(existing.id or 0) or None
        if existing is not None and existing.status == "generating":
            exams_repo.delete_exam_paper_cascade(session, paper_id=int(existing.id or 0))

        document_ids = [int(doc.id or 0) for doc in docs if doc.id is not None]
        document_version = max((int(doc.version_no or doc.version or 0) for doc in docs), default=0)
        knowledge_text = "\n\n".join(
            part
            for doc in docs
            for part in [
                f"# {doc.title}" if str(doc.title or "").strip() else "",
                str(doc.markdown_content or doc.content_markdown or "").strip(),
            ]
            if part
        ).strip()
        if not knowledge_text:
            return None
        config_snapshot = _build_exam_config_snapshot(
            course_id=course_id,
            user_id=user_id,
            exam_mode=exam_mode,
            question_count=question_count,
            user_prompt=None,
            sample_file_ids=[],
            knowledge_unit_ids=[],
            mastery_fingerprint=_exam_mastery_fingerprint(session, course_id=course_id, user_id=user_id),
            paper_layout_mode=None,
        )
        config_snapshot.update(
            {
                "source_kind": "published_knowledge_documents",
                "knowledge_document_ids": document_ids,
                "knowledge_document_version": document_version,
            }
        )
        config_hash = _exam_config_hash(config_snapshot)
        paper = _create_exam_generation_paper(
            session,
            course_id=course_id,
            user_id=user_id,
            exam_mode=exam_mode,
            question_count=question_count,
            user_prompt=None,
            sample_file_ids=[],
            unit_ids=[],
            config_snapshot=config_snapshot,
            config_hash=config_hash,
            paper_layout_mode=None,
            visibility="visible",
            generation_origin="prewarm",
        )
        context = _json_dict(paper.selection_context_json)
        context.update(
            {
                "source": "published_knowledge_documents",
                "knowledge_document_ids": document_ids,
                "knowledge_document_version": document_version,
            }
        )
        paper.selection_context_json = json.dumps(context, ensure_ascii=False)
        paper.updated_at = utcnow()
        session.add(paper)
        session.commit()
        session.refresh(paper)
        paper_id = int(paper.id or 0)
        course_name = course.name

    _publish_exam_event(
        course_id,
        paper_id,
        "snapshot",
        {"exam_paper_id": paper_id, "status": "generating", "stage": "published_document_question_build"},
    )
    try:
        drafts = await generate_exam_from_text(
            course_name=course_name,
            knowledge_text=knowledge_text,
            num_questions=question_count,
            difficulty="medium",
        )
        drafts_by_order = {int(draft.item_order): draft for draft in drafts}
        if sorted(drafts_by_order) != list(range(1, question_count + 1)):
            raise ValueError("Published-document exam generation returned an incomplete question set.")

        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is None or paper.course_id != course_id or paper.user_id != user_id:
                return None
            items: list[ExamPaperItem] = []
            for order in range(1, question_count + 1):
                draft = drafts_by_order[order]
                template = _upsert_generated_template(
                    session,
                    course_id=course_id,
                    unit=None,
                    question_type=draft.question_type,
                    difficulty=draft.difficulty,
                    stem=draft.stem,
                    answer=draft.correct_answer,
                    explanation=draft.explanation,
                    options=list(draft.options or []) or None,
                    knowledge_unit_refs=[],
                    rationale="Generated from the current published course documents.",
                )
                items.append(
                    ExamPaperItem(
                        exam_paper_id=paper_id,
                        question_template_id=int(template.id or 0),
                        item_order=order,
                        stem_snapshot=template.stem,
                        options_snapshot_json=template.options_json,
                        answer_snapshot=template.answer,
                        explanation_snapshot=template.explanation,
                        selection_context_json=json.dumps(
                            {"source": "published_knowledge_documents"},
                            ensure_ascii=False,
                        ),
                        difficulty=template.difficulty,
                        question_type=template.question_type,
                        score=_score_for_question(
                            exam_mode=exam_mode,
                            question_type=template.question_type,
                            difficulty=template.difficulty,
                        ),
                    )
                )
            exams_repo.create_exam_paper_items(session, items)
            paper.total_items = len(items)
            paper.total_score = float(sum(float(item.score or 0.0) for item in items))
            paper.paper_preview_json = _build_final_paper_preview(
                items,
                existing_preview=_paper_preview_from_json(paper.paper_preview_json),
                knowledge_unit_by_id={},
                links_by_item_id={},
            ).model_dump_json()
            context = _json_dict(paper.selection_context_json)
            context["paper_layout_mode"] = "practice_scroll"
            context["paper_layout"] = _build_paper_layout(
                exam_mode=exam_mode,
                question_count=question_count,
                paper_layout_mode="practice_scroll",
                rows=[
                    {
                        "item_order": item.item_order,
                        "question_type": item.question_type,
                        "difficulty": item.difficulty,
                        "score": item.score,
                    }
                    for item in items
                ],
            )
            paper.selection_context_json = json.dumps(context, ensure_ascii=False)
            paper = _set_exam_generation_status(session, paper, status="ready")
            _capture_exam_generated_event(
                session,
                course_id=course_id,
                user_id=user_id,
                paper=paper,
                requested_question_count=question_count,
                sample_file_count=0,
                paper_layout_mode="practice_scroll",
            )
            done_payload = _paper_generation_event_payload(paper, stage="ready")
        _publish_exam_event(course_id, paper_id, "done", done_payload)
    except asyncio.CancelledError:
        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is not None:
                _set_exam_generation_status(
                    session,
                    paper,
                    status="failed",
                    error_message="Initial exam generation was cancelled.",
                )
        raise
    except Exception as exc:
        logger.warning(
            "initial_exam_published_document_generation_failed",
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is not None:
                paper = _set_exam_generation_status(
                    session,
                    paper,
                    status="failed",
                    error_message="Initial exam generation failed.",
                )
                _publish_exam_event(
                    course_id,
                    paper_id,
                    "done",
                    _paper_generation_event_payload(
                        paper,
                        stage="failed",
                        error_message="Initial exam generation failed.",
                    ),
                )
    return paper_id


async def _run_exam_generation_background(
    *,
    course_id: str,
    user_id: str,
    paper_id: int,
    exam_mode: str,
    unit_ids: list[int],
    question_count: int,
    user_prompt: str | None,
    sample_file_ids: list[str] | None = None,
    config_snapshot: dict[str, object] | None = None,
    config_hash: str = "",
    paper_layout_mode: str | None = None,
    schedule_replacement: bool = False,
    background_task_registry=None,
) -> None:
    snapshot_question_count = 0
    if isinstance(config_snapshot, dict):
        snapshot_question_count = _positive_int(config_snapshot.get("num_questions"))
    question_count = max(1, snapshot_question_count or int(question_count or 1))
    resolved_paper_layout_mode = _normalize_paper_layout_mode(
        paper_layout_mode
        or (str((config_snapshot or {}).get("paper_layout_mode") or "") if isinstance(config_snapshot, dict) else None),
        exam_mode=exam_mode,
        question_count=question_count,
    )
    _publish_exam_event(
        course_id,
        paper_id,
        "snapshot",
        {"exam_paper_id": paper_id, "status": "generating", "stage": "question_build"},
    )
    try:
        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is None or paper.course_id != course_id or paper.user_id != user_id:
                return
            _publish_exam_event(
                course_id,
                paper_id,
                "snapshot",
                _paper_generation_event_payload(paper, stage="question_build"),
            )
            course_row = _ensure_course(session, course_id, user_id)
            units = list(
                session.exec(
                    select(KnowledgeUnit).where(
                        KnowledgeUnit.course_id == course_id,
                        KnowledgeUnit.id.in_(unit_ids),
                    )
                ).all()
            )
            unit_by_id = {int(unit.id): unit for unit in units if unit.id is not None}
            exam_units = [unit_by_id[unit_id] for unit_id in unit_ids if unit_id in unit_by_id]
            unit_name_by_id = {
                int(unit.id): unit.canonical_name
                for unit in exam_units
                if unit.id is not None and unit.canonical_name
            }
            if not exam_units:
                raise AITeachMeError(
                    detail="No persisted KnowledgeUnits are available for exam generation.",
                    error_code="NO_PERSISTED_KNOWLEDGE_UNITS_FOR_EXAM",
                    status_code=409,
                )
            course_context = load_course_llm_context(session, course_id=course_id)

            mastery_by_unit_id = _mastery_by_unit_id(session, user_id=user_id, course_id=course_id)
            priority_unit_ids = _exam_priority_unit_ids(
                session,
                user_id=user_id,
                course_id=course_id,
                exam_mode=exam_mode,
            )
            knowledge_graph_edges = _exam_knowledge_graph_edges(
                session,
                course_id=course_id,
                unit_ids=[int(unit.id or 0) for unit in exam_units],
            )
            recent_stems: list[str] = []
            for item, _asked_at, recent_paper_id in exams_repo.list_exam_item_snapshots_by_user(
                session,
                course_id=course_id,
                user_id=user_id,
                limit=RECENT_EXAM_STEM_AVOID_LIMIT + question_count,
            ):
                if int(recent_paper_id) == paper_id:
                    continue
                stem = _clean_exam_text(item.stem_snapshot)
                if stem:
                    recent_stems.append(stem[:220])
                if len(recent_stems) >= RECENT_EXAM_STEM_AVOID_LIMIT:
                    break

        diversity_prompt = _build_exam_diversity_prompt(
            run_id=uuid.uuid4().hex,
            recent_stems=recent_stems,
        )

        async def handle_question_build_progress(payload: dict[str, object]) -> None:
            candidate_unit_ids = payload.get("candidate_unit_ids")
            if isinstance(candidate_unit_ids, list):
                candidate_ids = [
                    int(unit_id)
                    for unit_id in candidate_unit_ids
                    if isinstance(unit_id, int | str) and int(unit_id or 0) > 0
                ]
                with managed_session() as session:
                    paper = exams_repo.get_exam_paper_by_id(session, paper_id)
                    if paper is None or paper.course_id != course_id or paper.user_id != user_id:
                        return
                    context = _json_dict(paper.selection_context_json)
                    context["source"] = "knowledge_unit_candidate_pool"
                    context["knowledge_unit_ids"] = candidate_ids
                    for key in (
                        "candidate_unit_limit",
                        "input_unit_count",
                        "knowledge_graph_edge_count",
                        "candidate_unit_count",
                        "scope_include_terms",
                        "scope_exclude_terms",
                        "scope_strict",
                        "filter_strategy",
                        "filter_rationale",
                    ):
                        if key in payload:
                            context[key] = payload[key]
                    paper.selection_context_json = json.dumps(context, ensure_ascii=False)
                    paper.updated_at = utcnow()
                    session.add(paper)
                    session.commit()
                    session.refresh(paper)
                    event_payload = _paper_generation_event_payload(
                        paper,
                        stage=str(payload.get("stage") or "filter_exam_units"),
                    )
                _publish_exam_event(course_id, paper_id, "snapshot", event_payload)

            generated_question = payload.get("generated_question")
            if isinstance(generated_question, dict):
                generated_payload = dict(generated_question)
                with managed_session() as session:
                    paper = exams_repo.get_exam_paper_by_id(session, paper_id)
                    if paper is None or paper.course_id != course_id or paper.user_id != user_id:
                        return
                    context = _json_dict(paper.selection_context_json)
                    context = _merge_generated_question_into_context(
                        context,
                        generated_payload,
                        question_count=question_count,
                    )
                    preview = _merge_generated_question_into_preview(
                        _paper_preview_from_json(paper.paper_preview_json),
                        generated_payload,
                        question_count=question_count,
                        unit_name_by_id=unit_name_by_id,
                    )
                    paper.total_items = question_count
                    paper.total_score = float(question_count)
                    paper.selection_context_json = json.dumps(context, ensure_ascii=False)
                    paper.paper_preview_json = preview.model_dump_json()
                    paper.updated_at = utcnow()
                    session.add(paper)
                    session.commit()
                    session.refresh(paper)
                    event_payload = _paper_generation_event_payload(
                        paper,
                        preview=preview,
                        stage=str(payload.get("stage") or "generate_exam_questions"),
                    )
                    event_payload["generated_question"] = generated_payload
                    if "generated_question_count" in payload:
                        event_payload["generated_question_count"] = payload["generated_question_count"]
                _publish_exam_event(course_id, paper_id, "snapshot", event_payload)

            failed_question = payload.get("failed_question")
            if isinstance(failed_question, dict):
                failed_payload = dict(failed_question)
                with managed_session() as session:
                    paper = exams_repo.get_exam_paper_by_id(session, paper_id)
                    if paper is None or paper.course_id != course_id or paper.user_id != user_id:
                        return
                    context = _json_dict(paper.selection_context_json)
                    context = _merge_failed_question_into_context(
                        context,
                        failed_payload,
                        question_count=question_count,
                    )
                    preview = _merge_failed_question_into_preview(
                        _paper_preview_from_json(paper.paper_preview_json),
                        failed_payload,
                        question_count=question_count,
                    )
                    paper.selection_context_json = json.dumps(context, ensure_ascii=False)
                    paper.paper_preview_json = preview.model_dump_json()
                    paper.updated_at = utcnow()
                    session.add(paper)
                    session.commit()
                    session.refresh(paper)
                    event_payload = _paper_generation_event_payload(
                        paper,
                        preview=preview,
                        stage=str(payload.get("stage") or "generate_exam_questions"),
                    )
                    event_payload["failed_question"] = failed_payload
                    if "failed_question_count" in payload:
                        event_payload["failed_question_count"] = payload["failed_question_count"]
                _publish_exam_event(course_id, paper_id, "snapshot", event_payload)

            requirement_plans = payload.get("question_requirement_plans")
            if isinstance(requirement_plans, list):
                requirement_payload = [item for item in requirement_plans if isinstance(item, dict)]
                requirement_payload = _normalize_blueprint_item_orders(requirement_payload)
                preview = _build_question_requirement_paper_preview(
                    requirement_payload,
                    question_count=question_count,
                )
                with managed_session() as session:
                    paper = exams_repo.get_exam_paper_by_id(session, paper_id)
                    if paper is None or paper.course_id != course_id or paper.user_id != user_id:
                        return
                    context = _json_dict(paper.selection_context_json)
                    context["question_requirement_plans"] = requirement_payload
                    context["paper_layout_mode"] = resolved_paper_layout_mode
                    context["paper_layout"] = _build_paper_layout(
                        exam_mode=exam_mode,
                        question_count=question_count,
                        paper_layout_mode=resolved_paper_layout_mode,
                        rows=[
                            {
                                "item_order": item.get("item_order"),
                                "question_type": item.get("question_type"),
                                "difficulty": "medium",
                            }
                            for item in requirement_payload
                        ],
                    )
                    paper.total_items = question_count
                    paper.total_score = float(question_count)
                    paper.selection_context_json = json.dumps(context, ensure_ascii=False)
                    paper.paper_preview_json = preview.model_dump_json()
                    paper.updated_at = utcnow()
                    session.add(paper)
                    session.commit()
                    session.refresh(paper)
                    event_payload = _paper_generation_event_payload(
                        paper,
                        preview=preview,
                        stage=str(payload.get("stage") or "plan_question_requirements"),
                    )
                    event_payload["question_requirement_plans"] = requirement_payload
                _publish_exam_event(course_id, paper_id, "snapshot", event_payload)

            blueprints = payload.get("question_blueprints")
            if not isinstance(blueprints, list):
                return
            blueprint_payload = [item for item in blueprints if isinstance(item, dict)]
            blueprint_payload = _normalize_blueprint_item_orders(blueprint_payload)
            preview = _build_blueprint_paper_preview(
                blueprint_payload,
                question_count=question_count,
                unit_name_by_id=unit_name_by_id,
            )
            with managed_session() as session:
                paper = exams_repo.get_exam_paper_by_id(session, paper_id)
                if paper is None or paper.course_id != course_id or paper.user_id != user_id:
                    return
                paper.total_items = question_count
                paper.total_score = float(question_count)
                context = _json_dict(paper.selection_context_json)
                context["paper_layout_mode"] = resolved_paper_layout_mode
                context["paper_layout"] = _build_paper_layout(
                    exam_mode=exam_mode,
                    question_count=question_count,
                    paper_layout_mode=resolved_paper_layout_mode,
                    rows=[
                        {
                            "item_order": item.get("item_order"),
                            "question_type": item.get("question_type"),
                            "difficulty": item.get("difficulty"),
                        }
                        for item in blueprint_payload
                    ],
                )
                paper.paper_preview_json = preview.model_dump_json()
                paper.selection_context_json = json.dumps(context, ensure_ascii=False)
                paper.updated_at = utcnow()
                session.add(paper)
                session.commit()
                session.refresh(paper)
                event_payload = _paper_generation_event_payload(
                    paper,
                    preview=preview,
                    stage=str(payload.get("stage") or "plan_exam_questions"),
                )
            _publish_exam_event(course_id, paper_id, "snapshot", event_payload)

        build_result = await run_question_build_workflow(
            course_id=course_id,
            course_name=course_row.name,
            course_description=course_row.description,
            course_user_intent=course_row.user_intent,
            exam_mode=exam_mode,
            units=exam_units,
            knowledge_graph_edges=knowledge_graph_edges,
            question_count=question_count,
            mastery_by_unit_id=mastery_by_unit_id,
            priority_unit_ids=priority_unit_ids,
            course_context=course_context,
            user_prompt=user_prompt or "",
            system_constraints=diversity_prompt,
            progress_callback=handle_question_build_progress,
        )
        generated_by_order = _require_generated_questions_by_order(
            build_result=build_result,
            expected_orders=list(range(1, question_count + 1)),
        )
        build_state = build_result.value or {}
        question_blueprints = build_state.get("question_blueprints") if isinstance(build_state, dict) else []
        blueprint_by_order = _blueprints_by_one_based_order(question_blueprints)
        failed_by_order = _failed_questions_by_order(build_state if isinstance(build_state, dict) else {})
        inferred_missing_orders = [
            order
            for order in range(1, question_count + 1)
            if order not in generated_by_order and order not in failed_by_order
        ]
        if inferred_missing_orders:
            logger.warning(
                "exam_generation_missing_question_terminal_records",
                course_id=course_id,
                user_id=user_id,
                paper_id=paper_id,
                missing_orders=inferred_missing_orders,
            )
            for order in inferred_missing_orders:
                failed_by_order[order] = _build_inferred_failed_question(
                    order=order,
                    blueprint_by_order=blueprint_by_order,
                )
        terminal_failed_by_order = {
            order: failed
            for order, failed in failed_by_order.items()
            if order not in generated_by_order
        }

        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is None or paper.course_id != course_id or paper.user_id != user_id:
                return
            paper_context = _json_dict(paper.selection_context_json)
            final_preview = _paper_preview_from_json(paper.paper_preview_json)
            for generated_payload in [
                generated_by_order[order]
                for order in sorted(generated_by_order)
            ]:
                paper_context = _merge_generated_question_into_context(
                    paper_context,
                    generated_payload,
                    question_count=question_count,
                )
                final_preview = _merge_generated_question_into_preview(
                    final_preview,
                    generated_payload,
                    question_count=question_count,
                    unit_name_by_id=unit_name_by_id,
                )
            for failed_payload in [
                terminal_failed_by_order[order]
                for order in sorted(terminal_failed_by_order)
            ]:
                paper_context = _merge_failed_question_into_context(
                    paper_context,
                    failed_payload,
                    question_count=question_count,
                )
                final_preview = _merge_failed_question_into_preview(
                    final_preview,
                    failed_payload,
                    question_count=question_count,
                )
            paper.total_items = question_count
            paper.total_score = float(question_count)
            paper.selection_context_json = json.dumps(paper_context, ensure_ascii=False)
            paper.paper_preview_json = final_preview.model_dump_json()
            paper.updated_at = utcnow()
            session.add(paper)
            session.commit()
            session.refresh(paper)
            if generated_by_order or terminal_failed_by_order:
                _publish_exam_event(
                    course_id,
                    paper_id,
                    "snapshot",
                    _paper_generation_event_payload(
                        paper,
                        preview=final_preview,
                        stage="generate_exam_questions",
                    ),
                )
            units = list(
                session.exec(
                    select(KnowledgeUnit).where(
                        KnowledgeUnit.course_id == course_id,
                        KnowledgeUnit.id.in_(unit_ids),
                    )
                ).all()
            )
            unit_by_id = {int(unit.id): unit for unit in units if unit.id is not None}
            items: list[ExamPaperItem] = []
            refs_by_order: dict[int, list[dict[str, object]]] = {}
            for order in sorted(generated_by_order):
                generated = generated_by_order[order]
                refs = [
                    ref
                    for ref in list(generated.get("knowledge_unit_refs") or [])
                    if isinstance(ref, dict) and int(ref.get("knowledge_unit_id", 0) or 0) in unit_by_id
                ]
                primary_unit_id = int((refs[0] if refs else {}).get("knowledge_unit_id", 0) or 0)
                unit = unit_by_id.get(primary_unit_id)
                if unit is None:
                    continue
                if not refs:
                    refs = [{"knowledge_unit_id": primary_unit_id, "coverage_weight": 1.0}]
                refs_by_order[order] = refs
                blueprint = blueprint_by_order.get(order, {})
                rationale = str(blueprint.get("rationale") or "")
                blueprint_unit_ids = [
                    int(unit_id)
                    for unit_id in list(blueprint.get("knowledge_unit_ids") or [])
                    if int(unit_id or 0) > 0
                ]
                if not blueprint_unit_ids:
                    blueprint_unit_ids = [
                        int(ref.get("knowledge_unit_id", 0) or 0)
                        for ref in refs
                        if int(ref.get("knowledge_unit_id", 0) or 0) > 0
                    ]
                item_selection_context = {
                    "blueprint": {
                        "item_order": int(blueprint.get("item_order") or order),
                        "knowledge_unit_ids": blueprint_unit_ids,
                        "question_type": str(blueprint.get("question_type") or generated["question_type"]),
                        "difficulty": str(blueprint.get("difficulty") or generated["difficulty"]),
                        "rationale": rationale,
                        "generation_prompt": str(blueprint.get("generation_prompt") or ""),
                    }
                }
                template = _upsert_generated_template(
                    session,
                    course_id=course_id,
                    unit=unit,
                    difficulty=str(generated["difficulty"]),
                    question_type=str(generated["question_type"]),
                    stem=str(generated["stem"]),
                    answer=str(generated["correct_answer"]),
                    explanation=str(generated["explanation"]),
                    options=list(generated.get("options") or []) or None,
                    knowledge_unit_refs=refs,
                    rationale=rationale,
                )
                items.append(
                    ExamPaperItem(
                        exam_paper_id=paper.id or 0,
                        question_template_id=template.id or 0,
                        item_order=order,
                        stem_snapshot=template.stem,
                        options_snapshot_json=template.options_json,
                        answer_snapshot=template.answer,
                        explanation_snapshot=template.explanation,
                        selection_context_json=json.dumps(item_selection_context, ensure_ascii=False),
                        difficulty=template.difficulty,
                        question_type=template.question_type,
                        score=_score_for_question(
                            exam_mode=exam_mode,
                            question_type=template.question_type,
                            difficulty=template.difficulty,
                        ),
                    )
                )
            exams_repo.create_exam_paper_items(session, items)
            links_by_item_id: dict[int, list[dict[str, object]]] = {}
            for item in items:
                refs = refs_by_order.get(item.item_order, [])
                exams_repo.replace_exam_paper_item_links(
                    session,
                    item_id=int(item.id or 0),
                    refs=refs,
                    auto_commit=False,
                )
                links_by_item_id[int(item.id or 0)] = refs
            session.commit()
            persisted_order_set = {int(item.item_order) for item in items}
            missing_persisted_orders = [
                order for order in range(1, question_count + 1) if order not in persisted_order_set
            ]
            for order in missing_persisted_orders:
                if order in terminal_failed_by_order:
                    continue
                failed_payload = _build_inferred_failed_question(
                    order=order,
                    blueprint_by_order=blueprint_by_order,
                )
                terminal_failed_by_order[order] = failed_payload
                paper_context = _merge_failed_question_into_context(
                    paper_context,
                    failed_payload,
                    question_count=question_count,
                )
                final_preview = _merge_failed_question_into_preview(
                    final_preview,
                    failed_payload,
                    question_count=question_count,
                )

            has_terminal_failures = bool(terminal_failed_by_order)
            is_complete = not has_terminal_failures and not missing_persisted_orders and len(items) == question_count
            paper.total_items = question_count
            paper.total_score = (
                float(sum(float(item.score or 0.0) for item in items))
                if is_complete
                else float(question_count)
            )
            paper.paper_preview_json = _build_final_paper_preview(
                items,
                existing_preview=final_preview,
                knowledge_unit_by_id=unit_by_id,
                links_by_item_id=links_by_item_id,
            ).model_dump_json()
            paper_context["paper_layout_mode"] = resolved_paper_layout_mode
            paper_context["paper_layout"] = _build_paper_layout(
                exam_mode=exam_mode,
                question_count=question_count,
                paper_layout_mode=resolved_paper_layout_mode,
                rows=[
                    {
                        "item_order": item.item_order,
                        "question_type": item.question_type,
                        "difficulty": item.difficulty,
                        "score": item.score,
                    }
                    for item in items
                ],
            )
            paper_context.pop("generated_questions", None)
            if is_complete:
                paper_context.pop("generated_question_count", None)
            else:
                paper_context["generated_question_count"] = len(items)
            paper.selection_context_json = json.dumps(paper_context, ensure_ascii=False)
            final_status = "ready" if is_complete else "failed"
            final_error_message = None if is_complete else EXAM_GENERATION_INCOMPLETE_MESSAGE
            _set_exam_generation_status(session, paper, status=final_status, error_message=final_error_message)
            done_payload = _paper_generation_event_payload(
                paper,
                stage=final_status,
                preview=_paper_preview_from_json(paper.paper_preview_json),
                error_message=final_error_message,
            )
            if is_complete:
                _capture_exam_generated_event(
                    session,
                    course_id=course_id,
                    user_id=user_id,
                    paper=paper,
                    requested_question_count=question_count,
                    sample_file_count=len(sample_file_ids or []),
                    paper_layout_mode=resolved_paper_layout_mode,
                )

        for order in inferred_missing_orders:
            failed_payload = terminal_failed_by_order.get(order)
            if not failed_payload:
                continue
            snapshot_payload = dict(done_payload)
            snapshot_payload["stage"] = "generate_exam_questions"
            snapshot_payload["failed_question"] = failed_payload
            _publish_exam_event(course_id, paper_id, "snapshot", snapshot_payload)

        _publish_exam_event(
            course_id,
            paper_id,
            "done",
            done_payload,
        )
        if done_payload.get("status") == "ready" and schedule_replacement and config_snapshot and config_hash:
            _schedule_exam_prewarm_task(
                background_task_registry,
                course_id=course_id,
                user_id=user_id,
                exam_mode=exam_mode,
                unit_ids=unit_ids,
                question_count=question_count,
                user_prompt=user_prompt,
                sample_file_ids=sample_file_ids,
                config_snapshot=config_snapshot,
                config_hash=config_hash,
                paper_layout_mode=resolved_paper_layout_mode,
            )
    except asyncio.CancelledError:
        error_message = "Exam question generation was cancelled during the planning stage."
        logger.exception(
            "exam_generation_background_cancelled",
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
            exam_mode=exam_mode,
            question_count=question_count,
            error_message=error_message,
        )
        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is not None:
                paper = _set_exam_generation_status(session, paper, status="failed", error_message=error_message)
                failure_payload = _paper_generation_event_payload(
                    paper,
                    stage="failed",
                    error_message=error_message,
                )
            else:
                failure_payload = {
                    "exam_paper_id": paper_id,
                    "status": "failed",
                    "error_message": error_message,
                }
        _publish_exam_event(
            course_id,
            paper_id,
            "done",
            failure_payload,
        )
    except Exception as exc:
        error_message = str(getattr(exc, "detail", None) or exc or "Exam question generation failed.")
        logger.exception(
            "exam_generation_background_failed",
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
            exam_mode=exam_mode,
            question_count=question_count,
            error_message=error_message,
        )
        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is not None:
                paper = _set_exam_generation_status(session, paper, status="failed", error_message=error_message)
                failure_payload = _paper_generation_event_payload(
                    paper,
                    stage="failed",
                    error_message=error_message,
                )
            else:
                failure_payload = {
                    "exam_paper_id": paper_id,
                    "status": "failed",
                    "error_message": error_message,
                }
        _publish_exam_event(
            course_id,
            paper_id,
            "done",
            failure_payload,
        )


async def _spawn_exam_generation_after_response(
    request: Request,
    *,
    course_id: str,
    user_id: str,
    paper_id: int,
    exam_mode: str,
    unit_ids: list[int],
    question_count: int,
    user_prompt: str | None,
    sample_file_ids: list[str] | None,
    config_snapshot: dict[str, object],
    config_hash: str,
    schedule_replacement: bool,
    paper_layout_mode: str | None = None,
) -> None:
    request.app.state.background_task_registry.spawn(
        _run_exam_generation_background(
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
            exam_mode=exam_mode,
            unit_ids=unit_ids,
            question_count=question_count,
            user_prompt=user_prompt,
            sample_file_ids=sample_file_ids,
            config_snapshot=config_snapshot,
            config_hash=config_hash,
            paper_layout_mode=paper_layout_mode,
            schedule_replacement=schedule_replacement,
            background_task_registry=getattr(request.app.state, "background_task_registry", None),
        ),
        kind="exam.generate",
        course_id=course_id,
        name=f"exam.generate:{course_id}:{paper_id}",
        dedupe_key=f"exam.generate:{course_id}:{paper_id}",
    )


async def _spawn_exam_prewarm_after_response(
    request: Request,
    *,
    course_id: str,
    user_id: str,
    exam_mode: str,
    unit_ids: list[int],
    question_count: int,
    user_prompt: str | None,
    sample_file_ids: list[str] | None,
    config_snapshot: dict[str, object],
    config_hash: str,
    paper_layout_mode: str | None = None,
) -> None:
    _schedule_exam_prewarm_task(
        getattr(request.app.state, "background_task_registry", None),
        course_id=course_id,
        user_id=user_id,
        exam_mode=exam_mode,
        unit_ids=unit_ids,
        question_count=question_count,
        user_prompt=user_prompt,
        sample_file_ids=sample_file_ids,
        config_snapshot=config_snapshot,
        config_hash=config_hash,
        paper_layout_mode=paper_layout_mode,
    )


def _paper_item_response(
    item: ExamPaperItem,
    *,
    knowledge_unit_by_id: dict[int, KnowledgeUnit],
    mastery_by_unit_id: dict[int, float],
    knowledge_unit_refs: list[dict[str, object]],
    marked_template_ids: set[int],
) -> ExamPaperItemResponse:
    return ExamPaperItemResponse(
        id=item.id,
        item_order=item.item_order,
        question_template_id=item.question_template_id,
        question_type=item.question_type,
        difficulty=item.difficulty,
        stem=item.stem_snapshot,
        options=json.loads(item.options_snapshot_json) if item.options_snapshot_json else None,
        correct_answer=item.answer_snapshot,
        explanation=item.feedback_text or item.explanation_snapshot,
        knowledge_unit_links=[
            {
                "knowledge_unit_id": knowledge_unit_id,
                "knowledge_unit_name": (
                    knowledge_unit_by_id[knowledge_unit_id].canonical_name
                    if knowledge_unit_id in knowledge_unit_by_id
                    else ""
                ),
                "coverage_weight": float(ref.get("coverage_weight", 1.0) or 1.0),
                "mastery_score": mastery_by_unit_id.get(knowledge_unit_id),
            }
            for ref in knowledge_unit_refs
            for knowledge_unit_id in [int(ref.get("knowledge_unit_id", 0) or 0)]
            if knowledge_unit_id > 0
        ],
        selection_context=_json_dict(item.selection_context_json),
        user_answer=item.answer_content or None,
        is_correct=item.is_correct,
        score_obtained=item.score_obtained,
        score_max=item.score_max if item.score_max is not None else item.score,
        error_cause_label=item.error_cause_label,
        is_marked=int(item.question_template_id or 0) in marked_template_ids,
    )


def _generated_question_item_responses(
    context: dict[str, object],
    *,
    knowledge_unit_by_id: dict[int, KnowledgeUnit],
    mastery_by_unit_id: dict[int, float],
) -> list[ExamPaperItemResponse]:
    generated_questions = context.get("generated_questions")
    if not isinstance(generated_questions, list):
        return []

    responses: list[ExamPaperItemResponse] = []
    for raw_item in generated_questions:
        if not isinstance(raw_item, dict):
            continue
        order = _positive_int(raw_item.get("item_order"))
        stem = _clean_exam_text(str(raw_item.get("stem") or ""))
        if order <= 0 or not stem:
            continue

        options_payload = raw_item.get("options")
        options = [str(option) for option in options_payload] if isinstance(options_payload, list) else None
        knowledge_unit_links: list[dict[str, object]] = []
        refs = [
            ref
            for ref in list(raw_item.get("knowledge_unit_refs") or [])
            if isinstance(ref, dict)
        ]
        refs.sort(key=lambda item: float(item.get("coverage_weight", 0.0) or 0.0), reverse=True)
        for ref in refs:
            knowledge_unit_id = _positive_int(ref.get("knowledge_unit_id"))
            if knowledge_unit_id <= 0:
                continue
            unit = knowledge_unit_by_id.get(knowledge_unit_id)
            knowledge_unit_links.append(
                {
                    "knowledge_unit_id": knowledge_unit_id,
                    "knowledge_unit_name": unit.canonical_name if unit is not None else "",
                    "coverage_weight": float(ref.get("coverage_weight", 1.0) or 1.0),
                    "mastery_score": mastery_by_unit_id.get(knowledge_unit_id),
                }
            )

        responses.append(
            ExamPaperItemResponse(
                id=-1_000_000 - order,
                item_order=order,
                question_template_id=0,
                question_type=str(raw_item.get("question_type") or "text"),
                difficulty=str(raw_item.get("difficulty") or "medium"),
                stem=str(raw_item.get("stem") or ""),
                options=options,
                correct_answer=str(raw_item.get("correct_answer") or ""),
                explanation=str(raw_item.get("explanation") or ""),
                knowledge_unit_links=knowledge_unit_links,
                selection_context={"generation_status": "generated"},
                user_answer=None,
                is_correct=None,
                score_obtained=None,
                score_max=1.0,
                error_cause_label=None,
                is_marked=False,
            )
        )
    return sorted(responses, key=lambda item: item.item_order)


def _question_template_response(
    template: QuestionTemplate,
    *,
    knowledge_unit_refs: list[dict[str, object]],
    has_wrong_attempt: bool = False,
) -> QuestionTemplateItemResponse:
    options_payload = None
    if template.options_json:
        try:
            decoded_options = json.loads(template.options_json)
            if isinstance(decoded_options, list):
                options_payload = [str(item) for item in decoded_options]
        except json.JSONDecodeError:
            options_payload = None

    return QuestionTemplateItemResponse(
        id=template.id or 0,
        course_id=template.course_id,
        question_type=template.question_type,
        difficulty=template.difficulty,
        stem=template.stem,
        options=options_payload,
        answer=template.answer,
        explanation=template.explanation,
        knowledge_unit_refs=knowledge_unit_refs,
        selection_hints=_json_dict(template.selection_hints_json),
        template_version=template.template_version,
        status=template.status,
        is_marked=template.is_marked,
        has_wrong_attempt=has_wrong_attempt,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _question_template_answer_history_response(
    item: ExamPaperItem,
    paper: ExamPaper,
) -> QuestionTemplateAnswerHistoryItem:
    return QuestionTemplateAnswerHistoryItem(
        exam_paper_id=paper.id or 0,
        exam_paper_item_id=item.id or 0,
        item_order=item.item_order,
        exam_mode=paper.exam_mode,
        exam_status=_effective_exam_paper_status(paper),
        submitted_at=paper.submitted_at,
        graded_at=paper.graded_at,
        answered_at=item.answered_at,
        user_answer=item.answer_content,
        correct_answer=item.answer_snapshot,
        is_correct=item.is_correct,
        score_obtained=item.score_obtained,
        score_max=item.score_max,
        error_cause_label=item.error_cause_label,
        feedback_text=item.feedback_text,
        created_at=item.created_at,
    )


async def _grade_exam_paper_item_answer(
    *,
    course_id: str,
    course_name: str,
    item: ExamPaperItem,
    answer: str,
) -> QuestionTemplateGradeResponse:
    question_type = _require_supported_question_type_for_api(item.question_type)
    grading_item = ExamPaperItem(
        exam_paper_id=int(item.exam_paper_id or 0),
        question_template_id=int(item.question_template_id or 0),
        item_order=int(item.item_order or 1),
        stem_snapshot=item.stem_snapshot,
        options_snapshot_json=item.options_snapshot_json,
        answer_snapshot=item.answer_snapshot,
        explanation_snapshot=item.explanation_snapshot,
        difficulty=item.difficulty,
        question_type=question_type,
        score=float(item.score or 1.0),
        answer_content=str(answer or ""),
    )
    decisions = await run_exam_grade_workflow(
        course_id=course_id,
        course_name=course_name,
        items=[grading_item],
    )
    decision = decisions[0] if decisions else None
    if decision is None:
        raise AITeachMeError(
            detail="Question grading produced no decision.",
            error_code="QUESTION_TEMPLATE_GRADE_FAILED",
            status_code=500,
        )
    return QuestionTemplateGradeResponse(
        question_template_id=int(item.question_template_id or 0),
        question_type=question_type,
        is_correct=decision.is_correct,
        score_obtained=decision.score_obtained,
        score_max=decision.score_max,
        feedback_text=decision.feedback_text,
        error_cause_label=decision.error_cause_label,
        grading_mode=decision.grading_mode,
        correct_answer=item.answer_snapshot,
    )


async def _grade_question_template_answer(
    *,
    course_id: str,
    course_name: str,
    template: QuestionTemplate,
    answer: str,
) -> QuestionTemplateGradeResponse:
    question_type = _require_supported_question_type_for_api(template.question_type)
    item = ExamPaperItem(
        exam_paper_id=0,
        question_template_id=int(template.id or 0),
        item_order=1,
        stem_snapshot=template.stem,
        options_snapshot_json=template.options_json,
        answer_snapshot=template.answer,
        explanation_snapshot=template.explanation,
        difficulty=template.difficulty,
        question_type=question_type,
        score=1.0,
        answer_content=str(answer or ""),
    )
    return await _grade_exam_paper_item_answer(
        course_id=course_id,
        course_name=course_name,
        item=item,
        answer=answer,
    )


def _mastery_drill_attempt_response(attempt: MasteryDrillAttempt) -> MasteryDrillAttemptResponse:
    status = str(attempt.status or "failed")
    if status not in {"grading", "graded", "failed"}:
        status = "failed"
    return MasteryDrillAttemptResponse(
        id=int(attempt.id or 0),
        mastery_drill_session_id=int(attempt.mastery_drill_session_id or 0),
        exam_paper_item_id=int(attempt.exam_paper_item_id or 0),
        question_template_id=int(attempt.question_template_id or 0),
        attempt_no=max(1, int(attempt.attempt_no or 1)),
        attempt_key=attempt.attempt_key,
        status=status,
        answer=attempt.answer_content,
        is_correct=attempt.is_correct,
        score_obtained=attempt.score_obtained,
        score_max=attempt.score_max,
        feedback_text=attempt.feedback_text,
        error_cause_label=attempt.error_cause_label,
        grading_mode=str(attempt.grading_mode or "").strip() or None,
        time_spent_seconds=attempt.time_spent_seconds,
        hint_used=bool(attempt.hint_used),
        confidence_self_report=attempt.confidence_self_report,
        error_code=str(attempt.error_code or "").strip() or None,
        answered_at=attempt.answered_at,
        created_at=attempt.created_at,
        updated_at=attempt.updated_at,
    )


def _mastery_drill_session_response(
    session: Session,
    drill: MasteryDrillSession,
) -> MasteryDrillSessionResponse:
    status = str(drill.status or "active")
    if status not in {"active", "completed", "abandoned"}:
        status = "abandoned"
    attempts = exams_repo.list_mastery_drill_attempts(
        session,
        drill_session_id=int(drill.id or 0),
    )
    return MasteryDrillSessionResponse(
        id=int(drill.id or 0),
        exam_paper_id=int(drill.exam_paper_id or 0),
        status=status,
        config_snapshot=_json_dict(drill.config_snapshot_json),
        total_attempts=max(0, int(drill.total_attempts or 0)),
        wrong_attempts=max(0, int(drill.wrong_attempts or 0)),
        started_at=drill.started_at,
        completed_at=drill.completed_at,
        attempts=[_mastery_drill_attempt_response(attempt) for attempt in attempts],
    )


def _mastery_drill_history_summary(
    drill: MasteryDrillSession | None,
) -> MasteryDrillHistorySummary | None:
    if drill is None:
        return None
    status = str(drill.status or "active")
    if status not in {"active", "completed", "abandoned"}:
        status = "abandoned"
    total_attempts = max(0, int(drill.total_attempts or 0))
    wrong_attempts = min(total_attempts, max(0, int(drill.wrong_attempts or 0)))
    correct_attempts = total_attempts - wrong_attempts
    return MasteryDrillHistorySummary(
        status=status,
        total_attempts=total_attempts,
        wrong_attempts=wrong_attempts,
        attempt_accuracy=(correct_attempts / total_attempts) if total_attempts else None,
    )


def _question_type_response(item: QuestionTypeRegistry) -> QuestionTypeRegistryItemResponse:
    return QuestionTypeRegistryItemResponse(
        id=item.id or 0,
        type_key=item.type_key,
        display_name=item.display_name,
        scope=item.scope,
        course_id=item.course_id,
        description=item.description,
        answer_format=item.answer_format,
        grading_method=item.grading_method,
        option_schema=_json_dict(item.option_schema_json),
        rubric=_json_dict(item.rubric_json),
        source=item.source,
        confidence=item.confidence,
        is_system=item.is_system,
        is_active=item.is_active,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _paper_detail(session: Session, paper: ExamPaper) -> ExamPaperDetailResponse:
    items = exams_repo.list_items_by_paper(session, paper.id or 0)
    drill = exams_repo.get_mastery_drill_session_by_paper(session, paper_id=int(paper.id or 0))
    links_by_item_id = _links_for_items(session, items)
    context = _json_dict(paper.selection_context_json)
    effective_status = _effective_exam_paper_status(paper, context=context)
    knowledge_unit_by_id = _knowledge_units_for_item_links(session, links_by_item_id)
    generated_unit_ids = {
        knowledge_unit_id
        for raw_item in list(context.get("generated_questions") or [])
        if isinstance(raw_item, dict)
        for ref in list(raw_item.get("knowledge_unit_refs") or [])
        if isinstance(ref, dict)
        for knowledge_unit_id in [_positive_int(ref.get("knowledge_unit_id"))]
        if knowledge_unit_id > 0
    }
    missing_generated_unit_ids = sorted(generated_unit_ids - set(knowledge_unit_by_id))
    if missing_generated_unit_ids:
        for unit in session.exec(
            select(KnowledgeUnit).where(
                KnowledgeUnit.course_id == paper.course_id,
                KnowledgeUnit.id.in_(missing_generated_unit_ids),
            )
        ).all():
            if unit.id is not None:
                knowledge_unit_by_id[int(unit.id)] = unit
    mastery_by_unit_id = {
        int(state.knowledge_unit_id): state.mastery_score
        for state in profile_repo.list_knowledge_states(
            session,
            user_id=paper.user_id,
            course_id=paper.course_id,
            target_kind="knowledge_unit",
        )
        if state.knowledge_unit_id is not None
    }
    marked_template_ids = exams_repo.list_marked_question_template_ids(
        session,
        [int(item.question_template_id or 0) for item in items],
    )
    item_responses = [
        _paper_item_response(
            item,
            knowledge_unit_by_id=knowledge_unit_by_id,
            mastery_by_unit_id=mastery_by_unit_id,
            knowledge_unit_refs=links_by_item_id.get(int(item.id or 0), []),
            marked_template_ids=marked_template_ids,
        )
        for item in items
    ]
    if effective_status in {"generating", "failed"}:
        response_by_order = {
            item.item_order: item
            for item in _generated_question_item_responses(
                context,
                knowledge_unit_by_id=knowledge_unit_by_id,
                mastery_by_unit_id=mastery_by_unit_id,
            )
        }
        response_by_order.update({item.item_order: item for item in item_responses})
        item_responses = [
            response_by_order[order]
            for order in sorted(response_by_order)
        ]

    return ExamPaperDetailResponse(
        id=paper.id,
        course_id=paper.course_id,
        user_id=paper.user_id,
        exam_mode=paper.exam_mode,
        status=effective_status,
        total_items=paper.total_items,
        score_obtained=paper.score_obtained,
        total_score=paper.total_score,
        submitted_at=paper.submitted_at,
        graded_at=paper.graded_at,
        created_at=paper.created_at,
        selection_context=context,
        profile_sync=_exam_profile_sync_response(session, paper) if paper.status == "graded" else None,
        mastery_drill=_mastery_drill_session_response(session, drill) if drill is not None else None,
        paper_preview=_paper_preview_for_response(
            paper,
            items,
            knowledge_unit_by_id=knowledge_unit_by_id,
            links_by_item_id=links_by_item_id,
        ),
        items=item_responses,
    )


async def _study_guide_detail(session: Session, paper: ExamPaper) -> ExamStudyGuideResponse:
    cache = exams_repo.get_study_guide_cache(session, exam_paper_id=int(paper.id or 0))
    if cache is not None and cache.status == "completed" and cache.guide_json.strip():
        try:
            return ExamStudyGuideResponse.model_validate_json(cache.guide_json)
        except Exception:
            logger.warning(
                "exam_study_guide_cache_invalid",
                course_id=paper.course_id,
                user_id=paper.user_id,
                paper_id=paper.id,
            )

    items = exams_repo.list_items_by_paper(session, paper.id or 0)
    links_by_item_id = _links_for_items(session, items)
    knowledge_unit_ids = {
        knowledge_unit_id
        for refs in links_by_item_id.values()
        for ref in refs
        for knowledge_unit_id in [int(ref.get("knowledge_unit_id", 0) or 0)]
        if knowledge_unit_id > 0
    }
    knowledge_unit_by_id = {
        unit.id: unit
        for unit in session.exec(
            select(KnowledgeUnit).where(KnowledgeUnit.id.in_(knowledge_unit_ids))
        ).all()
        if unit.id is not None
    } if knowledge_unit_ids else {}

    weak_states = profile_repo.list_weak_knowledge_states(
        session,
        user_id=paper.user_id,
        course_id=paper.course_id,
        target_kind="knowledge_unit",
    )
    pending_reviews = profile_repo.list_pending_reviews(
        session,
        user_id=paper.user_id,
        course_id=paper.course_id,
    )
    wrong_question_summaries = profile_repo.list_recent_wrong_attempt_summaries(
        session,
        user_id=paper.user_id,
        course_id=paper.course_id,
        knowledge_unit_ids=[
            int(state.knowledge_unit_id)
            for state in weak_states
            if state.knowledge_unit_id is not None
        ],
        limit=5,
    )

    score_summary = (
        f"得分 {paper.score_obtained or 0:.1f}/{paper.total_score or 0:.1f}，"
        f"共 {paper.total_items} 题，"
        f"正确 {sum(1 for item in items if item.is_correct)} 题，"
        f"错误或未作答 {sum(1 for item in items if item.is_correct is not True)} 题。"
    )
    weak_point_payload = [
        {
            "knowledge_unit_id": int(state.knowledge_unit_id) if state.knowledge_unit_id is not None else None,
            "knowledge_unit_name": (
                knowledge_unit_by_id[int(state.knowledge_unit_id)].canonical_name
                if state.knowledge_unit_id is not None and int(state.knowledge_unit_id) in knowledge_unit_by_id
                else "未命名知识点"
            ),
            "mastery_score": round(float(state.mastery_score), 3),
            "reason": (
                f"掌握度 {float(state.mastery_score):.0%}，"
                f"累计 {state.total_attempts} 次练习，"
                f"正确 {state.correct_attempts} 次。"
            ),
        }
        for state in weak_states[:5]
    ]
    review_payload = [
        {
            "knowledge_unit_name": (
                knowledge_unit_by_id[int(state.knowledge_unit_id)].canonical_name
                if state.knowledge_unit_id is not None and int(state.knowledge_unit_id) in knowledge_unit_by_id
                else "未命名知识点"
            ),
            "reason": state.review_reason or "建议尽快回顾",
            "priority": round(float(state.review_priority), 3),
        }
        for state in pending_reviews[:5]
    ]

    response = await run_exam_study_guide_workflow(
        exam_paper_id=paper.id or 0,
        course_id=paper.course_id,
        course_name=_ensure_course(session, paper.course_id, paper.user_id).name,
        exam_title=_build_exam_title(paper),
        score_summary=score_summary,
        wrong_question_summaries=wrong_question_summaries,
        weak_points=weak_point_payload,
        pending_reviews=review_payload,
        generated_at=utcnow(),
    )
    if response.focus_units:
        normalized_focus_units: list[ExamStudyGuideFocusUnit] = []
        for item in response.focus_units:
            if item.knowledge_unit_name.strip():
                normalized_focus_units.append(item)
        response.focus_units = normalized_focus_units
    exams_repo.upsert_study_guide_cache(
        session,
        exam_paper_id=int(paper.id or 0),
        course_id=paper.course_id,
        user_id=paper.user_id,
        status="completed",
        guide_json=response.model_dump_json(),
        error_message="",
        generated_at=response.generated_at,
    )
    return response


async def _run_exam_study_guide_background(
    *,
    course_id: str,
    user_id: str,
    paper_id: int,
) -> None:
    try:
        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is None or paper.course_id != course_id or paper.user_id != user_id or _is_hidden_exam_paper(paper):
                return
            if paper.status != "graded":
                return
            cache = exams_repo.get_study_guide_cache(session, exam_paper_id=paper_id)
            if cache is not None and cache.status == "completed" and cache.guide_json.strip():
                return
            await _study_guide_detail(session, paper)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception(
            "exam_study_guide_background_failed",
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
            error=str(exc),
        )
        with managed_session() as session:
            exams_repo.upsert_study_guide_cache(
                session,
                exam_paper_id=paper_id,
                course_id=course_id,
                user_id=user_id,
                status="failed",
                guide_json="{}",
                error_message=str(exc),
                generated_at=None,
            )


async def _spawn_exam_study_guide_after_response(
    request: Request,
    *,
    course_id: str,
    user_id: str,
    paper_id: int,
) -> None:
    _schedule_exam_study_guide_task(
        getattr(request.app.state, "background_task_registry", None),
        course_id=course_id,
        user_id=user_id,
        paper_id=paper_id,
    )


def _schedule_exam_study_guide_task(
    background_task_registry,
    *,
    course_id: str,
    user_id: str,
    paper_id: int,
) -> bool:
    if background_task_registry is None:
        return False
    background_task_registry.spawn(
        _run_exam_study_guide_background(
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
        ),
        kind="exam.study_guide",
        course_id=course_id,
        name=f"exam.study_guide:{course_id}:{paper_id}",
        dedupe_key=f"exam.study_guide:{course_id}:{paper_id}",
    )
    return True


async def _grade_exam(
    session: Session,
    paper: ExamPaper,
    *,
    claim_token: str | None = None,
) -> ExamGradeResponse:
    paper_id = int(paper.id or 0)
    active_claim_token = str(claim_token or "").strip()
    if not active_claim_token:
        active_claim_token = uuid.uuid4().hex
        claimed_at = utcnow()
        claimed = exams_repo.claim_exam_grading(
            session,
            paper_id=paper_id,
            claim_token=active_claim_token,
        claimed_at=claimed_at,
        lease_expires_at=claimed_at + EXAM_GRADING_LEASE_DURATION,
        max_attempts=EXAM_GRADING_MAX_ATTEMPTS,
        )
        session.expire_all()
        paper = exams_repo.get_exam_paper_by_id(session, paper_id) or paper
        if not claimed:
            return _exam_grade_response_from_paper(session, paper)

    items = exams_repo.list_items_by_paper(session, paper.id or 0)
    _require_supported_exam_items(items)
    course_name = _ensure_course(session, paper.course_id, paper.user_id).name
    session.commit()
    decisions = await run_exam_grade_workflow(course_id=paper.course_id, course_name=course_name, items=items)
    total_score = 0.0
    score_obtained = 0.0
    now = utcnow()
    for item, decision in zip(items, decisions, strict=False):
        total_score += item.score
        score_obtained += decision.score_obtained or 0.0

    finalized = exams_repo.finalize_exam_grading_claim(
        session,
        paper_id=paper_id,
        claim_token=active_claim_token,
        total_score=total_score,
        score_obtained=score_obtained,
        graded_at=now,
    )
    if not finalized:
        session.rollback()
        session.expire_all()
        current = exams_repo.get_exam_paper_by_id(session, paper_id) or paper
        return _exam_grade_response_from_paper(session, current)

    for item, decision in zip(items, decisions, strict=False):
        item.is_correct = decision.is_correct
        item.score_max = decision.score_max
        item.score_obtained = decision.score_obtained
        item.error_cause_label = decision.error_cause_label
        item.feedback_text = decision.feedback_text
        item.graded_at = now
        item.updated_at = now
        session.add(item)
    exams_repo.ensure_exam_profile_sync(
        session,
        paper=paper,
        status="pending",
        trigger="exam_graded",
        next_attempt_at=now,
        auto_commit=False,
    )
    session.commit()
    session.expire_all()
    paper = exams_repo.get_exam_paper_by_id(session, paper_id) or paper
    session.refresh(paper)
    return _exam_grade_response_from_paper(session, paper)


async def _renew_exam_grading_lease_loop(*, paper_id: int, claim_token: str) -> None:
    while True:
        await asyncio.sleep(EXAM_GRADING_HEARTBEAT_SECONDS)
        try:
            with managed_session() as session:
                renewed = exams_repo.renew_exam_grading_lease(
                    session,
                    paper_id=paper_id,
                    claim_token=claim_token,
                    lease_expires_at=utcnow() + EXAM_GRADING_LEASE_DURATION,
                )
        except Exception as exc:
            logger.warning(
                "exam_grading_lease_renewal_failed",
                paper_id=paper_id,
                error_type=type(exc).__name__,
            )
            continue
        if not renewed:
            return


async def _renew_mastery_drill_attempt_lease_loop(*, attempt_id: int, claim_token: str) -> None:
    while True:
        await asyncio.sleep(MASTERY_DRILL_ATTEMPT_HEARTBEAT_SECONDS)
        try:
            with managed_session() as session:
                renewed = exams_repo.renew_mastery_drill_attempt_lease(
                    session,
                    attempt_id=attempt_id,
                    claim_token=claim_token,
                    lease_expires_at=utcnow() + MASTERY_DRILL_ATTEMPT_LEASE_DURATION,
                )
        except Exception as exc:
            logger.warning(
                "mastery_drill_attempt_lease_renewal_failed",
                attempt_id=attempt_id,
                error_type=type(exc).__name__,
            )
            continue
        if not renewed:
            return


async def _run_exam_grading_background(
    *,
    course_id: str,
    user_id: str,
    paper_id: int,
    background_task_registry=None,
) -> None:
    claim_token = uuid.uuid4().hex
    claimed_at = utcnow()
    with managed_session() as session:
        paper = exams_repo.get_exam_paper_by_id(session, paper_id)
        if paper is None or paper.course_id != course_id or paper.user_id != user_id or _is_hidden_exam_paper(paper):
            return
        claimed = exams_repo.claim_exam_grading(
            session,
            paper_id=paper_id,
            claim_token=claim_token,
            claimed_at=claimed_at,
            lease_expires_at=claimed_at + EXAM_GRADING_LEASE_DURATION,
        )
    if not claimed:
        return

    heartbeat = asyncio.create_task(
        _renew_exam_grading_lease_loop(paper_id=paper_id, claim_token=claim_token),
        name=f"exam.grading.heartbeat:{paper_id}",
    )
    try:
        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is None:
                return
            grade_response = await _grade_exam(session, paper, claim_token=claim_token)
            session.expire_all()
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if paper is None or paper.status != "graded":
                return
            analytics_user = _analytics_user_context_from_db(session, user_id)
            _capture_exam_event(
                "exam_graded",
                course_id=course_id,
                user=analytics_user,
                paper=paper,
                insert_id_parts=["graded", str(paper.graded_at.isoformat() if paper.graded_at else utcnow().isoformat())],
                properties={
                    "states_updated": grade_response.states_updated,
                    "tasks_created": grade_response.tasks_created,
                    "mastery_consumed": grade_response.mastery_consumed,
                },
            )
        _publish_exam_event(course_id, paper_id, "done", {"exam_paper_id": paper_id, "status": "graded"})
        profile_sync_scheduled = schedule_exam_profile_sync_task(
            background_task_registry,
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
        )
        if not profile_sync_scheduled:
            await run_exam_profile_sync_background(
                course_id=course_id,
                user_id=user_id,
                paper_id=paper_id,
            )
        _schedule_exam_study_guide_task(
            background_task_registry,
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
        )
    except asyncio.CancelledError:
        with managed_session() as session:
            exams_repo.release_exam_grading_claim(
                session,
                paper_id=paper_id,
                claim_token=claim_token,
                error_message="grading_worker_cancelled",
                terminal_when_exhausted=False,
                max_attempts=EXAM_GRADING_MAX_ATTEMPTS,
            )
        raise
    except Exception as exc:
        logger.exception(
            "exam_grading_background_failed",
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
            error=str(exc),
        )
        terminal_failure = False
        with managed_session() as session:
            released = exams_repo.release_exam_grading_claim(
                session,
                paper_id=paper_id,
                claim_token=claim_token,
                error_message=f"{type(exc).__name__}: grading_failed",
                max_attempts=EXAM_GRADING_MAX_ATTEMPTS,
            )
            if released:
                session.expire_all()
                failed_paper = exams_repo.get_exam_paper_by_id(session, paper_id)
                terminal_failure = failed_paper is not None and failed_paper.status == "grading_failed"
        if terminal_failure:
            _publish_exam_event(
                course_id,
                paper_id,
                "failed",
                {
                    "exam_paper_id": paper_id,
                    "status": "grading_failed",
                    "error_message": "判卷多次失败，请手动重新批改。",
                },
            )
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning(
                "exam_grading_heartbeat_cleanup_failed",
                paper_id=paper_id,
                error_type=type(exc).__name__,
            )


def _schedule_exam_grading_task(
    background_task_registry,
    *,
    course_id: str,
    user_id: str,
    paper_id: int,
) -> bool:
    if background_task_registry is None:
        return False
    background_task_registry.spawn(
        _run_exam_grading_background(
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
            background_task_registry=background_task_registry,
        ),
        kind="exam.grading",
        course_id=course_id,
        name=f"exam.grading:{course_id}:{paper_id}",
        dedupe_key=f"exam.grading:{paper_id}",
    )
    return True


def _recover_exam_grading_tasks_once(background_task_registry) -> int:
    now = utcnow()
    with managed_session() as session:
        papers = exams_repo.list_recoverable_exam_grading_papers(session, as_of=now)
        exhausted_papers = [
            (str(paper.course_id), int(paper.id or 0))
            for paper in papers
            if paper.id is not None and int(paper.grading_attempts or 0) >= EXAM_GRADING_MAX_ATTEMPTS
        ]
        exhausted_paper_ids = {paper_id for _, paper_id in exhausted_papers}
        for exhausted_course_id, paper_id in exhausted_papers:
            if exams_repo.fail_exhausted_exam_grading(
                session,
                paper_id=paper_id,
                as_of=now,
                max_attempts=EXAM_GRADING_MAX_ATTEMPTS,
            ):
                _publish_exam_event(
                    exhausted_course_id,
                    paper_id,
                    "failed",
                    {
                        "exam_paper_id": paper_id,
                        "status": "grading_failed",
                        "error_message": "判卷重试次数已用尽，请手动重新批改。",
                    },
                )
        recoverable = [
            (str(paper.course_id), str(paper.user_id), int(paper.id or 0))
            for paper in papers
            if paper.id is not None
            and int(paper.id or 0) not in exhausted_paper_ids
            and _is_exam_grading_recoverable_now(paper, as_of=now)
        ]
    return sum(
        1
        for course_id, user_id, paper_id in recoverable
        if _schedule_exam_grading_task(
            background_task_registry,
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
        )
    )


async def run_exam_grading_recovery_loop(*, task_registry) -> None:
    while True:
        try:
            _recover_exam_grading_tasks_once(task_registry)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("exam_grading_recovery_scan_failed", error=str(exc))
        await asyncio.sleep(EXAM_GRADING_RECOVERY_INTERVAL_SECONDS)


@router.get(
    "/mastery-drills/active",
    response_model=ApiResponse[ExamPaperDetailResponse | None],
    summary="Fetch the active mastery drill for this course",
    responses=build_error_responses([400, 404, 500]),
)
async def active_mastery_drill(
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDetailResponse | None]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    active = exams_repo.get_active_mastery_drill_session(
        session,
        course_id=normalized,
        user_id=user.user_id,
    )
    if active is None:
        return ok_response(None)
    paper = exams_repo.get_exam_paper_by_id(session, int(active.exam_paper_id or 0))
    if paper is None or _is_hidden_exam_paper(paper):
        return ok_response(None)
    return ok_response(_paper_detail(session, paper))


@router.post(
    "/generate",
    response_model=ApiResponse[ExamGenerateResponse],
    summary="Generate an exam from KnowledgeUnits",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def generate_exam(
    request: Request,
    background_tasks: BackgroundTasks,
    course_id: str = Path(...),
    body: ExamGenerateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGenerateResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    mode = _require_generic_exam_mode(exam_mode_value(body.exam_mode))
    default_question_count = _default_exam_question_count_for_mode(mode)
    question_count = max(1, int(body.num_questions or default_question_count))
    paper_layout_mode = _normalize_paper_layout_mode(
        body.paper_layout_mode,
        exam_mode=mode,
        question_count=question_count,
    )
    units = _list_exam_eligible_units(
        session,
        course_id=normalized,
    )
    if not units:
        raise AITeachMeError(
            detail="No active KnowledgeUnits are available for exam generation.",
            error_code="NO_KNOWLEDGE_UNITS_FOR_EXAM",
            status_code=409,
        )
    exam_units = [unit for unit in units if unit.id is not None]
    if not exam_units:
        raise AITeachMeError(
            detail="No persisted KnowledgeUnits are available for exam generation.",
            error_code="NO_PERSISTED_KNOWLEDGE_UNITS_FOR_EXAM",
            status_code=409,
        )

    unit_ids = [int(unit.id or 0) for unit in exam_units]
    config_snapshot = _build_exam_config_snapshot(
        course_id=normalized,
        user_id=user.user_id,
        exam_mode=mode,
        question_count=question_count,
        user_prompt=body.user_prompt,
        sample_file_ids=body.sample_file_ids,
        knowledge_unit_ids=unit_ids,
        mastery_fingerprint=_exam_mastery_fingerprint(session, course_id=normalized, user_id=user.user_id),
        paper_layout_mode=paper_layout_mode,
    )
    config_hash = _exam_config_hash(config_snapshot)
    paper = _visible_active_exam_candidate(
        session,
        course_id=normalized,
        user_id=user.user_id,
        config_hash=config_hash,
        question_count=question_count,
    )
    if paper is None:
        paper = exams_repo.claim_prepared_exam_paper(
            session,
            course_id=normalized,
            user_id=user.user_id,
            config_hash=config_hash,
            question_count=question_count,
        )
    if paper is None:
        paper = _claim_default_auto_prewarm_candidate(
            session,
            course_id=normalized,
            user_id=user.user_id,
            exam_mode=mode,
            question_count=question_count,
            user_prompt=body.user_prompt,
            sample_file_ids=body.sample_file_ids,
            paper_layout_mode=paper_layout_mode,
        )
    if paper is not None:
        paper = _mark_prewarm_paper_claimed(session, paper)
        paper_id = int(paper.id or 0)

        _capture_exam_event(
            "exam_generation_requested",
            course_id=normalized,
            user=user,
            paper=paper,
            insert_id_parts=["prepared", str(paper.updated_at.isoformat())],
            properties={
                "served_from_prepared": True,
                "requested_question_count": question_count,
                "sample_file_count": len(body.sample_file_ids or []),
                "paper_layout_mode": paper_layout_mode,
            },
        )
        _capture_exam_generated_event(
            session,
            course_id=normalized,
            user_id=user.user_id,
            paper=paper,
            requested_question_count=question_count,
            sample_file_count=len(body.sample_file_ids or []),
            paper_layout_mode=paper_layout_mode,
        )
        return ok_response(
            ExamGenerateResponse(
                id=paper_id,
                status=paper.status,
                error_message=None,
                created_at=paper.created_at,
                updated_at=paper.updated_at,
                course_id=paper.course_id,
                user_id=paper.user_id,
                exam_mode=paper.exam_mode,
                num_questions=paper.total_items or question_count,
                exam_paper_id=paper_id,
                sample_file_ids=body.sample_file_ids or [],
                served_from_prepared=True,
            )
        )

    paper = _create_exam_generation_paper(
        session,
        course_id=normalized,
        user_id=user.user_id,
        exam_mode=mode,
        question_count=question_count,
        user_prompt=body.user_prompt,
        sample_file_ids=body.sample_file_ids,
        unit_ids=unit_ids,
        config_snapshot=config_snapshot,
        config_hash=config_hash,
        paper_layout_mode=paper_layout_mode,
        visibility="visible",
        generation_origin="user",
    )
    paper_id = paper.id or 0
    background_tasks.add_task(
        _spawn_exam_generation_after_response,
        request,
        course_id=normalized,
        user_id=user.user_id,
        paper_id=paper_id,
        exam_mode=mode,
        unit_ids=unit_ids,
        question_count=question_count,
        user_prompt=body.user_prompt,
        sample_file_ids=body.sample_file_ids or [],
        config_snapshot=config_snapshot,
        config_hash=config_hash,
        paper_layout_mode=paper_layout_mode,
        schedule_replacement=False,
    )
    _capture_exam_event(
        "exam_generation_requested",
        course_id=normalized,
        user=user,
        paper=paper,
        insert_id_parts=["new", str(paper.created_at.isoformat())],
        properties={
            "served_from_prepared": False,
            "requested_question_count": question_count,
            "sample_file_count": len(body.sample_file_ids or []),
            "paper_layout_mode": paper_layout_mode,
        },
    )
    return ok_response(
        ExamGenerateResponse(
            id=paper_id,
            status=paper.status,
            error_message=None,
            created_at=paper.created_at,
            updated_at=paper.updated_at,
            course_id=paper.course_id,
            user_id=paper.user_id,
            exam_mode=paper.exam_mode,
            num_questions=question_count,
            exam_paper_id=paper_id,
            sample_file_ids=body.sample_file_ids or [],
            served_from_prepared=False,
        )
    )


def _prewarm_status_from_candidate(paper: ExamPaper | None) -> str:
    if paper is None:
        return "missing"
    unclaimed_prewarm = _is_unclaimed_prewarm_paper(paper)
    now = utcnow()
    expires_at = ensure_utc_datetime(paper.expires_at)
    if expires_at is not None and expires_at <= now:
        if unclaimed_prewarm:
            return "missing"
        return "stale"
    if paper.status == "ready":
        return "ready"
    if paper.status == "generating":
        return "preparing"
    if paper.status == "failed":
        if unclaimed_prewarm:
            return "missing"
        return "failed"
    return "missing"


def _is_unclaimed_prewarm_paper(paper: ExamPaper | None) -> bool:
    if paper is None:
        return False
    return str(getattr(paper, "generation_origin", "") or "") == "prewarm" and paper.claimed_at is None


def _mark_prewarm_paper_claimed(session: Session, paper: ExamPaper) -> ExamPaper:
    if not _is_unclaimed_prewarm_paper(paper):
        return paper
    now = utcnow()
    paper.visibility = "visible"
    paper.claimed_at = now
    paper.expires_at = None
    paper.updated_at = now
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


@router.get(
    "/prewarm-status",
    response_model=ApiResponse[ExamPrewarmStatusResponse],
    summary="Get background-prepared exam status for the current generation options",
    responses=build_error_responses([400, 404, 500]),
)
async def exam_prewarm_status(
    request: Request,
    background_tasks: BackgroundTasks,
    course_id: str = Path(...),
    exam_mode: str = Query("web_practice"),
    num_questions: int = Query(DEFAULT_AUTO_PREWARM_QUESTION_COUNT, ge=1, le=200),
    user_prompt: str | None = Query(default=None),
    sample_file_ids: list[str] | None = Query(default=None),
    paper_layout_mode: str | None = Query(default=None),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPrewarmStatusResponse]:
    del request, background_tasks
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    mode = exam_mode_value(exam_mode)
    question_count = max(1, int(num_questions or DEFAULT_AUTO_PREWARM_QUESTION_COUNT))
    resolved_paper_layout_mode = _normalize_paper_layout_mode(
        paper_layout_mode,
        exam_mode=mode,
        question_count=question_count,
    )
    units = _list_exam_eligible_units(session, course_id=normalized)
    unit_ids = [int(unit.id or 0) for unit in units if unit.id is not None]
    if not unit_ids:
        return ok_response(
            ExamPrewarmStatusResponse(
                status="missing",
                exam_mode=mode,
                num_questions=question_count,
                error_message="No active KnowledgeUnits are available for exam generation.",
            )
        )

    config_snapshot = _build_exam_config_snapshot(
        course_id=normalized,
        user_id=user.user_id,
        exam_mode=mode,
        question_count=question_count,
        user_prompt=user_prompt,
        sample_file_ids=sample_file_ids or [],
        knowledge_unit_ids=unit_ids,
        mastery_fingerprint=_exam_mastery_fingerprint(session, course_id=normalized, user_id=user.user_id),
        paper_layout_mode=resolved_paper_layout_mode,
    )
    config_hash = _exam_config_hash(config_snapshot)
    candidate = _visible_active_exam_candidate(
        session,
        course_id=normalized,
        user_id=user.user_id,
        config_hash=config_hash,
        question_count=question_count,
    )
    if candidate is None:
        candidate = exams_repo.get_prepared_exam_candidate(
            session,
            course_id=normalized,
            user_id=user.user_id,
            config_hash=config_hash,
            question_count=question_count,
        )
    if candidate is None:
        candidate = _find_default_auto_prewarm_candidate(
            session,
            course_id=normalized,
            user_id=user.user_id,
            exam_mode=mode,
            question_count=question_count,
            user_prompt=user_prompt,
            sample_file_ids=sample_file_ids or [],
            paper_layout_mode=resolved_paper_layout_mode,
        )
    status = _prewarm_status_from_candidate(candidate)

    return ok_response(
        ExamPrewarmStatusResponse(
            status=status,
            exam_mode=mode,
            num_questions=question_count,
            prepared_at=candidate.prepared_at if candidate is not None else None,
            expires_at=candidate.expires_at if candidate is not None else None,
            updated_at=candidate.updated_at if candidate is not None else None,
            background_requested=False,
            error_message=str(_json_dict(candidate.selection_context_json).get("error_message") or "")
            if candidate is not None and status == "failed"
            else None,
        )
    )


@router.get(
    "/history",
    response_model=ApiResponse[PaginatedData[ExamHistoryItem]],
    summary="List exam history",
    responses=build_error_responses([400, 404, 500]),
)
async def exam_history(
    request: Request,
    background_tasks: BackgroundTasks,
    course_id: str = Path(...),
    page: int = 1,
    size: int = 20,
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ExamHistoryItem]]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    _fail_stale_visible_exam_generations(
        session,
        course_id=normalized,
        user_id=user.user_id,
    )

    rows, total = exams_repo.list_exam_papers(
        session,
        course_id=normalized,
        user_id=user.user_id,
        limit=size,
        offset=PageParams(page=page, size=size).offset,
    )
    paper_ids = [int(paper.id or 0) for paper in rows if paper.id is not None]
    items_by_paper_id = exams_repo.list_items_by_papers(session, paper_ids)
    mastery_drill_by_paper_id = exams_repo.list_mastery_drill_sessions_by_papers(session, paper_ids)
    all_items = [item for items in items_by_paper_id.values() for item in items]
    links_by_item_id = _links_for_items(session, all_items)
    knowledge_unit_by_id = _knowledge_units_for_item_links(session, links_by_item_id)
    return ok_response(
        build_paginated_data(
            items=[
                ExamHistoryItem(
                    id=paper.id,
                    course_id=paper.course_id,
                    user_id=paper.user_id,
                    exam_mode=paper.exam_mode,
                    status=_effective_exam_paper_status(paper),
                    total_items=paper.total_items,
                    score_obtained=paper.score_obtained,
                    total_score=paper.total_score,
                    created_at=paper.created_at,
                    updated_at=paper.updated_at,
                    submitted_at=paper.submitted_at,
                    graded_at=paper.graded_at,
                    generation_progress=_exam_generation_progress_for_response(paper),
                    paper_preview=_paper_preview_for_response(
                        paper,
                        items_by_paper_id.get(int(paper.id or 0), []),
                        knowledge_unit_by_id=knowledge_unit_by_id,
                        links_by_item_id=links_by_item_id,
                    ),
                    mastery_drill=_mastery_drill_history_summary(
                        mastery_drill_by_paper_id.get(int(paper.id or 0))
                    ),
                )
                for paper in rows
            ],
            page=page,
            size=size,
            total=total,
        )
    )


@router.get(
    "/question-templates",
    response_model=ApiResponse[list[QuestionTemplateItemResponse]],
    summary="List question templates for the course",
    responses=build_error_responses([400, 404, 500]),
)
async def question_templates(
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[QuestionTemplateItemResponse]]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    rows = list(
        session.exec(
            select(QuestionTemplate)
            .where(QuestionTemplate.course_id == normalized)
            .order_by(QuestionTemplate.created_at.desc(), QuestionTemplate.id.desc())
        ).all()
    )
    template_ids = [int(item.id or 0) for item in rows]
    links_by_template_id = exams_repo.list_links_for_templates(session, template_ids)
    wrong_template_ids = exams_repo.list_wrong_question_template_ids(
        session,
        course_id=normalized,
        user_id=user.user_id,
        template_ids=template_ids,
    )
    return ok_response([
        _question_template_response(
            item,
            knowledge_unit_refs=links_by_template_id.get(int(item.id or 0), []),
            has_wrong_attempt=int(item.id or 0) in wrong_template_ids,
        )
        for item in rows
    ])


@router.get(
    "/question-templates/{question_template_id}/answer-history",
    response_model=ApiResponse[list[QuestionTemplateAnswerHistoryItem]],
    summary="List answer history for a question template",
    responses=build_error_responses([400, 404, 500]),
)
async def question_template_answer_history(
    course_id: str = Path(...),
    question_template_id: int = Path(..., ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[QuestionTemplateAnswerHistoryItem]]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    template = session.get(QuestionTemplate, question_template_id)
    if template is None or template.course_id != normalized:
        _raise_not_found(
            f"Question template `{question_template_id}` not found.",
            error_code="QUESTION_TEMPLATE_NOT_FOUND",
        )
    rows = exams_repo.list_question_template_answer_history(
        session,
        course_id=normalized,
        user_id=user.user_id,
        template_id=question_template_id,
        limit=limit,
    )
    return ok_response([
        _question_template_answer_history_response(item, paper)
        for item, paper in rows
    ])


@router.post(
    "/question-templates/{question_template_id}/grade",
    response_model=ApiResponse[QuestionTemplateGradeResponse],
    summary="Grade one answer against a question template",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def grade_question_template_answer(
    course_id: str = Path(...),
    question_template_id: int = Path(...),
    body: QuestionTemplateGradeRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[QuestionTemplateGradeResponse]:
    normalized = normalize_course_id(course_id)
    course = _ensure_course(session, normalized, user.user_id)
    template = session.get(QuestionTemplate, question_template_id)
    if template is None or template.course_id != normalized:
        _raise_not_found(
            f"Question template `{question_template_id}` not found.",
            error_code="QUESTION_TEMPLATE_NOT_FOUND",
        )
    assert template is not None
    data = await _grade_question_template_answer(
        course_id=normalized,
        course_name=course.name,
        template=template,
        answer=body.answer,
    )
    _capture_exam_event(
        "question_template_answer_graded",
        course_id=normalized,
        user=user,
        insert_id_parts=[str(question_template_id), str(data.grading_mode), str(utcnow().isoformat())],
        properties={
            "question_template_id_present": True,
            "question_template_id_suffix": _suffix(question_template_id),
            "question_type": data.question_type,
            "difficulty": template.difficulty,
            "is_correct": data.is_correct,
            "score_obtained": data.score_obtained,
            "score_max": data.score_max,
            "grading_mode": data.grading_mode,
            "error_cause_label": data.error_cause_label,
        },
    )
    return ok_response(data)


@router.patch(
    "/question-templates/{question_template_id}/mark",
    response_model=ApiResponse[QuestionTemplateMarkResponse],
    summary="Mark or unmark a question template",
    responses=build_error_responses([400, 404, 500]),
)
async def mark_question_template(
    course_id: str = Path(...),
    question_template_id: int = Path(..., ge=1),
    body: QuestionTemplateMarkRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[QuestionTemplateMarkResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    template = exams_repo.set_question_template_mark(
        session,
        course_id=normalized,
        template_id=question_template_id,
        is_marked=body.is_marked,
    )
    if template is None:
        _raise_not_found(
            f"Question template `{question_template_id}` not found.",
            error_code="QUESTION_TEMPLATE_NOT_FOUND",
        )
    assert template is not None
    return ok_response(
        QuestionTemplateMarkResponse(
            question_template_id=question_template_id,
            is_marked=bool(template.is_marked),
        )
    )


@router.get(
    "/question-types",
    response_model=ApiResponse[list[QuestionTypeRegistryItemResponse]],
    summary="List global and course question types",
    responses=build_error_responses([400, 404, 500]),
)
async def question_types(
    course_id: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[QuestionTypeRegistryItemResponse]]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    rows = list(
        session.exec(
            select(QuestionTypeRegistry)
            .where(
                QuestionTypeRegistry.is_active == True,  # noqa: E712
                or_(
                    QuestionTypeRegistry.scope == "global",
                    QuestionTypeRegistry.course_id == normalized,
                ),
            )
            .order_by(
                QuestionTypeRegistry.scope.asc(),
                QuestionTypeRegistry.course_id.asc(),
                QuestionTypeRegistry.type_key.asc(),
            )
        ).all()
    )
    return ok_response([_question_type_response(item) for item in rows if is_supported_question_type(item.type_key)])


@router.post(
    "/mastery-drills/start",
    response_model=ApiResponse[ExamPaperDetailResponse],
    summary="Start or resume a durable mastery drill",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def start_mastery_drill(
    course_id: str = Path(...),
    body: MasteryDrillStartRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDetailResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)

    active = exams_repo.get_open_mastery_drill_session(
        session,
        course_id=normalized,
        user_id=user.user_id,
    )
    if active is not None:
        active_paper = exams_repo.get_exam_paper_by_id(session, int(active.exam_paper_id or 0))
        if (
            active_paper is not None
            and not _is_hidden_exam_paper(active_paper)
            and active_paper.status in {"ready", "in_progress"}
        ):
            return ok_response(_paper_detail(session, active_paper))
        abandoned = exams_repo.abandon_mastery_drill_session(
            session,
            drill_session_id=int(active.id or 0),
            abandoned_at=utcnow(),
        )
        if abandoned:
            logger.warning(
                "mastery_drill_inconsistent_active_session_abandoned",
                course_id=normalized,
                user_id=user.user_id,
                drill_session_id=int(active.id or 0),
                exam_paper_id=int(active.exam_paper_id or 0),
                exam_paper_status=str(active_paper.status if active_paper is not None else "missing"),
            )
        session.expire_all()

    existing = exams_repo.get_mastery_drill_session_by_key(
        session,
        course_id=normalized,
        user_id=user.user_id,
        session_key=body.session_key,
    )
    if existing is not None:
        existing_paper = exams_repo.get_exam_paper_by_id(session, int(existing.exam_paper_id or 0))
        if existing_paper is not None and not _is_hidden_exam_paper(existing_paper):
            return ok_response(_paper_detail(session, existing_paper))

    template_ids = [int(template_id) for template_id in body.question_template_ids]
    if len(template_ids) != len(set(template_ids)):
        raise AITeachMeError(
            detail="Mastery drill question template IDs must be unique.",
            error_code="MASTERY_DRILL_DUPLICATE_TEMPLATE",
            status_code=400,
        )
    templates = list(
        session.exec(
            select(QuestionTemplate).where(
                QuestionTemplate.course_id == normalized,
                QuestionTemplate.id.in_(template_ids),
            )
        ).all()
    )
    template_by_id = {int(template.id or 0): template for template in templates}
    missing_template_ids = [template_id for template_id in template_ids if template_id not in template_by_id]
    if missing_template_ids:
        raise AITeachMeError(
            detail="One or more mastery drill templates were not found.",
            error_code="MASTERY_DRILL_TEMPLATE_NOT_FOUND",
            status_code=404,
            data={"question_template_ids": missing_template_ids},
        )

    ordered_templates = [template_by_id[template_id] for template_id in template_ids]
    for template in ordered_templates:
        _require_supported_question_type_for_api(template.question_type)
        if template.status != "active":
            raise AITeachMeError(
                detail=f"Question template `{template.id}` is not active.",
                error_code="MASTERY_DRILL_TEMPLATE_NOT_ACTIVE",
                status_code=409,
                data={"question_template_id": int(template.id or 0), "status": template.status},
            )
        if not template.stem.strip() or not template.answer.strip():
            raise AITeachMeError(
                detail=f"Question template `{template.id}` is incomplete.",
                error_code="MASTERY_DRILL_TEMPLATE_INCOMPLETE",
                status_code=409,
                data={"question_template_id": int(template.id or 0)},
            )

    configured_question_types = [
        _require_supported_question_type_for_api(question_type)
        for question_type in body.configured_question_types
    ]
    now = utcnow()
    config_snapshot = {
        "version": 1,
        "configured_question_count": int(body.configured_question_count),
        "configured_question_types": configured_question_types,
        "question_template_ids": template_ids,
    }
    config_json = json.dumps(config_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    paper = ExamPaper(
        course_id=normalized,
        user_id=user.user_id,
        exam_mode="mastery_drill",
        status="in_progress",
        visibility="visible",
        generation_origin="mastery_drill_session",
        config_hash=hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
        config_snapshot_json=config_json,
        total_items=len(ordered_templates),
        total_score=float(len(ordered_templates)),
        selection_context_json=json.dumps(
            {
                "standalone_mastery_drill": True,
                "persistent_mastery_drill": True,
                "title": "独立闯关训练",
            },
            ensure_ascii=False,
        ),
        created_at=now,
        updated_at=now,
    )
    try:
        exams_repo.create_exam_paper(session, paper, auto_commit=False)
        template_links = exams_repo.list_links_for_templates(session, template_ids)
        items = exams_repo.create_exam_paper_items(
            session,
            [
                ExamPaperItem(
                    exam_paper_id=int(paper.id or 0),
                    question_template_id=int(template.id or 0),
                    item_order=index,
                    stem_snapshot=template.stem,
                    options_snapshot_json=template.options_json,
                    answer_snapshot=template.answer,
                    explanation_snapshot=template.explanation,
                    selection_context_json=json.dumps(
                        {
                            "mastery_drill_session": True,
                            "template_version": int(template.template_version or 1),
                        },
                        ensure_ascii=False,
                    ),
                    difficulty=template.difficulty,
                    question_type=template.question_type,
                    score=1.0,
                    created_at=now,
                    updated_at=now,
                )
                for index, template in enumerate(ordered_templates, start=1)
            ],
            auto_commit=False,
        )
        for item in items:
            exams_repo.replace_exam_paper_item_links(
                session,
                item_id=int(item.id or 0),
                refs=template_links.get(int(item.question_template_id or 0), []),
                auto_commit=False,
            )
        drill = MasteryDrillSession(
            exam_paper_id=int(paper.id or 0),
            course_id=normalized,
            user_id=user.user_id,
            session_key=body.session_key,
            status="active",
            config_snapshot_json=config_json,
            started_at=now,
            created_at=now,
            updated_at=now,
        )
        exams_repo.create_mastery_drill_session(session, drill, auto_commit=False)
        session.commit()
    except IntegrityError:
        session.rollback()
        existing = exams_repo.get_mastery_drill_session_by_key(
            session,
            course_id=normalized,
            user_id=user.user_id,
            session_key=body.session_key,
        )
        if existing is None:
            existing = exams_repo.get_active_mastery_drill_session(
                session,
                course_id=normalized,
                user_id=user.user_id,
            )
        if existing is None:
            raise
        concurrent_paper = exams_repo.get_exam_paper_by_id(session, int(existing.exam_paper_id or 0))
        if concurrent_paper is None or _is_hidden_exam_paper(concurrent_paper):
            raise
        return ok_response(_paper_detail(session, concurrent_paper))

    session.expire_all()
    stored_paper = exams_repo.get_exam_paper_by_id(session, int(paper.id or 0))
    if stored_paper is None:
        _raise_not_found("Created mastery drill paper was not found.")
    _capture_exam_event(
        "mastery_drill_session_started",
        course_id=normalized,
        user=user,
        paper=stored_paper,
        insert_id_parts=[body.session_key],
        properties={
            "question_count": len(ordered_templates),
            "configured_question_count": int(body.configured_question_count),
            "configured_question_types": configured_question_types,
        },
    )
    return ok_response(_paper_detail(session, stored_paper))


@router.post(
    "/{exam_paper_id}/mastery-drill-attempts",
    response_model=ApiResponse[MasteryDrillAttemptResponse],
    summary="Persist and grade one mastery-drill attempt",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def record_mastery_drill_attempt(
    course_id: str = Path(...),
    exam_paper_id: int = Path(..., ge=1),
    body: MasteryDrillAttemptRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[MasteryDrillAttemptResponse]:
    normalized = normalize_course_id(course_id)
    course = _ensure_course(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.course_id != normalized or paper.user_id != user.user_id or _is_hidden_exam_paper(paper):
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    if paper.exam_mode != "mastery_drill":
        raise AITeachMeError(
            detail="This exam paper is not a mastery drill.",
            error_code="EXAM_NOT_MASTERY_DRILL",
            status_code=409,
        )
    drill = exams_repo.get_mastery_drill_session_by_paper(session, paper_id=exam_paper_id)
    if drill is None:
        _raise_not_found("Mastery drill session was not found.", error_code="MASTERY_DRILL_NOT_FOUND")
    if drill.status != "active" or paper.status not in {"ready", "in_progress"}:
        raise AITeachMeError(
            detail="This mastery drill is already complete.",
            error_code="MASTERY_DRILL_NOT_ACTIVE",
            status_code=409,
        )
    item = session.get(ExamPaperItem, body.exam_paper_item_id)
    if item is None or int(item.exam_paper_id or 0) != exam_paper_id:
        _raise_not_found(
            f"Exam paper item `{body.exam_paper_item_id}` not found.",
            error_code="EXAM_PAPER_ITEM_NOT_FOUND",
        )
    _require_supported_question_type_for_api(item.question_type)
    answer = str(body.answer or "").strip()
    if not answer:
        raise AITeachMeError(
            detail="Mastery drill answer cannot be empty.",
            error_code="MASTERY_DRILL_EMPTY_ANSWER",
            status_code=400,
        )
    request_payload = {
        "exam_paper_item_id": int(body.exam_paper_item_id),
        "answer": answer,
        "time_spent_seconds": body.time_spent_seconds,
        "hint_used": body.hint_used,
        "confidence_self_report": body.confidence_self_report,
    }
    request_hash = hashlib.sha256(
        json.dumps(request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    claimed_at = utcnow()
    claim_token = uuid.uuid4().hex
    outcome, attempt = exams_repo.claim_mastery_drill_attempt(
        session,
        drill_session_id=int(drill.id or 0),
        item=item,
        attempt_key=body.attempt_key,
        request_hash=request_hash,
        answer=answer,
        time_spent_seconds=body.time_spent_seconds,
        hint_used=body.hint_used,
        confidence_self_report=body.confidence_self_report,
        claim_token=claim_token,
        claimed_at=claimed_at,
        lease_expires_at=claimed_at + MASTERY_DRILL_ATTEMPT_LEASE_DURATION,
    )
    if outcome == "conflict":
        raise AITeachMeError(
            detail="This attempt key was already used for a different answer.",
            error_code="MASTERY_DRILL_ATTEMPT_CONFLICT",
            status_code=409,
        )
    if outcome == "completed":
        return ok_response(_mastery_drill_attempt_response(attempt))
    if outcome == "passed":
        raise AITeachMeError(
            detail="This mastery drill item was already passed.",
            error_code="MASTERY_DRILL_ITEM_ALREADY_PASSED",
            status_code=409,
        )
    if outcome == "in_progress":
        raise AITeachMeError(
            detail="This question already has an answer attempt being graded.",
            error_code="MASTERY_DRILL_ATTEMPT_IN_PROGRESS",
            status_code=409,
        )

    attempt_id = int(attempt.id or 0)
    heartbeat = asyncio.create_task(
        _renew_mastery_drill_attempt_lease_loop(attempt_id=attempt_id, claim_token=claim_token),
        name=f"mastery-drill-attempt.heartbeat:{attempt_id}",
    )
    try:
        grade = await _grade_exam_paper_item_answer(
            course_id=normalized,
            course_name=course.name,
            item=item,
            answer=answer,
        )
    except asyncio.CancelledError:
        exams_repo.fail_mastery_drill_attempt(
            session,
            attempt_id=attempt_id,
            claim_token=claim_token,
            error_code="MASTERY_DRILL_ATTEMPT_CANCELLED",
        )
        raise
    except Exception as exc:
        error_code = exc.error_code if isinstance(exc, AITeachMeError) else "MASTERY_DRILL_ATTEMPT_GRADE_FAILED"
        exams_repo.fail_mastery_drill_attempt(
            session,
            attempt_id=attempt_id,
            claim_token=claim_token,
            error_code=error_code,
        )
        raise
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning(
                "mastery_drill_attempt_heartbeat_cleanup_failed",
                attempt_id=attempt_id,
                error_type=type(exc).__name__,
            )

    finalized = exams_repo.finalize_mastery_drill_attempt(
        session,
        attempt_id=attempt_id,
        claim_token=claim_token,
        is_correct=grade.is_correct,
        score_obtained=grade.score_obtained,
        score_max=grade.score_max,
        feedback_text=grade.feedback_text,
        error_cause_label=grade.error_cause_label,
        grading_mode=grade.grading_mode,
        answered_at=utcnow(),
    )
    if finalized is None:
        current = exams_repo.get_mastery_drill_attempt_by_key(
            session,
            drill_session_id=int(drill.id or 0),
            attempt_key=body.attempt_key,
        )
        if current is not None and current.status == "graded":
            return ok_response(_mastery_drill_attempt_response(current))
        raise AITeachMeError(
            detail="The mastery drill grading claim was lost; retry the same attempt.",
            error_code="MASTERY_DRILL_ATTEMPT_CLAIM_LOST",
            status_code=409,
        )
    _capture_exam_event(
        "mastery_drill_attempt_graded",
        course_id=normalized,
        user=user,
        paper=paper,
        insert_id_parts=[str(finalized.id), body.attempt_key],
        properties={
            "question_type": item.question_type,
            "difficulty": item.difficulty,
            "attempt_no": finalized.attempt_no,
            "is_correct": finalized.is_correct,
            "grading_mode": finalized.grading_mode,
            "hint_used": finalized.hint_used,
        },
    )
    return ok_response(_mastery_drill_attempt_response(finalized))


@router.post(
    "/{exam_paper_id}/mastery-drill-complete",
    response_model=ApiResponse[ExamGradeResponse],
    summary="Idempotently complete a mastery drill",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def complete_mastery_drill(
    request: Request,
    background_tasks: BackgroundTasks,
    course_id: str = Path(...),
    exam_paper_id: int = Path(..., ge=1),
    body: MasteryDrillCompleteRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGradeResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.course_id != normalized or paper.user_id != user.user_id or _is_hidden_exam_paper(paper):
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    if paper.exam_mode != "mastery_drill":
        raise AITeachMeError(
            detail="This exam paper is not a mastery drill.",
            error_code="EXAM_NOT_MASTERY_DRILL",
            status_code=409,
        )
    drill = exams_repo.get_mastery_drill_session_by_paper(session, paper_id=exam_paper_id)
    if drill is None:
        _raise_not_found("Mastery drill session was not found.", error_code="MASTERY_DRILL_NOT_FOUND")
    if drill.status == "completed" and paper.status == "graded":
        return ok_response(_exam_grade_response_from_paper(session, paper))
    if drill.status != "active" or paper.status not in {"ready", "in_progress"}:
        raise AITeachMeError(
            detail="This mastery drill cannot be completed from its current state.",
            error_code="MASTERY_DRILL_NOT_COMPLETABLE",
            status_code=409,
        )

    items = exams_repo.list_items_by_paper(session, exam_paper_id)
    _require_supported_exam_items(items)
    incomplete_item_ids = [int(item.id or 0) for item in items if item.is_correct is not True]
    if incomplete_item_ids:
        raise AITeachMeError(
            detail="Every mastery drill item must be passed before completion.",
            error_code="MASTERY_DRILL_ITEMS_INCOMPLETE",
            status_code=409,
            data={"exam_paper_item_ids": incomplete_item_ids},
        )
    attempts = exams_repo.list_mastery_drill_attempts(
        session,
        drill_session_id=int(drill.id or 0),
    )
    graded_item_ids = {
        int(attempt.exam_paper_item_id)
        for attempt in attempts
        if attempt.status == "graded" and attempt.is_correct is True
    }
    missing_attempt_item_ids = [int(item.id or 0) for item in items if int(item.id or 0) not in graded_item_ids]
    if missing_attempt_item_ids:
        raise AITeachMeError(
            detail="Every mastery drill item requires a persisted correct attempt.",
            error_code="MASTERY_DRILL_ATTEMPTS_INCOMPLETE",
            status_code=409,
            data={"exam_paper_item_ids": missing_attempt_item_ids},
        )

    canonical_attempts = [
        {
            "id": int(attempt.id or 0),
            "item_id": int(attempt.exam_paper_item_id or 0),
            "is_correct": bool(attempt.is_correct),
        }
        for attempt in attempts
        if attempt.status == "graded"
    ]
    submission_hash = hashlib.sha256(
        json.dumps(canonical_attempts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    first_attempt_by_item_id: dict[int, MasteryDrillAttempt] = {}
    for attempt in attempts:
        if attempt.status != "graded":
            continue
        first_attempt_by_item_id.setdefault(int(attempt.exam_paper_item_id or 0), attempt)
    total_score = sum(float(item.score or 0.0) for item in items)
    score_obtained = 0.0
    for item in items:
        first_attempt = first_attempt_by_item_id.get(int(item.id or 0))
        if first_attempt is None:
            continue
        attempt_score_max = float(first_attempt.score_max or 0.0)
        if attempt_score_max <= 0:
            score_obtained += float(item.score or 0.0) if first_attempt.is_correct is True else 0.0
            continue
        score_ratio = max(0.0, min(1.0, float(first_attempt.score_obtained or 0.0) / attempt_score_max))
        score_obtained += float(item.score or 0.0) * score_ratio
    completed_at = utcnow()
    finalized = exams_repo.finalize_mastery_drill_session(
        session,
        drill=drill,
        paper=paper,
        completion_key=body.completion_key,
        submission_hash=submission_hash,
        total_score=total_score,
        score_obtained=score_obtained,
        duration_seconds=body.duration_seconds,
        completed_at=completed_at,
    )
    session.expire_all()
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    if not finalized and paper.status != "graded":
        raise AITeachMeError(
            detail="The mastery drill completion state changed; reload and retry.",
            error_code="MASTERY_DRILL_COMPLETION_CONFLICT",
            status_code=409,
        )

    if finalized:
        _capture_exam_event(
            "mastery_drill_session_completed",
            course_id=normalized,
            user=user,
            paper=paper,
            insert_id_parts=[body.completion_key, submission_hash],
            properties={
                "question_count": len(items),
                "total_attempt_count": len([attempt for attempt in attempts if attempt.status == "graded"]),
                "wrong_attempt_count": len(
                    [attempt for attempt in attempts if attempt.status == "graded" and attempt.is_correct is False]
                ),
                "duration_seconds": body.duration_seconds,
            },
        )

    profile_sync = exams_repo.get_exam_profile_sync(session, paper_id=exam_paper_id)
    if profile_sync is not None and is_exam_profile_sync_recoverable_now(profile_sync):
        registry = getattr(request.app.state, "background_task_registry", None)
        scheduled = schedule_exam_profile_sync_task(
            registry,
            course_id=normalized,
            user_id=user.user_id,
            paper_id=exam_paper_id,
        )
        if not scheduled:
            background_tasks.add_task(
                run_exam_profile_sync_background,
                course_id=normalized,
                user_id=user.user_id,
                paper_id=exam_paper_id,
            )
    return ok_response(_exam_grade_response_from_paper(session, paper))


@router.get(
    "/{exam_paper_id}/stream",
    summary="SSE stream for exam generation status",
    responses=build_error_responses([400, 404, 500]),
)
async def exam_generation_stream(
    request: Request,
    response: Response,
    course_id: str = Path(...),
    exam_paper_id: int = Path(...),
) -> StreamingResponse:
    normalized = normalize_course_id(course_id)
    with managed_session() as session:
        user = get_current_user_context(request, response, session)
        _ensure_course(session, normalized, user.user_id)
        paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
        if paper is None or paper.course_id != normalized or paper.user_id != user.user_id or _is_hidden_exam_paper(paper):
            _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")

    async def event_generator():
        snapshot_fallback_interval_s = get_sse_interval(
            "SSE_EXAM_SNAPSHOT_FALLBACK_INTERVAL_S",
            default=2.0,
        )
        last_snapshot_hash: str | None = None

        def snapshot_payload() -> dict[str, object]:
            with managed_session() as stream_session:
                current = exams_repo.get_exam_paper_by_id(stream_session, exam_paper_id)
                if current is None:
                    return {
                        "exam_paper_id": exam_paper_id,
                        "status": "failed",
                        "error_message": "Exam paper no longer exists.",
                    }
                return _paper_generation_event_payload(current)

        def should_emit_snapshot(snapshot: dict[str, object], *, force: bool = False) -> bool:
            nonlocal last_snapshot_hash
            snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, default=str)
            current_hash = hashlib.md5(snapshot_json.encode()).hexdigest()
            if not force and current_hash == last_snapshot_hash:
                return False
            last_snapshot_hash = current_hash
            return True

        initial = snapshot_payload()
        if should_emit_snapshot(initial, force=True):
            yield format_sse_event("snapshot", initial)
        if str(initial.get("status") or "") in {"ready", "failed", "graded"}:
            yield format_sse_event("done", initial)
            return

        with subscribe_workflow_stream(_exam_stream_channel(normalized, exam_paper_id)) as queue:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=snapshot_fallback_interval_s)
                except asyncio.TimeoutError:
                    snapshot = snapshot_payload()
                    if should_emit_snapshot(snapshot):
                        yield format_sse_event("snapshot", snapshot)
                    else:
                        yield format_sse_event("ping", {})
                    if str(snapshot.get("status") or "") in {"ready", "failed", "graded"}:
                        yield format_sse_event("done", snapshot)
                        break
                    continue
                except Exception:
                    break
                if event.event == "snapshot":
                    should_emit_snapshot(event.data, force=True)
                yield format_sse_event(event.event, event.data)
                if event.event == "done":
                    break

    stream_response = StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers=sse_headers(),
    )
    set_guest_cookie_for_user(stream_response, user_id=user.user_id)
    return stream_response


@router.get(
    "/{exam_paper_id}",
    response_model=ApiResponse[ExamPaperDetailResponse],
    summary="Fetch exam detail",
    responses=build_error_responses([400, 404, 500]),
)
async def exam_detail(
    request: Request,
    course_id: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDetailResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.course_id != normalized or paper.user_id != user.user_id or _is_hidden_exam_paper(paper):
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    if _is_exam_grading_recoverable_now(paper):
        _schedule_exam_grading_task(
            getattr(request.app.state, "background_task_registry", None),
            course_id=normalized,
            user_id=user.user_id,
            paper_id=exam_paper_id,
        )
    profile_sync = _ensure_legacy_exam_profile_sync(session, paper)
    if profile_sync is not None and is_exam_profile_sync_recoverable_now(profile_sync):
        schedule_exam_profile_sync_task(
            getattr(request.app.state, "background_task_registry", None),
            course_id=normalized,
            user_id=user.user_id,
            paper_id=exam_paper_id,
        )
    return ok_response(_paper_detail(session, paper))


@router.delete(
    "/{exam_paper_id}",
    response_model=ApiResponse[ExamPaperDeleteResponse],
    summary="Delete exam paper",
    responses=build_error_responses([400, 404, 500]),
)
async def delete_exam_paper(
    course_id: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDeleteResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.course_id != normalized or paper.user_id != user.user_id or _is_hidden_exam_paper(paper):
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")

    exams_repo.delete_exam_paper_cascade(session, paper_id=exam_paper_id)
    return ok_response(ExamPaperDeleteResponse(deleted=True, exam_paper_id=exam_paper_id))


@router.get(
    "/{exam_paper_id}/study-guide",
    response_model=ApiResponse[ExamStudyGuideResponse],
    summary="Generate study guide from a graded exam",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def exam_study_guide(
    course_id: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamStudyGuideResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.course_id != normalized or paper.user_id != user.user_id or _is_hidden_exam_paper(paper):
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    if paper.status != "graded":
        raise AITeachMeError(
            detail="Study guide is available only after grading is complete.",
            error_code="EXAM_NOT_GRADED",
            status_code=409,
        )
    return ok_response(await _study_guide_detail(session, paper))


@router.post(
    "/{exam_paper_id}/profile-sync/retry",
    response_model=ApiResponse[ExamProfileSyncResponse],
    summary="Retry Profile synchronization for a graded exam",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def retry_exam_profile_sync(
    request: Request,
    background_tasks: BackgroundTasks,
    course_id: str = Path(...),
    exam_paper_id: int = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamProfileSyncResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.course_id != normalized or paper.user_id != user.user_id or _is_hidden_exam_paper(paper):
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    if paper.status != "graded":
        raise AITeachMeError(
            detail="Profile synchronization is available only after grading is complete.",
            error_code="EXAM_NOT_GRADED",
            status_code=409,
        )

    task = exams_repo.get_exam_profile_sync(session, paper_id=exam_paper_id)
    if task is None:
        task = exams_repo.ensure_exam_profile_sync(
            session,
            paper=paper,
            status="pending",
            trigger="manual_retry",
            next_attempt_at=utcnow(),
            auto_commit=True,
        )
    elif task.status in {"failed", "retry_wait"}:
        exams_repo.request_exam_profile_sync_retry(
            session,
            paper_id=exam_paper_id,
            requested_at=utcnow(),
        )
        session.expire_all()
        task = exams_repo.get_exam_profile_sync(session, paper_id=exam_paper_id) or task

    if is_exam_profile_sync_recoverable_now(task):
        background_task_registry = getattr(request.app.state, "background_task_registry", None)
        scheduled = schedule_exam_profile_sync_task(
            background_task_registry,
            course_id=normalized,
            user_id=user.user_id,
            paper_id=exam_paper_id,
        )
        if not scheduled:
            background_tasks.add_task(
                run_exam_profile_sync_background,
                course_id=normalized,
                user_id=user.user_id,
                paper_id=exam_paper_id,
            )
    return ok_response(_exam_profile_sync_response(session, paper, task=task))


@router.post(
    "/{exam_paper_id}/submit",
    response_model=ApiResponse[ExamGradeResponse],
    summary="Submit answers and start grading",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def submit_exam(
    request: Request,
    background_tasks: BackgroundTasks,
    course_id: str = Path(...),
    exam_paper_id: int = Path(...),
    body: ExamSubmitRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGradeResponse]:
    normalized = normalize_course_id(course_id)
    _ensure_course(session, normalized, user.user_id)
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.course_id != normalized or paper.user_id != user.user_id or _is_hidden_exam_paper(paper):
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    _require_generic_exam_mode(str(paper.exam_mode or ""))
    if paper.status == "generating":
        raise AITeachMeError(detail="Exam is still generating.", error_code="EXAM_STILL_GENERATING", status_code=409)
    if paper.status == "failed":
        raise AITeachMeError(detail="Exam generation failed.", error_code="EXAM_GENERATION_FAILED", status_code=409)
    paper_items = exams_repo.list_items_by_paper(session, exam_paper_id)
    _require_supported_exam_items(paper_items)
    resolved_answers, submission_hash, submission_key = _resolve_exam_submission_answers(paper_items, body)

    accepted_now = False
    restarted_now = False
    now = utcnow()
    if paper.submission_hash:
        if paper.submission_hash != submission_hash:
            raise AITeachMeError(
                detail="This exam was already submitted with different answers.",
                error_code="EXAM_SUBMISSION_CONFLICT",
                status_code=409,
            )
    elif paper.status in {"submitted", "grading", "grading_failed"}:
        legacy_answers_match = all(
            str(item.answer_content or "") == resolved_answers.get(int(item.id or 0), "")
            for item in paper_items
        )
        if not legacy_answers_match:
            raise AITeachMeError(
                detail="This exam was already submitted with different answers.",
                error_code="EXAM_SUBMISSION_CONFLICT",
                status_code=409,
            )
        paper.submission_key = submission_key
        paper.submission_hash = submission_hash
        paper.updated_at = now
        session.add(paper)
        session.commit()
    elif paper.status == "graded":
        # Papers graded before submission fingerprints were introduced remain safely readable.
        return ok_response(_exam_grade_response_from_paper(session, paper))
    elif paper.status in {"ready", "in_progress"}:
        accepted_now = exams_repo.claim_exam_submission(
            session,
            paper_id=exam_paper_id,
            submission_key=submission_key,
            submission_hash=submission_hash,
            submitted_at=now,
        )
        if accepted_now:
            for item in paper_items:
                item.answer_content = resolved_answers.get(int(item.id or 0), "")
                item.answered_at = now
                item.updated_at = now
                session.add(item)
            session.commit()
        else:
            session.rollback()
            session.expire_all()
            paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
            if paper is None:
                _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
            if paper.submission_hash != submission_hash:
                raise AITeachMeError(
                    detail="This exam was already submitted with different answers.",
                    error_code="EXAM_SUBMISSION_CONFLICT",
                    status_code=409,
                )
    else:
        raise AITeachMeError(
            detail=f"Exam status `{paper.status}` cannot be submitted.",
            error_code="EXAM_NOT_SUBMITTABLE",
            status_code=409,
        )

    if paper.status == "graded":
        return ok_response(_exam_grade_response_from_paper(session, paper))
    if paper.status == "grading_failed":
        restarted_now = exams_repo.restart_failed_exam_grading(
            session,
            paper_id=exam_paper_id,
            submission_hash=submission_hash,
            restarted_at=now,
        )
        if restarted_now:
            session.commit()
        else:
            session.rollback()

    session.expire_all()
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None:
        _raise_not_found(f"Exam paper `{exam_paper_id}` not found.")
    if accepted_now:
        _capture_exam_event(
            "exam_submitted",
            course_id=normalized,
            user=user,
            paper=paper,
            insert_id_parts=["submitted", submission_hash],
            properties={
                "answer_count": len(body.answers),
                "answered_count": sum(1 for answer in resolved_answers.values() if answer.strip()),
            },
        )
    elif restarted_now:
        _capture_exam_event(
            "exam_grading_restarted",
            course_id=normalized,
            user=user,
            paper=paper,
            insert_id_parts=["manual-retry", submission_hash, now.isoformat()],
            properties={"automatic_attempt_limit": EXAM_GRADING_MAX_ATTEMPTS},
        )

    background_task_registry = getattr(request.app.state, "background_task_registry", None)
    scheduled = _schedule_exam_grading_task(
        background_task_registry,
        course_id=normalized,
        user_id=user.user_id,
        paper_id=exam_paper_id,
    )
    if not scheduled:
        background_tasks.add_task(
            _run_exam_grading_background,
            course_id=normalized,
            user_id=user.user_id,
            paper_id=exam_paper_id,
            background_task_registry=None,
        )
    return ok_response(_exam_grade_response_from_paper(session, paper))
