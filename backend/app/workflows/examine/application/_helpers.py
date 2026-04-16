"""Exam service shared helpers, DTOs and internal utilities."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from math import ceil
from time import perf_counter

import structlog
from sqlmodel import Session, select

from app.shared.infra.database import managed_session
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.memory import append_to_learner_section, log_learning_event, sync_profile_to_doc
from app.models import (
    ExamMode,
    ExamPaper,
    ExamPaperItem,
    QuestionType,
    is_paper_exam_mode,
    is_web_practice_mode,
    normalize_exam_mode,
)
from app.repositories import exams_repo, profile_repo
from app.utils.time import utcnow
from app.workflows.examine.context import (
    ExamStyleProfile,
    normalize_difficulty_focus,
)
from app.workflows.examine.paper_exporter import compile_tex_to_pdf_artifact

logger = structlog.get_logger()


# 鈹€鈹€ DTOs 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

@dataclass(frozen=True)
class ExamPaperDetail:
    paper: ExamPaper
    items: list[ExamPaperItem]
    attempts_by_item_id: dict[int, ExamPaperItem]


@dataclass(frozen=True)
class QuestionBankItem:
    question_template_id: int
    stem: str
    question_type: str
    difficulty: str
    teaching_unit_id: int
    times_asked: int
    last_asked_at: datetime
    last_exam_paper_id: int
    knowledge_points: list[str]
    style_summary: str | None


@dataclass(frozen=True)
class QuestionBuildResult:
    id: int
    subject: str
    status: str
    templates_created: int
    warnings_json: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ExamGenerationResult:
    id: int
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    subject: str
    user_id: str
    exam_mode: str
    num_questions: int
    exam_paper_id: int | None
    theme_tree_node_id: int | None
    teaching_unit_ids_json: str
    sample_file_uids_json: str


@dataclass(frozen=True)
class ExamGradingResult:
    id: int
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    exam_paper_id: int
    score: float | None
    states_updated: int
    tasks_created: int
    mastery_consumed: bool


# 鈹€鈹€ Concurrency primitives 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

_exam_generate_locks: dict[tuple[str, str], asyncio.Lock] = {}
_exam_generate_locks_guard = asyncio.Lock()
_paper_export_tasks: set[asyncio.Task[None]] = set()


# 鈹€鈹€ Internal utility functions 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€

def _new_runtime_job_id() -> int:
    return (int(utcnow().timestamp() * 1_000_000) % 2_000_000_000) + 1


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((perf_counter() - started_at) * 1000)))


def _track_background_task(task: asyncio.Task[None]) -> None:
    _paper_export_tasks.add(task)
    task.add_done_callback(_paper_export_tasks.discard)


def _raise_not_found(detail: str, *, error_code: str = "NOT_FOUND") -> None:
    raise AITeachMeError(
        detail=detail,
        status_code=HTTPStatus.NOT_FOUND,
        error_code=error_code,
    )


def _raise_conflict(detail: str, *, error_code: str = "CONFLICT") -> None:
    raise AITeachMeError(
        detail=detail,
        status_code=HTTPStatus.CONFLICT,
        error_code=error_code,
    )


def _normalize_answers_payload(*, answers: dict[int | str, str]) -> dict[int, str]:
    normalized: dict[int, str] = {}
    for raw_key, value in answers.items():
        try:
            key = int(raw_key)
        except (TypeError, ValueError):
            continue
        normalized[key] = value
    return normalized


def _parse_json_list(raw: str | None) -> list[object]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


def _parse_json_object(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _resolve_template_count_difficulty(difficulty: str | None) -> str | None:
    normalized = normalize_difficulty_focus(difficulty)
    if normalized in {"easy", "medium", "hard"}:
        return normalized
    return None


def _extract_requested_question_count(user_prompt: str | None) -> int | None:
    if not user_prompt:
        return None
    match = re.search(r"(\d{1,3})\s*(?:棰榺閬搢questions?)", user_prompt, re.IGNORECASE)
    if not match:
        return None
    value = int(match.group(1))
    return max(1, min(200, value))


def _choose_default_question_count(mode: str) -> int:
    defaults = {
        ExamMode.WEB_PRACTICE.value: 10,
        ExamMode.PAPER_EXAM.value: 24,
    }
    return defaults.get(mode, 10)


def _choose_preferred_question_types(
    mode: str,
    user_prompt: str | None,
    style_profile=None,
) -> list[str]:
    prompt = (user_prompt or "").lower()
    picked: list[str] = []
    if any(key in prompt for key in ["閫夋嫨", "鍗曢€?, "choice", "mcq"]):
        picked.append(QuestionType.SINGLE_CHOICE.value)
    if any(key in prompt for key in ["濉┖", "blank"]):
        picked.append(QuestionType.FILL_BLANK.value)
    if any(key in prompt for key in ["绠€绛?, "闂瓟", "瑙ｇ瓟", "鍒嗘瀽", "璁鸿堪", "essay"]):
        picked.append(QuestionType.SHORT_ANSWER.value)

    if picked:
        return list(dict.fromkeys(picked))

    profile_types = [
        str(item).strip()
        for item in getattr(style_profile, "preferred_question_types", []) or []
        if str(item).strip()
    ]
    if profile_types:
        return list(dict.fromkeys(profile_types))

    if is_paper_exam_mode(mode):
        return [
            QuestionType.SINGLE_CHOICE.value,
            QuestionType.FILL_BLANK.value,
            QuestionType.SHORT_ANSWER.value,
        ]
    if is_web_practice_mode(mode):
        return [
            QuestionType.SINGLE_CHOICE.value,
            QuestionType.FILL_BLANK.value,
            QuestionType.SHORT_ANSWER.value,
        ]
    return [QuestionType.SINGLE_CHOICE.value, QuestionType.FILL_BLANK.value]


def _estimate_questions_per_unit(*, num_questions: int, unit_count: int, mode: str) -> int:
    if unit_count <= 0:
        return 3
    spread_units = max(1, min(unit_count, 8))
    baseline = (num_questions + spread_units - 1) // spread_units
    if is_paper_exam_mode(mode):
        baseline = max(baseline, 4)
    return max(2, min(12, baseline))


def _resolve_generate_mode(exam_mode: ExamMode | str) -> str:
    return normalize_exam_mode(exam_mode)


async def _acquire_exam_generate_lock(*, subject: str, user_id: str) -> asyncio.Lock:
    key = (subject, user_id)
    async with _exam_generate_locks_guard:
        lock = _exam_generate_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _exam_generate_locks[key] = lock

    if lock.locked():
        _raise_conflict(
            "褰撳墠宸叉湁璇曞嵎鐢熸垚浠诲姟杩涜涓紝璇风◢鍚庡啀璇曘€?,
            error_code="EXAM_GENERATE_JOB_ACTIVE",
        )
    await lock.acquire()
    return lock


async def _compile_paper_export_async(
    *,
    exam_paper_id: int,
    tex_path: str,
    runtime_job_id: int,
    subject: str,
    user_id: str,
) -> None:
    started_at = perf_counter()
    try:
        pdf_path, compiler, compile_log_path = await asyncio.to_thread(
            compile_tex_to_pdf_artifact,
            tex_path,
        )

        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
            if paper is None:
                return

            selection_context = _parse_json_object(paper.selection_context_json)
            export_artifacts = selection_context.get("export_artifacts")
            if not isinstance(export_artifacts, dict):
                export_artifacts = {}
                selection_context["export_artifacts"] = export_artifacts

            export_artifacts["pdf_path"] = pdf_path
            export_artifacts["compiler"] = compiler
            export_artifacts["compile_log_path"] = compile_log_path
            export_artifacts["pdf_compile_status"] = "completed" if pdf_path else "failed"
            paper.selection_context_json = json.dumps(selection_context, ensure_ascii=False)
            paper.updated_at = utcnow()
            session.add(paper)
            session.commit()

        logger.info(
            "exam_generate_paper_pdf_compile_finished",
            runtime_job_id=runtime_job_id,
            subject=subject,
            user_id=user_id,
            exam_paper_id=exam_paper_id,
            pdf_path=pdf_path,
            compiler=compiler,
            compile_log_path=compile_log_path,
            compile_elapsed_ms=_elapsed_ms(started_at),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "exam_generate_paper_pdf_compile_failed",
            runtime_job_id=runtime_job_id,
            subject=subject,
            user_id=user_id,
            exam_paper_id=exam_paper_id,
            tex_path=tex_path,
            error=str(exc),
        )


async def _sync_exam_learning_memory(
    *,
    paper: ExamPaper,
    score_percent: float,
    correct_count: int,
    total_count: int,
) -> None:
    summary = (
        f"{paper.subject} 瀹屾垚{('鑰冭瘯鍗? if is_paper_exam_mode(paper.exam_mode) else '鍦ㄧ嚎娴嬮獙')}锛?
        f"寰楀垎 {correct_count}/{total_count}锛坽score_percent:.1f} 鍒嗭級"
    )
    note_line = f"- {summary}"
    advice_line = f"- {paper.subject}锛氭渶杩戜竴娆′綔绛斿緱鍒?{score_percent:.1f} 鍒嗭紝鍙嵁姝よ皟鏁翠笅涓€杞瑙ｄ笌缁冧範闅惧害銆?

    await log_learning_event(
        paper.user_id,
        event_type="exam",
        subject=paper.subject,
        summary=summary,
        metadata={
            "exam_paper_id": paper.id,
            "exam_mode": paper.exam_mode,
            "correct_count": correct_count,
            "total_count": total_count,
            "score_percent": round(score_percent, 2),
        },
    )
    await sync_profile_to_doc(paper.user_id)
    await append_to_learner_section(
        paper.user_id,
        "鏈€杩戝涔犱富棰?,
        note_line,
    )
    await append_to_learner_section(
        paper.user_id,
        "鏁欏澶囨敞",
        advice_line,
    )


def _prioritize_build_unit_ids(
    session: Session,
    *,
    subject: str,
    user_id: str,
    candidate_unit_ids: list[int],
    mode: str,
    required_question_count: int,
    questions_per_unit: int,
    style_profile: ExamStyleProfile,
) -> list[int]:
    if len(candidate_unit_ids) <= 1:
        return candidate_unit_ids

    desired_unit_count = max(1, ceil(required_question_count / max(1, questions_per_unit)))
    desired_unit_count += 2 if is_paper_exam_mode(mode) else 1
    desired_unit_count = min(
        len(candidate_unit_ids),
        max(4 if is_web_practice_mode(mode) else 6, desired_unit_count),
        8 if is_web_practice_mode(mode) else 12,
    )

    prioritized: list[int] = []
    seen: set[int] = set()

    def _append(values: list[int]) -> None:
        for value in values:
            if value not in candidate_unit_ids or value in seen:
                continue
            seen.add(value)
            prioritized.append(value)

    _append([int(item) for item in style_profile.focus_teaching_unit_ids if int(item) > 0])
    due_states = profile_repo.list_due_knowledge_states(
        session,
        user_id=user_id,
        subject=subject,
        as_of=utcnow(),
        target_kind="unit",
    )
    _append([
        int(state.teaching_unit_id)
        for state in due_states
        if state.teaching_unit_id is not None
    ])
    weak_states = profile_repo.list_weak_knowledge_states(
        session,
        user_id=user_id,
        subject=subject,
        threshold=0.8,
        target_kind="unit",
    )
    _append([
        int(state.teaching_unit_id)
        for state in weak_states
        if state.teaching_unit_id is not None
    ])
    _append(candidate_unit_ids)
    return prioritized[:desired_unit_count]


def _resolve_requested_unit_scope(
    session: Session,
    *,
    subject: str,
    teaching_unit_ids: list[int] | None,
    theme_tree_node_id: int | None,
) -> list[int]:
    allowed_ids = set(
        exams_repo.list_teaching_unit_ids_by_subject(
            session,
            subject=subject,
            status=None,
        )
    )
    if teaching_unit_ids:
        normalized = sorted(
            {
                int(item)
                for item in teaching_unit_ids
                if int(item) > 0 and int(item) in allowed_ids
            }
        )
        return normalized

    if theme_tree_node_id is None:
        return []

    resolved = exams_repo.resolve_teaching_units_from_theme_tree_node(session, theme_tree_node_id)
    return sorted(int(unit_id) for unit_id in resolved if int(unit_id) in allowed_ids)


def _resolve_auto_build_unit_ids(
    session: Session,
    *,
    subject: str,
    teaching_unit_ids: list[int] | None,
    theme_tree_node_id: int | None,
) -> list[int]:
    requested_scope_ids = _resolve_requested_unit_scope(
        session,
        subject=subject,
        teaching_unit_ids=teaching_unit_ids,
        theme_tree_node_id=theme_tree_node_id,
    )
    if requested_scope_ids:
        return requested_scope_ids

    active_ids = exams_repo.list_teaching_unit_ids_by_subject(
        session,
        subject=subject,
        status="active",
    )
    if active_ids:
        return active_ids

    return exams_repo.list_teaching_unit_ids_by_subject(
        session,
        subject=subject,
        status=None,
    )


def _count_effective_template_inventory(
    session: Session,
    *,
    subject: str,
    curriculum_version_id: int,
    unit_ids: list[int],
    preferred_question_types: list[str],
    difficulty: str | None,
    template_context_signature: str | None,
    context_locked: bool,
) -> int:
    from app.workflows.examine.context import template_matches_request_context

    candidate_templates = exams_repo.list_active_question_templates(
        session,
        subject=subject,
        curriculum_version_id=curriculum_version_id,
        unit_ids=set(unit_ids) if unit_ids else None,
        question_types=set(preferred_question_types) if preferred_question_types else None,
        difficulty=difficulty,
    )
    return sum(
        1
        for template in candidate_templates
        if template_matches_request_context(
            template.selection_hints_json,
            requested_context_signature=template_context_signature,
            context_locked=context_locked,
        )
    )


def _summarize_style_hint(selection_hints_json: str | None) -> str | None:
    hints = _parse_json_object(selection_hints_json)
    style_profile = hints.get("style_profile")
    if not isinstance(style_profile, dict):
        return None

    parts: list[str] = []
    title_hint = style_profile.get("title_hint")
    if isinstance(title_hint, str) and title_hint.strip():
        parts.append(title_hint.strip())

    format_hint = style_profile.get("format_hint")
    if isinstance(format_hint, str) and format_hint.strip() and format_hint != "standard":
        parts.append(format_hint.strip())

    focus_prompt = style_profile.get("focus_prompt")
    if isinstance(focus_prompt, str) and focus_prompt.strip():
        parts.append(focus_prompt.strip())

    if not parts:
        notes = style_profile.get("notes")
        if isinstance(notes, list):
            for note in notes:
                if isinstance(note, str) and note.strip():
                    parts.append(note.strip())
                    break

    if not parts:
        return None
    return " | ".join(parts[:2])


def _resolve_template_knowledge_points(
    session: Session,
    *,
    template_ids: list[int],
) -> dict[int, list[str]]:
    from app.models import KnowledgeUnit, QuestionTemplate

    if not template_ids:
        return {}

    templates = list(
        session.exec(
            select(QuestionTemplate).where(QuestionTemplate.id.in_(template_ids))
        ).all()
    )
    node_ids: set[int] = set()
    refs_by_template: dict[int, list[dict[str, object]]] = {}
    for template in templates:
        if template.id is None:
            continue
        refs = [item for item in _parse_json_list(template.node_refs_json) if isinstance(item, dict)]
        refs_by_template[int(template.id)] = refs
        for ref in refs:
            raw_node_id = ref.get("knowledge_node_id")
            if isinstance(raw_node_id, int) and raw_node_id > 0:
                node_ids.add(raw_node_id)

    nodes = list(session.exec(select(KnowledgeUnit).where(KnowledgeUnit.id.in_(node_ids))).all()) if node_ids else []
    node_name_by_id = {int(node.id): node.canonical_name for node in nodes if node.id is not None}

    result: dict[int, list[str]] = {}
    for template_id, refs in refs_by_template.items():
        names: list[str] = []
        for ref in refs:
            raw_node_id = ref.get("knowledge_node_id")
            if isinstance(raw_node_id, int) and raw_node_id in node_name_by_id:
                names.append(node_name_by_id[raw_node_id])
        deduped = list(dict.fromkeys(name for name in names if name))
        result[template_id] = deduped
    return result

