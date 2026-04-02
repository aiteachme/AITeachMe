"""Exam domain service layer."""

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

from app.core.database import managed_session
from app.core.exceptions import AITeachMeError, NoPublishedCurriculumSnapshotError
from app.infra.memory import append_to_learner_section, log_learning_event, sync_profile_to_doc
from app.infra.tracing import llm_trace_scope
from app.models import (
    ExamMode,
    ExamPaper,
    ExamPaperItem,
    ExamPaperStatus,
    KnowledgeNode,
    QuestionTemplate,
    QuestionType,
    is_paper_exam_mode,
    is_web_practice_mode,
    normalize_exam_mode,
    validate_status_transition,
)
from app.repositories import exams_repo, profile_repo
from app.schemas.common import PaginatedData, build_paginated_data
from app.utils.time import seconds_between, utcnow
from app.workflows.examine.answer_grader import grade_paper
from app.workflows.examine.context import (
    ExamStyleProfile,
    build_exam_style_profile,
    normalize_difficulty_focus,
)
from app.workflows.examine.paper_assembler import assemble_paper
from app.workflows.examine.paper_exporter import (
    compile_tex_to_pdf_artifact,
    export_exam_paper_artifacts,
)
from app.workflows.examine.question_build_workflow import QuestionBuildWorkflow
from app.workflows.profile.mastery_updater import update_mastery_from_exam
from app.workflows.profile.review_scheduler import schedule_reviews
from app.workflows.profile.subject_profile import refresh_subject_profile_summary
from app.workflows.profile.user_profile import refresh_user_profile_summary

logger = structlog.get_logger()


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


_exam_generate_locks: dict[tuple[str, str], asyncio.Lock] = {}
_exam_generate_locks_guard = asyncio.Lock()
_paper_export_tasks: set[asyncio.Task[None]] = set()


def _new_runtime_job_id() -> int:
    return (int(utcnow().timestamp() * 1_000_000) % 2_000_000_000) + 1


def _elapsed_ms(started_at: float) -> int:
    return max(0, int(round((perf_counter() - started_at) * 1000)))


def _track_background_task(task: asyncio.Task[None]) -> None:
    _paper_export_tasks.add(task)
    task.add_done_callback(_paper_export_tasks.discard)


def _resolve_template_count_difficulty(difficulty: str | None) -> str | None:
    normalized = normalize_difficulty_focus(difficulty)
    if normalized in {"easy", "medium", "hard"}:
        return normalized
    return None


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
        f"{paper.subject} 完成{('考试卷' if is_paper_exam_mode(paper.exam_mode) else '在线测验')}，"
        f"得分 {correct_count}/{total_count}（{score_percent:.1f} 分）"
    )
    note_line = f"- {summary}"
    advice_line = f"- {paper.subject}：最近一次作答得分 {score_percent:.1f} 分，可据此调整下一轮讲解与练习难度。"

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
        "最近学习主题",
        note_line,
    )
    await append_to_learner_section(
        paper.user_id,
        "教学备注",
        advice_line,
    )


async def _acquire_exam_generate_lock(*, subject: str, user_id: str) -> asyncio.Lock:
    key = (subject, user_id)
    async with _exam_generate_locks_guard:
        lock = _exam_generate_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _exam_generate_locks[key] = lock

    if lock.locked():
        _raise_conflict(
            "当前已有试卷生成任务进行中，请稍后再试。",
            error_code="EXAM_GENERATE_JOB_ACTIVE",
        )
    await lock.acquire()
    return lock


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


def _extract_requested_question_count(user_prompt: str | None) -> int | None:
    if not user_prompt:
        return None
    match = re.search(r"(\d{1,3})\s*(?:题|道|questions?)", user_prompt, re.IGNORECASE)
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
    if any(key in prompt for key in ["选择", "单选", "choice", "mcq"]):
        picked.append(QuestionType.SINGLE_CHOICE.value)
    if any(key in prompt for key in ["填空", "blank"]):
        picked.append(QuestionType.FILL_BLANK.value)
    if any(key in prompt for key in ["简答", "问答", "解答", "分析", "论述", "essay"]):
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


def _resolve_auto_build_unit_ids(
    session: Session,
    *,
    subject: str,
    teaching_unit_ids: list[int] | None,
) -> list[int]:
    if teaching_unit_ids:
        normalized = sorted({int(item) for item in teaching_unit_ids if int(item) > 0})
        if normalized:
            return normalized

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

    nodes = list(session.exec(select(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids))).all()) if node_ids else []
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


