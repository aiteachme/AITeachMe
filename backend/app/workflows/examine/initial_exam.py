"""Durable orchestration for a course's one automatic initial exam."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

import structlog

from app.models import Course
from app.repositories import initial_exam_repo
from app.repositories import exams_repo
from app.shared.infra.database import managed_session
from app.shared.infra.llm_support.model_choices import (
    normalize_runtime_model_override,
    use_runtime_model_override,
)
from app.utils.time import utcnow

logger = structlog.get_logger(__name__)

INITIAL_EXAM_LEASE_DURATION = timedelta(minutes=30)
INITIAL_EXAM_LEASE_HEARTBEAT_SECONDS = 60.0
INITIAL_EXAM_RECOVERY_INTERVAL_SECONDS = 30.0
INITIAL_EXAM_RETRY_DELAY = timedelta(seconds=30)
INITIAL_EXAM_MAX_ATTEMPTS = 6


def ensure_course_initial_exam_job(
    *,
    course_id: str,
    user_id: str | None = None,
    build_session_id: str = "",
    model_override: str | None = None,
) -> bool:
    """Persist the one-per-course marker and return whether it is runnable."""

    with managed_session() as session:
        course = session.get(Course, course_id)
        if course is None:
            return False
        owner_user_id = user_id or course.user_id
        if owner_user_id != course.user_id:
            return False
        job = initial_exam_repo.ensure_course_initial_exam_job(
            session,
            course_id=course_id,
            user_id=owner_user_id,
            build_session_id=build_session_id,
            model_override=normalize_runtime_model_override(model_override) or "",
            auto_commit=True,
        )
        return job.status in {"pending", "retry_wait", "processing"}


async def _renew_initial_exam_lease_loop(*, course_id: str, claim_token: str) -> None:
    while True:
        await asyncio.sleep(INITIAL_EXAM_LEASE_HEARTBEAT_SECONDS)
        try:
            with managed_session() as session:
                renewed = initial_exam_repo.renew_course_initial_exam_job_lease(
                    session,
                    course_id=course_id,
                    claim_token=claim_token,
                    lease_expires_at=utcnow() + INITIAL_EXAM_LEASE_DURATION,
                )
        except Exception as exc:
            logger.warning(
                "course_initial_exam_lease_renewal_failed",
                course_id=course_id,
                error_type=type(exc).__name__,
            )
            continue
        if not renewed:
            return


async def run_course_initial_exam_job(
    *,
    course_id: str,
    user_id: str | None = None,
    build_session_id: str = "",
    model_override: str | None = None,
) -> None:
    """Claim and complete the course's single automatic-exam job."""

    if not ensure_course_initial_exam_job(
        course_id=course_id,
        user_id=user_id,
        build_session_id=build_session_id,
        model_override=model_override,
    ):
        return

    with managed_session() as session:
        course = session.get(Course, course_id)
        if course is None:
            return
        owner_user_id = user_id or course.user_id
        job = initial_exam_repo.get_course_initial_exam_job(session, course_id=course_id)
        resolved_model_override = normalize_runtime_model_override(job.model_override if job is not None else None)
    claim_token = uuid.uuid4().hex
    claimed_at = utcnow()
    with managed_session() as session:
        claimed = initial_exam_repo.claim_course_initial_exam_job(
            session,
            course_id=course_id,
            claim_token=claim_token,
            claimed_at=claimed_at,
            lease_expires_at=claimed_at + INITIAL_EXAM_LEASE_DURATION,
        )
    if not claimed:
        return

    heartbeat = asyncio.create_task(
        _renew_initial_exam_lease_loop(course_id=course_id, claim_token=claim_token),
        name=f"exam.initial.heartbeat:{course_id}",
    )
    paper_id: int | None = None
    try:
        from app.api.exams import _run_initial_exam_from_published_docs_background
        from app.workflows.examine.prewarm import trigger_default_exam_prewarm_for_course

        with use_runtime_model_override(resolved_model_override):
            result = await trigger_default_exam_prewarm_for_course(
                course_id=course_id,
                user_id=owner_user_id,
                wait_for_units_timeout_s=0.0,
            )
            paper_id = result.exam_paper_id
            if result.reason == "no_active_knowledge_units":
                paper_id = await _run_initial_exam_from_published_docs_background(
                    course_id=course_id,
                    user_id=owner_user_id,
                )

        with managed_session() as session:
            paper = exams_repo.get_exam_paper_by_id(session, int(paper_id or 0)) if paper_id else None
            job = initial_exam_repo.get_course_initial_exam_job(session, course_id=course_id)
            attempt_count = int(job.attempt_count or 1) if job is not None else 1
            if paper is not None and paper.status in {"ready", "submitted", "grading", "graded"}:
                finalized = initial_exam_repo.finalize_course_initial_exam_job(
                    session,
                    course_id=course_id,
                    claim_token=claim_token,
                    exam_paper_id=int(paper.id or 0),
                    completed_at=utcnow(),
                )
                if not finalized:
                    logger.warning("course_initial_exam_claim_lost", course_id=course_id)
                    return
                logger.info(
                    "course_initial_exam_completed",
                    course_id=course_id,
                    user_id=owner_user_id,
                    paper_id=int(paper.id or 0),
                    source=str(result.reason or result.status),
                )
                return

            if paper is not None and paper.status == "generating":
                initial_exam_repo.release_course_initial_exam_job(
                    session,
                    course_id=course_id,
                    claim_token=claim_token,
                    status="retry_wait",
                    next_attempt_at=utcnow() + INITIAL_EXAM_RETRY_DELAY,
                    error_code="initial_exam_still_generating",
                    exam_paper_id=int(paper.id or 0),
                )
                return

            terminal = attempt_count >= INITIAL_EXAM_MAX_ATTEMPTS
            failed_paper_id = int(paper.id or 0) if paper is not None else None
            if failed_paper_id is not None and not terminal:
                # Failed attempts belong to this internal job. Remove them before
                # retrying so users still see exactly one automatic quiz rather
                # than a trail of failed placeholders.
                exams_repo.delete_exam_paper_cascade(session, paper_id=failed_paper_id)
            initial_exam_repo.release_course_initial_exam_job(
                session,
                course_id=course_id,
                claim_token=claim_token,
                status="failed" if terminal else "retry_wait",
                next_attempt_at=None if terminal else utcnow() + INITIAL_EXAM_RETRY_DELAY,
                error_code=(
                    "initial_exam_generation_failed"
                    if paper is not None
                    else "initial_exam_source_not_ready"
                ),
                exam_paper_id=failed_paper_id if terminal else None,
            )
    except asyncio.CancelledError:
        with managed_session() as session:
            initial_exam_repo.release_course_initial_exam_job(
                session,
                course_id=course_id,
                claim_token=claim_token,
                status="retry_wait",
                next_attempt_at=utcnow() + INITIAL_EXAM_RETRY_DELAY,
                error_code="initial_exam_worker_cancelled",
                exam_paper_id=paper_id,
            )
        raise
    except Exception as exc:
        with managed_session() as session:
            job = initial_exam_repo.get_course_initial_exam_job(session, course_id=course_id)
            attempt_count = int(job.attempt_count or 1) if job is not None else 1
            terminal = attempt_count >= INITIAL_EXAM_MAX_ATTEMPTS
            initial_exam_repo.release_course_initial_exam_job(
                session,
                course_id=course_id,
                claim_token=claim_token,
                status="failed" if terminal else "retry_wait",
                next_attempt_at=None if terminal else utcnow() + INITIAL_EXAM_RETRY_DELAY,
                error_code=type(exc).__name__,
                exam_paper_id=paper_id,
            )
        logger.exception(
            "course_initial_exam_failed",
            course_id=course_id,
            user_id=owner_user_id,
            error_type=type(exc).__name__,
        )
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass


def schedule_course_initial_exam_job(
    background_task_registry,
    *,
    course_id: str,
    user_id: str | None = None,
    build_session_id: str = "",
    model_override: str | None = None,
) -> bool:
    if not ensure_course_initial_exam_job(
        course_id=course_id,
        user_id=user_id,
        build_session_id=build_session_id,
        model_override=model_override,
    ):
        return False
    coro = run_course_initial_exam_job(
        course_id=course_id,
        user_id=user_id,
        build_session_id=build_session_id,
        model_override=model_override,
    )
    if background_task_registry is not None:
        background_task_registry.spawn(
            coro,
            kind="exam.initial",
            course_id=course_id,
            name=f"exam.initial:{course_id}",
            dedupe_key=f"exam.initial:{course_id}",
        )
    else:
        asyncio.create_task(coro, name=f"exam.initial:{course_id}")
    return True


def recover_course_initial_exam_jobs_once(background_task_registry) -> int:
    with managed_session() as session:
        jobs = initial_exam_repo.list_recoverable_course_initial_exam_jobs(session, as_of=utcnow())
        recoverable = [
            (job.course_id, job.user_id, job.build_session_id, job.model_override)
            for job in jobs
        ]
    return sum(
        1
        for course_id, user_id, build_session_id, model_override in recoverable
        if schedule_course_initial_exam_job(
            background_task_registry,
            course_id=course_id,
            user_id=user_id,
            build_session_id=build_session_id,
            model_override=model_override,
        )
    )


async def run_course_initial_exam_recovery_loop(*, task_registry) -> None:
    while True:
        try:
            recover_course_initial_exam_jobs_once(task_registry)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "course_initial_exam_recovery_scan_failed",
                error_type=type(exc).__name__,
            )
        await asyncio.sleep(INITIAL_EXAM_RECOVERY_INTERVAL_SECONDS)


__all__ = [
    "ensure_course_initial_exam_job",
    "recover_course_initial_exam_jobs_once",
    "run_course_initial_exam_job",
    "run_course_initial_exam_recovery_loop",
    "schedule_course_initial_exam_job",
]
