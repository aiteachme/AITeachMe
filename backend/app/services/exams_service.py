"""Exam domain service layer."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus

import structlog
from sqlmodel import Session, select

from app.core.exceptions import AITeachMeError, NoPublishedCurriculumSnapshotError
from app.models import (
    ExamMode,
    ExamPaper,
    ExamPaperItem,
    ExamPaperStatus,
    QuestionType,
    UserAnswerAttempt,
    validate_status_transition,
)
from app.repositories import exams_repo
from app.schemas.common import PaginatedData, build_paginated_data
from app.utils.time import utcnow
from app.workflows.examine.answer_grader import grade_paper
from app.workflows.examine.paper_assembler import assemble_paper
from app.workflows.examine.question_build_workflow import QuestionBuildWorkflow
from app.workflows.profile.mastery_updater import update_mastery_from_exam
from app.workflows.profile.review_scheduler import schedule_reviews

logger = structlog.get_logger()


@dataclass(frozen=True)
class ExamPaperDetail:
    paper: ExamPaper
    items: list[ExamPaperItem]
    attempts_by_item_id: dict[int, UserAnswerAttempt]


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
class ExamGenerateResult:
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


@dataclass(frozen=True)
class ExamGradeResult:
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


def _new_runtime_job_id() -> int:
    return (int(utcnow().timestamp() * 1_000_000) % 2_000_000_000) + 1


async def _acquire_exam_generate_lock(*, subject: str, user_id: str) -> asyncio.Lock:
    key = (subject, user_id)
    async with _exam_generate_locks_guard:
        lock = _exam_generate_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _exam_generate_locks[key] = lock

    if lock.locked():
        _raise_conflict(
            "当前已有试卷生成任务进行中，请稍候再试。",
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
        ExamMode.DIAGNOSTIC.value: 12,
        ExamMode.PRACTICE.value: 10,
        ExamMode.WEAKPOINT_BOOST.value: 10,
        ExamMode.REVIEW.value: 8,
        ExamMode.MOCK_FINAL.value: 20,
    }
    return defaults.get(mode, 10)


def _choose_preferred_question_types(mode: str, user_prompt: str | None) -> list[str]:
    prompt = (user_prompt or "").lower()
    picked: list[str] = []
    if any(key in prompt for key in ["选择", "单选", "choice", "mcq"]):
        picked.append(QuestionType.SINGLE_CHOICE.value)
    if any(key in prompt for key in ["填空", "blank"]):
        picked.append(QuestionType.FILL_BLANK.value)
    if any(key in prompt for key in ["简答", "问答", "解答", "分析", "证明", "essay"]):
        picked.append(QuestionType.SHORT_ANSWER.value)

    if picked:
        return list(dict.fromkeys(picked))

    defaults_by_mode = {
        ExamMode.DIAGNOSTIC.value: [
            QuestionType.SINGLE_CHOICE.value,
            QuestionType.FILL_BLANK.value,
            QuestionType.SHORT_ANSWER.value,
        ],
        ExamMode.PRACTICE.value: [
            QuestionType.SINGLE_CHOICE.value,
            QuestionType.FILL_BLANK.value,
        ],
        ExamMode.WEAKPOINT_BOOST.value: [
            QuestionType.SINGLE_CHOICE.value,
            QuestionType.SHORT_ANSWER.value,
        ],
        ExamMode.REVIEW.value: [QuestionType.SINGLE_CHOICE.value],
        ExamMode.MOCK_FINAL.value: [
            QuestionType.SINGLE_CHOICE.value,
            QuestionType.FILL_BLANK.value,
            QuestionType.SHORT_ANSWER.value,
        ],
    }
    return defaults_by_mode.get(
        mode,
        [QuestionType.SINGLE_CHOICE.value, QuestionType.FILL_BLANK.value],
    )


def _estimate_questions_per_unit(*, num_questions: int, unit_count: int, mode: str) -> int:
    if unit_count <= 0:
        return 3
    spread_units = max(1, min(unit_count, 8))
    baseline = (num_questions + spread_units - 1) // spread_units
    if mode == ExamMode.MOCK_FINAL.value:
        baseline = max(baseline, 4)
    return max(2, min(10, baseline))


def _resolve_generate_mode(exam_mode: ExamMode | str) -> str:
    if isinstance(exam_mode, ExamMode):
        return exam_mode.value
    return str(exam_mode).strip().lower()


async def trigger_question_build(
    session: Session,
    *,
    subject: str,
    unit_ids: list[int],
    questions_per_unit: int,
) -> QuestionBuildResult:
    runtime_job_id = _new_runtime_job_id()
    created_at = utcnow()
    resolved_questions_per_unit = max(1, int(questions_per_unit))

    try:
        state = await QuestionBuildWorkflow.run(
            subject=subject,
            unit_ids=unit_ids,
            questions_per_unit=resolved_questions_per_unit,
            job_id=runtime_job_id,
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


async def get_question_build_job_status(
    session: Session,
    *,
    subject: str,
    job_id: int,
) -> QuestionBuildResult:
    del session, subject
    _raise_not_found(
        f"题库构建任务 `{job_id}` 不存在（QuestionBuildJob 已移除）。",
        error_code="QUESTION_BUILD_JOB_NOT_FOUND",
    )


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

    all_ids = exams_repo.list_teaching_unit_ids_by_subject(
        session,
        subject=subject,
        status=None,
    )
    return all_ids


async def trigger_exam_generate(
    session: Session,
    *,
    subject: str,
    user_id: str,
    exam_mode: ExamMode | str,
    num_questions: int | None = None,
    user_prompt: str | None = None,
    theme_tree_node_id: int | None = None,
    teaching_unit_ids: list[int] | None = None,
) -> ExamGenerateResult:
    mode = _resolve_generate_mode(exam_mode)
    prompt_requested_count = _extract_requested_question_count(user_prompt)
    resolved_num_questions = (
        prompt_requested_count
        or (int(num_questions) if num_questions is not None else None)
        or _choose_default_question_count(mode)
    )
    preferred_question_types = _choose_preferred_question_types(mode, user_prompt)
    runtime_job_id = _new_runtime_job_id()
    created_at = utcnow()
    lock = await _acquire_exam_generate_lock(subject=subject, user_id=user_id)
    try:
        build_unit_ids = _resolve_auto_build_unit_ids(
            session,
            subject=subject,
            teaching_unit_ids=teaching_unit_ids,
        )
        questions_per_unit = _estimate_questions_per_unit(
            num_questions=resolved_num_questions,
            unit_count=len(build_unit_ids),
            mode=mode,
        )

        snapshot = exams_repo.get_published_curriculum_snapshot(session, subject)
        if snapshot is None:
            raise NoPublishedCurriculumSnapshotError(subject)
        if not build_unit_ids:
            _raise_conflict(
                "当前学科没有可用教学单元，无法自动构题。",
                error_code="EXAM_GENERATE_NO_TEACHING_UNITS",
            )

        required_template_count = max(1, int(resolved_num_questions))
        build_job: QuestionBuildResult | None = None
        template_count_before = exams_repo.count_active_question_templates(
            session,
            subject=subject,
            question_types=set(preferred_question_types) if preferred_question_types else None,
        )
        if template_count_before < required_template_count:
            build_job = await trigger_question_build(
                session,
                subject=subject,
                unit_ids=build_unit_ids,
                questions_per_unit=questions_per_unit,
            )
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
        )
        if template_count <= 0 and build_job is not None and build_job.status == "failed":
            raise ValueError(build_job.error_message or "自动构题失败，且没有可用题模板。")
        if template_count <= 0:
            raise ValueError("自动构题后仍没有可用题模板。")

        paper = assemble_paper(
            session,
            subject=subject,
            user_id=user_id,
            exam_mode=mode,
            num_questions=max(1, int(resolved_num_questions)),
            theme_tree_node_id=theme_tree_node_id,
            teaching_unit_ids=(build_unit_ids if mode == ExamMode.PRACTICE.value else teaching_unit_ids),
            preferred_question_types=preferred_question_types,
        )
        updated_at = utcnow()

        logger.info(
            "exam_generate_completed",
            runtime_job_id=runtime_job_id,
            subject=subject,
            user_id=user_id,
            exam_paper_id=paper.id,
            exam_mode=mode,
            num_questions=resolved_num_questions,
            teaching_unit_count=len(build_unit_ids),
            user_prompt_present=bool((user_prompt or "").strip()),
        )
        return ExamGenerateResult(
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
            teaching_unit_ids_json=json.dumps(build_unit_ids),
        )
    finally:
        lock.release()


async def get_exam_generate_job_status(
    session: Session,
    *,
    subject: str,
    job_id: int,
    user_id: str,
) -> ExamGenerateResult:
    del session, subject, user_id
    _raise_not_found(
        f"组卷任务 `{job_id}` 不存在（ExamGenerateJob 已移除）。",
        error_code="EXAM_GENERATE_JOB_NOT_FOUND",
    )


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

    attempts: list[UserAnswerAttempt] = []
    for item in items:
        if item.id is None:
            continue
        answer_text = answer_map.get(item.id)
        if answer_text is None:
            answer_text = answer_map.get(item.item_order, "")
        attempts.append(
            UserAnswerAttempt(
                exam_paper_item_id=item.id,
                user_id=user_id,
                attempt_no=1,
                user_answer=answer_text,
                created_at=utcnow(),
            )
        )

    if attempts:
        exams_repo.create_answer_attempts(session, attempts)

    paper.status = "submitted"
    paper.submitted_at = utcnow()
    paper.updated_at = utcnow()
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def _reset_attempts_for_regrade(session: Session, exam_paper_id: int) -> None:
    attempts = exams_repo.list_attempts_by_paper(session, exam_paper_id)
    for attempt in attempts:
        attempt.is_correct = None
        attempt.score_obtained = None
        attempt.score_max = None
        attempt.error_cause_label = None
        session.add(attempt)
    session.commit()


async def trigger_exam_grade(
    session: Session,
    *,
    exam_paper_id: int,
    regrade: bool = False,
) -> ExamGradeResult:
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")
    runtime_job_id = _new_runtime_job_id()
    created_at = utcnow()

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

        grade_result = await grade_paper(session, exam_paper_id)

        states_updated = 0
        tasks_created = 0
        mastery_consumed = bool(regrade)
        if not regrade:
            mastery_result = update_mastery_from_exam(session, exam_paper_id)
            states_updated = mastery_result.states_updated
            review_tasks = schedule_reviews(
                session,
                user_id=paper.user_id,
                subject=paper.subject,
                updated_state_ids=mastery_result.updated_state_ids,
            )
            tasks_created = len(review_tasks)
        else:
            logger.info(
                "exam_grade_regrade_skip_mastery",
                runtime_job_id=runtime_job_id,
                exam_paper_id=exam_paper_id,
            )

        updated_at = utcnow()
        logger.info(
            "exam_grade_completed",
            runtime_job_id=runtime_job_id,
            exam_paper_id=exam_paper_id,
            score=grade_result.score,
            states_updated=states_updated,
            tasks_created=tasks_created,
            mastery_consumed=mastery_consumed,
        )
        return ExamGradeResult(
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


async def get_exam_grade_job_status(
    session: Session,
    *,
    subject: str,
    job_id: int,
    user_id: str,
) -> ExamGradeResult:
    del session, subject, user_id
    _raise_not_found(
        f"判卷任务 `{job_id}` 不存在（ExamGradeJob 已移除）。",
        error_code="EXAM_GRADE_JOB_NOT_FOUND",
    )


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
    for item, asked_at, exam_paper_id in rows:
        template_id = int(item.question_template_id)
        existing = agg.get(template_id)
        if existing is None:
            agg[template_id] = QuestionBankItem(
                question_template_id=template_id,
                stem=item.snapshot_stem,
                question_type=item.snapshot_question_type,
                difficulty=item.snapshot_difficulty,
                teaching_unit_id=item.snapshot_teaching_unit_id,
                times_asked=1,
                last_asked_at=asked_at,
                last_exam_paper_id=exam_paper_id,
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
    attempts = exams_repo.list_attempts_by_paper(session, exam_paper_id)
    attempts_by_item_id: dict[int, UserAnswerAttempt] = {}
    for attempt in attempts:
        current = attempts_by_item_id.get(attempt.exam_paper_item_id)
        if current is None or attempt.attempt_no > current.attempt_no:
            attempts_by_item_id[attempt.exam_paper_item_id] = attempt

    return ExamPaperDetail(paper=paper, items=items, attempts_by_item_id=attempts_by_item_id)