async def trigger_question_build(
    session: Session,
    *,
    subject: str,
    user_id: str,
    unit_ids: list[int],
    questions_per_unit: int,
    exam_mode: str,
    preferred_question_types: list[str] | None = None,
    user_prompt: str | None = None,
    focus_prompt: str | None = None,
    style_profile: ExamStyleProfile | None = None,
) -> QuestionBuildResult:
    runtime_job_id = _new_runtime_job_id()
    created_at = utcnow()
    resolved_questions_per_unit = max(1, int(questions_per_unit))

    try:
        with llm_trace_scope(
            subject=subject,
            build_session_id=str(runtime_job_id),
            workflow="examine.question_build",
            lane="question_build",
            node="generate_templates",
        ):
            state = await QuestionBuildWorkflow.run(
                subject=subject,
                user_id=user_id,
                unit_ids=unit_ids,
                questions_per_unit=resolved_questions_per_unit,
                job_id=runtime_job_id,
                exam_mode=exam_mode,
                preferred_question_types=preferred_question_types or [],
                user_prompt=user_prompt,
                focus_prompt=focus_prompt,
                style_profile=style_profile,
                session=session,
            )
        error = state.get("error")
        updated_at = utcnow()
        return QuestionBuildResult(
            id=runtime_job_id,
            subject=subject,
            status="failed" if error else "completed",
            templates_created=int(state.get("templates_created", 0)),
            warnings_json=json.dumps(state.get("warnings", []), ensure_ascii=False),
            error_message=str(error) if error else None,
            created_at=created_at,
            updated_at=updated_at,
        )
    except Exception as exc:  # noqa: BLE001
        updated_at = utcnow()
        logger.error(
            "trigger_question_build_failed",
            subject=subject,
            user_id=user_id,
            error=str(exc),
            exc_info=True,
        )
        return QuestionBuildResult(
            id=runtime_job_id,
            subject=subject,
            status="failed",
            templates_created=0,
            warnings_json="[]",
            error_message=str(exc),
            created_at=created_at,
            updated_at=updated_at,
        )


