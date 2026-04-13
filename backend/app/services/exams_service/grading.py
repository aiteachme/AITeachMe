"""Exam answer submission and grading logic."""

from __future__ import annotations

from time import perf_counter

import structlog
from sqlmodel import Session, select

from app.models import (
    ExamPaperItem,
    ExamPaperStatus,
    validate_status_transition,
)
from app.repositories import exams_repo
from app.shared.infra.observability import llm_trace_scope
from app.utils.time import seconds_between, utcnow
from app.workflows.examine.answer_grader import grade_paper
from app.workflows.profile.mastery_updater import update_mastery_from_exam
from app.workflows.profile.review_scheduler import schedule_reviews
from app.workflows.profile.subject_profile import refresh_subject_profile_summary
from app.workflows.profile.user_profile import refresh_user_profile_summary

from ._helpers import (
    ExamGradingResult,
    _elapsed_ms,
    _new_runtime_job_id,
    _normalize_answers_payload,
    _raise_conflict,
    _raise_not_found,
    _sync_exam_learning_memory,
)

logger = structlog.get_logger()


async def submit_exam_answers(
    session: Session,
    *,
    subject: str,
    exam_paper_id: int,
    user_id: str,
    answers: dict[int | str, str],
):
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