async def trigger_exam_generate(
    session: Session,
    *,
    subject: str,
    user_id: str,
    exam_mode: ExamMode | str,
    difficulty: str | None = None,
    num_questions: int | None = None,
    user_prompt: str | None = None,
    style_prompt: str | None = None,
    focus_prompt: str | None = None,
    sample_file_uids: list[str] | None = None,
    theme_tree_node_id: int | None = None,
    teaching_unit_ids: list[int] | None = None,
) -> ExamGenerationResult:
    started_at = perf_counter()
    raw_mode = exam_mode.value if isinstance(exam_mode, ExamMode) else str(exam_mode or "")
    mode = _resolve_generate_mode(exam_mode)
    runtime_job_id = _new_runtime_job_id()
    created_at = utcnow()
    build_session_id = f"exam_generate_{runtime_job_id}"
    lock = await _acquire_exam_generate_lock(subject=subject, user_id=user_id)

    try:
        snapshot = exams_repo.get_published_curriculum_version(session, subject)
        if snapshot is None:
            raise NoPublishedCurriculumSnapshotError(subject)

        style_profile_started_at = perf_counter()
        style_profile = build_exam_style_profile(
            session,
            subject=subject,
            user_id=user_id,
            sample_file_uids=sample_file_uids,
            style_prompt=style_prompt,
            focus_prompt=focus_prompt,
            user_prompt=user_prompt,
            difficulty=difficulty,
            exam_mode=mode,
        )
        style_profile_ms = _elapsed_ms(style_profile_started_at)
        prompt_requested_count = _extract_requested_question_count(user_prompt)
        resolved_num_questions = (
            prompt_requested_count
            or (int(num_questions) if num_questions is not None else None)
            or style_profile.recommended_question_count
            or _choose_default_question_count(mode)
        )
        preferred_question_types = _choose_preferred_question_types(mode, user_prompt, style_profile)
        build_unit_ids = _resolve_auto_build_unit_ids(
            session,
            subject=subject,
            teaching_unit_ids=teaching_unit_ids,
        )
        if not build_unit_ids:
            _raise_conflict(
                "当前学科没有可用教学单元，无法自动构题。",
                error_code="EXAM_GENERATE_NO_TEACHING_UNITS",
            )

        questions_per_unit = _estimate_questions_per_unit(
            num_questions=max(1, int(resolved_num_questions)),
            unit_count=len(build_unit_ids),
            mode=mode,
        )
        if not teaching_unit_ids:
            build_unit_ids = _prioritize_build_unit_ids(
                session,
                subject=subject,
                user_id=user_id,
                candidate_unit_ids=build_unit_ids,
                mode=mode,
                required_question_count=max(1, int(resolved_num_questions)),
                questions_per_unit=questions_per_unit,
                style_profile=style_profile,
            )
        required_template_count = max(1, int(resolved_num_questions))
        force_contextual_build = bool(
            (style_prompt or "").strip()
            or (focus_prompt or "").strip()
            or (sample_file_uids or [])
        )
        build_job: QuestionBuildResult | None = None
        question_build_ms = 0
        assemble_paper_ms = 0
        template_count_difficulty = _resolve_template_count_difficulty(style_profile.difficulty_focus)

        with llm_trace_scope(
            subject=subject,
            build_session_id=build_session_id,
            workflow="examine.generate",
            lane="generation",
            node="trigger_exam_generate",
        ):
            template_count_before = exams_repo.count_active_question_templates(
                session,
                subject=subject,
                question_types=set(preferred_question_types) if preferred_question_types else None,
                difficulty=template_count_difficulty,
            )
            if force_contextual_build or template_count_before < required_template_count:
                question_build_started_at = perf_counter()
                build_job = await trigger_question_build(
                    session,
                    subject=subject,
                    user_id=user_id,
                    unit_ids=build_unit_ids,
                    questions_per_unit=questions_per_unit,
                    exam_mode=mode,
                    preferred_question_types=preferred_question_types,
                    user_prompt=user_prompt,
                    focus_prompt=focus_prompt,
                    style_profile=style_profile,
                )
                question_build_ms = _elapsed_ms(question_build_started_at)
            else:
                logger.info(
                    "exam_generate_skip_question_build",
                    runtime_job_id=runtime_job_id,
                    subject=subject,
                    user_id=user_id,
                    template_count=template_count_before,
                    required_template_count=required_template_count,
                )

            template_count = exams_repo.count_active_question_templates(
                session,
                subject=subject,
                question_types=set(preferred_question_types) if preferred_question_types else None,
                difficulty=template_count_difficulty,
            )
            if template_count <= 0 and build_job is not None and build_job.status == "failed":
                raise ValueError(build_job.error_message or "自动构题失败，且没有可用题模板。")
            if template_count <= 0:
                raise ValueError("自动构题后仍没有可用题模板。")

            assemble_paper_started_at = perf_counter()
            paper = assemble_paper(
                session,
                subject=subject,
                user_id=user_id,
                exam_mode=mode,
                num_questions=max(1, int(resolved_num_questions)),
                theme_tree_node_id=theme_tree_node_id,
                teaching_unit_ids=(teaching_unit_ids or (build_unit_ids if is_web_practice_mode(mode) else None)),
                preferred_question_types=preferred_question_types,
                preferred_difficulty=style_profile.difficulty_focus,
                style_profile=style_profile,
                user_prompt=user_prompt,
                focus_prompt=focus_prompt,
                sample_file_uids=sample_file_uids or [],
            )
            assemble_paper_ms = _elapsed_ms(assemble_paper_started_at)
            export_ms = 0
            if is_paper_exam_mode(mode):
                export_started_at = perf_counter()
                export_result = export_exam_paper_artifacts(
                    session,
                    paper=paper,
                    compile_pdf=False,
                )
                export_context = _parse_json_object(paper.selection_context_json)
                export_payload = export_result.model_dump()
                export_payload["pdf_compile_status"] = "pending"
                export_context["export_artifacts"] = export_payload
                paper.selection_context_json = json.dumps(export_context, ensure_ascii=False)
                paper.updated_at = utcnow()
                session.add(paper)
                session.commit()
                session.refresh(paper)
                export_ms = _elapsed_ms(export_started_at)
                logger.info(
                    "exam_generate_paper_export_staged",
                    runtime_job_id=runtime_job_id,
                    subject=subject,
                    user_id=user_id,
                    exam_paper_id=paper.id,
                    markdown_path=export_result.markdown_path,
                    tex_path=export_result.tex_path,
                    export_ms=export_ms,
                )
                if export_result.tex_path and paper.id is not None:
                    compile_task = asyncio.create_task(
                        _compile_paper_export_async(
                            exam_paper_id=int(paper.id),
                            tex_path=export_result.tex_path,
                            runtime_job_id=runtime_job_id,
                            subject=subject,
                            user_id=user_id,
                        )
                    )
                    _track_background_task(compile_task)

        updated_at = utcnow()
        logger.info(
            "exam_generate_timing_summary",
            runtime_job_id=runtime_job_id,
            subject=subject,
            user_id=user_id,
            raw_exam_mode=raw_mode,
            exam_mode=mode,
            workflow_elapsed_ms=_elapsed_ms(started_at),
            style_profile_ms=style_profile_ms,
            question_build_ms=question_build_ms,
            assemble_paper_ms=assemble_paper_ms,
            paper_export_ms=(export_ms if is_paper_exam_mode(mode) else 0),
            question_build_triggered=build_job is not None,
            question_build_status=(build_job.status if build_job is not None else "skipped"),
        )
        logger.info(
            "exam_generate_completed",
            runtime_job_id=runtime_job_id,
            subject=subject,
            user_id=user_id,
            exam_paper_id=paper.id,
            exam_mode=mode,
            num_questions=resolved_num_questions,
            teaching_unit_count=len(build_unit_ids),
            sample_file_count=len(sample_file_uids or []),
            user_prompt_present=bool((user_prompt or "").strip()),
            style_prompt_present=bool((style_prompt or "").strip()),
            focus_prompt_present=bool((focus_prompt or "").strip()),
            difficulty_focus=style_profile.difficulty_focus,
            build_unit_ids=build_unit_ids,
        )
        return ExamGenerationResult(
            id=runtime_job_id,
            status="completed",
            error_message=None,
            created_at=created_at,
            updated_at=updated_at,
            subject=subject,
            user_id=user_id,
            exam_mode=mode,
            num_questions=max(1, int(resolved_num_questions)),
            exam_paper_id=paper.id,
            theme_tree_node_id=theme_tree_node_id,
            teaching_unit_ids_json=json.dumps(build_unit_ids, ensure_ascii=False),
            sample_file_uids_json=json.dumps(sample_file_uids or [], ensure_ascii=False),
        )
    finally:
        lock.release()


async def submit_exam_answers(
    session: Session,
    *,
    subject: str,
    exam_paper_id: int,
    user_id: str,
    answers: dict[int | str, str],
) -> ExamPaper:
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != subject:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")
    if paper.user_id != user_id:
        _raise_conflict(
            f"用户 `{user_id}` 无权提交试卷 `{exam_paper_id}`。",
            error_code="EXAM_PAPER_USER_MISMATCH",
        )

    if paper.status in {"submitted", "grading", "graded"}:
        _raise_conflict(
            f"试卷 `{exam_paper_id}` 当前状态 `{paper.status}`，不允许重复提交。",
            error_code="EXAM_ALREADY_SUBMITTED",
        )
    if paper.status not in {"ready", "in_progress"}:
        _raise_conflict(
            f"试卷 `{exam_paper_id}` 当前状态 `{paper.status}`，不可提交。",
            error_code="INVALID_EXAM_PAPER_STATUS",
        )

    items = list(
        session.exec(
            select(ExamPaperItem).where(ExamPaperItem.exam_paper_id == exam_paper_id).order_by(ExamPaperItem.item_order)
        ).all()
    )
    answer_map = _normalize_answers_payload(answers=answers)

    if paper.status == "ready":
        validate_status_transition(ExamPaperStatus.READY, ExamPaperStatus.IN_PROGRESS)
        paper.status = "in_progress"

    validate_status_transition(ExamPaperStatus.IN_PROGRESS, ExamPaperStatus.SUBMITTED)

    for item in items:
        if item.id is None:
            continue
        answer_text = answer_map.get(item.id)
        if answer_text is None:
            answer_text = answer_map.get(item.item_order, "")
        item.answer_content = answer_text
        item.answered_at = utcnow()
        item.updated_at = utcnow()
        session.add(item)

    paper.status = "submitted"
    paper.submitted_at = utcnow()
    duration_seconds = seconds_between(paper.submitted_at, paper.created_at)
    if duration_seconds is not None:
        paper.duration_seconds = duration_seconds
    paper.updated_at = utcnow()
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def _reset_attempts_for_regrade(session: Session, exam_paper_id: int) -> None:
    items = exams_repo.list_items_by_paper(session, exam_paper_id)
    for item in items:
        item.is_correct = None
        item.score_obtained = None
        item.score_max = None
        item.error_cause_label = None
        item.feedback_text = None
        item.graded_at = None
        item.updated_at = utcnow()
        session.add(item)
    session.commit()


async def trigger_exam_grade(
    session: Session,
    *,
    exam_paper_id: int,
    regrade: bool = False,
) -> ExamGradingResult:
    started_at = perf_counter()
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")
    runtime_job_id = _new_runtime_job_id()
    created_at = utcnow()
    build_session_id = f"exam_grade_{runtime_job_id}"

    if paper.status == "graded":
        if not regrade:
            _raise_conflict(
                f"试卷 `{exam_paper_id}` 已判分，需传 `regrade=true` 才可重判。",
                error_code="EXAM_ALREADY_GRADED",
            )
        _reset_attempts_for_regrade(session, exam_paper_id)
        paper.status = "submitted"
        paper.graded_at = None
        paper.updated_at = utcnow()
        session.add(paper)
        session.commit()
        session.refresh(paper)

    if paper.status != "submitted":
        _raise_conflict(
            f"试卷 `{exam_paper_id}` 当前状态 `{paper.status}`，仅 submitted 可触发判卷。",
            error_code="INVALID_EXAM_PAPER_STATUS",
        )

    try:
        validate_status_transition(ExamPaperStatus.SUBMITTED, ExamPaperStatus.GRADING)
        paper.status = ExamPaperStatus.GRADING.value
        paper.updated_at = utcnow()
        session.add(paper)
        session.commit()
        session.refresh(paper)

        grade_started_at = perf_counter()
        with llm_trace_scope(
            subject=paper.subject,
            build_session_id=build_session_id,
            workflow="examine.grade",
            lane="grading",
            node="grade_paper",
        ):
            grade_result = await grade_paper(
                session,
                exam_paper_id,
                auto_commit=False,
            )
        grade_paper_ms = _elapsed_ms(grade_started_at)

        states_updated = 0
        tasks_created = 0
        mastery_consumed = False
        mastery_update_ms = 0
        review_schedule_ms = 0
        subject_profile_refresh_ms = 0
        user_profile_refresh_ms = 0
        if not regrade:
            mastery_started_at = perf_counter()
            mastery_result = update_mastery_from_exam(
                session,
                exam_paper_id,
                auto_commit=False,
            )
            mastery_update_ms = _elapsed_ms(mastery_started_at)
            states_updated = mastery_result.states_updated
            review_started_at = perf_counter()
            review_tasks = schedule_reviews(
                session,
                user_id=paper.user_id,
                subject=paper.subject,
                updated_state_ids=mastery_result.updated_state_ids,
                auto_commit=False,
            )
            review_schedule_ms = _elapsed_ms(review_started_at)
            tasks_created = len(review_tasks)
            subject_profile_started_at = perf_counter()
            refresh_subject_profile_summary(
                session,
                subject=paper.subject,
                auto_commit=False,
            )
            subject_profile_refresh_ms = _elapsed_ms(subject_profile_started_at)
            user_profile_started_at = perf_counter()
            refresh_user_profile_summary(
                session,
                user_id=paper.user_id,
                auto_commit=False,
            )
            user_profile_refresh_ms = _elapsed_ms(user_profile_started_at)
            mastery_consumed = True
        else:
            logger.info(
                "exam_grade_regrade_skip_mastery",
                runtime_job_id=runtime_job_id,
                exam_paper_id=exam_paper_id,
            )

        session.commit()
        updated_at = utcnow()
        try:
            await _sync_exam_learning_memory(
                paper=paper,
                score_percent=float(grade_result.score),
                correct_count=int(grade_result.correct_items),
                total_count=int(grade_result.total_items),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "exam_grade_learning_memory_sync_failed",
                runtime_job_id=runtime_job_id,
                exam_paper_id=exam_paper_id,
                error=str(exc),
            )
        logger.info(
            "exam_grade_timing_summary",
            runtime_job_id=runtime_job_id,
            exam_paper_id=exam_paper_id,
            workflow_elapsed_ms=_elapsed_ms(started_at),
            grade_paper_ms=grade_paper_ms,
            mastery_update_ms=mastery_update_ms,
            review_schedule_ms=review_schedule_ms,
            subject_profile_refresh_ms=subject_profile_refresh_ms,
            user_profile_refresh_ms=user_profile_refresh_ms,
            regrade=regrade,
        )
        logger.info(
            "exam_grade_completed",
            runtime_job_id=runtime_job_id,
            exam_paper_id=exam_paper_id,
            score=grade_result.score,
            states_updated=states_updated,
            tasks_created=tasks_created,
            mastery_consumed=mastery_consumed,
        )
        return ExamGradingResult(
            id=runtime_job_id,
            status="completed",
            error_message=None,
            created_at=created_at,
            updated_at=updated_at,
            exam_paper_id=exam_paper_id,
            score=float(grade_result.score),
            states_updated=states_updated,
            tasks_created=tasks_created,
            mastery_consumed=mastery_consumed,
        )
    except Exception:
        session.rollback()
        latest_paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
        if latest_paper is not None and latest_paper.status == ExamPaperStatus.GRADING.value:
            latest_paper.status = ExamPaperStatus.SUBMITTED.value
            latest_paper.updated_at = utcnow()
            session.add(latest_paper)
            session.commit()
        logger.error(
            "exam_grade_failed",
            runtime_job_id=runtime_job_id,
            exam_paper_id=exam_paper_id,
            exc_info=True,
        )
        raise


async def get_exam_history(
    session: Session,
    *,
    subject: str,
    user_id: str,
    page: int,
    size: int,
) -> PaginatedData[ExamPaper]:
    rows, total = exams_repo.list_exam_papers(
        session,
        subject=subject,
        user_id=user_id,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(items=rows, page=page, size=size, total=total)


async def get_question_bank(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> list[QuestionBankItem]:
    rows = exams_repo.list_exam_item_snapshots_by_user(
        session,
        subject=subject,
        user_id=user_id,
    )
    agg: dict[int, QuestionBankItem] = {}
    style_summary_by_template: dict[int, str | None] = {}
    knowledge_points_by_template: dict[int, list[str]] = {}

    template_ids = list({int(item.question_template_id) for item, _, _ in rows if item.question_template_id is not None})
    if template_ids:
        templates = list(session.exec(select(QuestionTemplate).where(QuestionTemplate.id.in_(template_ids))).all())
        style_summary_by_template = {
            int(template.id): _summarize_style_hint(template.selection_hints_json)
            for template in templates
            if template.id is not None
        }
        knowledge_points_by_template = _resolve_template_knowledge_points(session, template_ids=template_ids)

    for item, asked_at, exam_paper_id in rows:
        template_id = int(item.question_template_id)
        existing = agg.get(template_id)
        if existing is None:
            agg[template_id] = QuestionBankItem(
                question_template_id=template_id,
                stem=item.stem_snapshot,
                question_type=item.question_type,
                difficulty=item.difficulty,
                teaching_unit_id=item.teaching_unit_id,
                times_asked=1,
                last_asked_at=asked_at,
                last_exam_paper_id=exam_paper_id,
                knowledge_points=knowledge_points_by_template.get(template_id, []),
                style_summary=style_summary_by_template.get(template_id),
            )
            continue

        latest_time = existing.last_asked_at
        latest_paper_id = existing.last_exam_paper_id
        if asked_at > existing.last_asked_at:
            latest_time = asked_at
            latest_paper_id = exam_paper_id
        agg[template_id] = QuestionBankItem(
            question_template_id=existing.question_template_id,
            stem=existing.stem,
            question_type=existing.question_type,
            difficulty=existing.difficulty,
            teaching_unit_id=existing.teaching_unit_id,
            times_asked=existing.times_asked + 1,
            last_asked_at=latest_time,
            last_exam_paper_id=latest_paper_id,
            knowledge_points=existing.knowledge_points,
            style_summary=existing.style_summary,
        )
    return sorted(agg.values(), key=lambda item: item.last_asked_at, reverse=True)


async def delete_exam_paper(
    session: Session,
    *,
    subject: str,
    user_id: str,
    exam_paper_id: int,
) -> None:
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != subject or paper.user_id != user_id:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")

    deleted = exams_repo.delete_exam_paper_cascade(session, paper_id=exam_paper_id)
    if not deleted:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")


async def get_exam_paper_detail(
    session: Session,
    *,
    subject: str,
    user_id: str,
    exam_paper_id: int,
) -> ExamPaperDetail:
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != subject or paper.user_id != user_id:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")

    items = list(
        session.exec(
            select(ExamPaperItem)
            .where(ExamPaperItem.exam_paper_id == exam_paper_id)
            .order_by(ExamPaperItem.item_order)
        ).all()
    )
    attempts_by_item_id: dict[int, ExamPaperItem] = {}
    for item in items:
        if item.id is None:
            continue
        if not (item.answer_content or item.is_correct is not None):
            continue
        attempts_by_item_id[item.id] = item

    return ExamPaperDetail(paper=paper, items=items, attempts_by_item_id=attempts_by_item_id)
