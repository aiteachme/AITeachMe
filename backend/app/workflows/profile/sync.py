"""Durable, retryable consumption of graded exams into Profile."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import timedelta

import structlog

from app.repositories import exams_repo
from app.shared.infra.database import managed_session
from app.utils.time import ensure_utc_datetime, utcnow
from app.workflows.profile.update.graph import run_profile_update_workflow

logger = structlog.get_logger(__name__)

PROFILE_SYNC_LEASE_DURATION = timedelta(minutes=10)
PROFILE_SYNC_HEARTBEAT_SECONDS = 60.0
PROFILE_SYNC_RECOVERY_INTERVAL_SECONDS = 30.0
PROFILE_SYNC_MAX_ATTEMPTS = 6
PROFILE_SYNC_RETRY_BASE_SECONDS = 30
PROFILE_SYNC_RETRY_MAX_SECONDS = 6 * 60 * 60


class ProfileSyncExecutionError(RuntimeError):
    def __init__(self, error_code: str) -> None:
        self.error_code = _normalize_profile_sync_error_code(error_code)
        super().__init__(self.error_code)


def _normalize_profile_sync_error_code(value: object) -> str:
    cleaned = str(value or "profile_sync_failed").strip()
    head = cleaned.split(":", 1)[0].strip()
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", head).strip("._-")
    return (normalized or "profile_sync_failed")[:80]


def profile_sync_retry_delay(*, attempt_count: int, paper_id: int) -> timedelta:
    attempt = max(1, int(attempt_count or 0))
    base = min(
        PROFILE_SYNC_RETRY_MAX_SECONDS,
        PROFILE_SYNC_RETRY_BASE_SECONDS * (2 ** min(attempt - 1, 10)),
    )
    jitter = int(paper_id or 0) % 17
    return timedelta(seconds=base + jitter)


def is_exam_profile_sync_recoverable_now(task, *, as_of=None) -> bool:
    now = ensure_utc_datetime(as_of) or utcnow()
    if task.status in {"pending", "retry_wait"}:
        next_attempt_at = ensure_utc_datetime(task.next_attempt_at)
        return next_attempt_at is None or next_attempt_at <= now
    if task.status == "processing":
        lease_expires_at = ensure_utc_datetime(task.lease_expires_at)
        return lease_expires_at is None or lease_expires_at <= now
    return False


async def _renew_exam_profile_sync_lease_loop(*, paper_id: int, claim_token: str) -> None:
    while True:
        await asyncio.sleep(PROFILE_SYNC_HEARTBEAT_SECONDS)
        try:
            with managed_session() as session:
                renewed = exams_repo.renew_exam_profile_sync_lease(
                    session,
                    paper_id=paper_id,
                    claim_token=claim_token,
                    lease_expires_at=utcnow() + PROFILE_SYNC_LEASE_DURATION,
                )
        except Exception as exc:
            logger.warning(
                "exam_profile_sync_lease_renewal_failed",
                paper_id=paper_id,
                error_type=type(exc).__name__,
            )
            continue
        if not renewed:
            return


async def run_exam_profile_sync_background(
    *,
    course_id: str,
    user_id: str,
    paper_id: int,
) -> None:
    claim_token = uuid.uuid4().hex
    claimed_at = utcnow()
    with managed_session() as session:
        claimed = exams_repo.claim_exam_profile_sync(
            session,
            paper_id=paper_id,
            claim_token=claim_token,
            claimed_at=claimed_at,
            lease_expires_at=claimed_at + PROFILE_SYNC_LEASE_DURATION,
        )
    if not claimed:
        return

    heartbeat = asyncio.create_task(
        _renew_exam_profile_sync_lease_loop(paper_id=paper_id, claim_token=claim_token),
        name=f"exam.profile_sync.heartbeat:{paper_id}",
    )
    try:
        with managed_session() as session:
            task = exams_repo.get_exam_profile_sync(session, paper_id=paper_id)
            paper = exams_repo.get_exam_paper_by_id(session, paper_id)
            if task is None or paper is None:
                raise ProfileSyncExecutionError("exam_paper_not_found")
            if paper.course_id != course_id or paper.user_id != user_id:
                raise ProfileSyncExecutionError("exam_profile_sync_owner_mismatch")
            if paper.status != "graded":
                raise ProfileSyncExecutionError("exam_not_graded")
            if task.claim_token != claim_token or task.status != "processing":
                raise ProfileSyncExecutionError("profile_sync_claim_lost")

            result = await run_profile_update_workflow(
                exam_paper_id=paper_id,
                course_id=course_id,
                user_id=user_id,
                trigger=task.trigger,
                session=session,
            )
            result_value = getattr(result, "value", None)
            result_error = getattr(result, "error", None)
            if getattr(result, "failed", False):
                workflow_error = getattr(result_error, "code", None) or result_error or "profile_update_failed"
            elif not isinstance(result_value, dict):
                workflow_error = "profile_update_result_missing"
            else:
                workflow_error = result_value.get("error")
            if workflow_error:
                raise ProfileSyncExecutionError(workflow_error)

            state = dict(result_value) if isinstance(result_value, dict) else {}
            mastery = dict(state.get("mastery_result") or {})
            review_task_ids = list(state.get("review_task_ids") or [])
            completed_at = utcnow()
            finalized = exams_repo.finalize_exam_profile_sync(
                session,
                paper_id=paper_id,
                claim_token=claim_token,
                states_updated=int(mastery.get("states_updated") or 0),
                review_task_count=len(review_task_ids),
                completed_at=completed_at,
            )
            if not finalized:
                raise ProfileSyncExecutionError("profile_sync_claim_lost")
        logger.info(
            "exam_profile_sync_completed",
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
        )
    except asyncio.CancelledError:
        with managed_session() as session:
            task = exams_repo.get_exam_profile_sync(session, paper_id=paper_id)
            attempt_count = int(task.attempt_count or 1) if task is not None else 1
            exams_repo.release_exam_profile_sync(
                session,
                paper_id=paper_id,
                claim_token=claim_token,
                status="retry_wait",
                next_attempt_at=utcnow() + profile_sync_retry_delay(
                    attempt_count=attempt_count,
                    paper_id=paper_id,
                ),
                error_code="profile_sync_worker_cancelled",
            )
        raise
    except Exception as exc:
        error_code = (
            exc.error_code
            if isinstance(exc, ProfileSyncExecutionError)
            else _normalize_profile_sync_error_code(type(exc).__name__)
        )
        with managed_session() as session:
            task = exams_repo.get_exam_profile_sync(session, paper_id=paper_id)
            attempt_count = int(task.attempt_count or 1) if task is not None else 1
            terminal = attempt_count >= PROFILE_SYNC_MAX_ATTEMPTS or error_code in {
                "exam_paper_not_found",
                "exam_profile_sync_owner_mismatch",
                "exam_not_graded",
            }
            exams_repo.release_exam_profile_sync(
                session,
                paper_id=paper_id,
                claim_token=claim_token,
                status="failed" if terminal else "retry_wait",
                next_attempt_at=(
                    None
                    if terminal
                    else utcnow()
                    + profile_sync_retry_delay(attempt_count=attempt_count, paper_id=paper_id)
                ),
                error_code=error_code,
            )
        logger.warning(
            "exam_profile_sync_failed",
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
            error_code=error_code,
        )
    finally:
        heartbeat.cancel()
        try:
            await heartbeat
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning(
                "exam_profile_sync_heartbeat_cleanup_failed",
                paper_id=paper_id,
                error_type=type(exc).__name__,
            )


def schedule_exam_profile_sync_task(
    background_task_registry,
    *,
    course_id: str,
    user_id: str,
    paper_id: int,
) -> bool:
    if background_task_registry is None:
        return False
    background_task_registry.spawn(
        run_exam_profile_sync_background(
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
        ),
        kind="exam.profile_sync",
        course_id=course_id,
        name=f"exam.profile_sync:{course_id}:{paper_id}",
        dedupe_key=f"exam.profile_sync:{paper_id}",
    )
    return True


def recover_exam_profile_sync_tasks_once(background_task_registry) -> int:
    with managed_session() as session:
        tasks = exams_repo.list_recoverable_exam_profile_syncs(session, as_of=utcnow())
        recoverable = [
            (task.course_id, task.user_id, int(task.exam_paper_id))
            for task in tasks
        ]
    return sum(
        1
        for course_id, user_id, paper_id in recoverable
        if schedule_exam_profile_sync_task(
            background_task_registry,
            course_id=course_id,
            user_id=user_id,
            paper_id=paper_id,
        )
    )


async def run_exam_profile_sync_recovery_loop(*, task_registry) -> None:
    while True:
        try:
            recover_exam_profile_sync_tasks_once(task_registry)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "exam_profile_sync_recovery_scan_failed",
                error_type=type(exc).__name__,
            )
        await asyncio.sleep(PROFILE_SYNC_RECOVERY_INTERVAL_SECONDS)


__all__ = [
    "PROFILE_SYNC_MAX_ATTEMPTS",
    "ProfileSyncExecutionError",
    "is_exam_profile_sync_recoverable_now",
    "profile_sync_retry_delay",
    "recover_exam_profile_sync_tasks_once",
    "run_exam_profile_sync_background",
    "run_exam_profile_sync_recovery_loop",
    "schedule_exam_profile_sync_task",
]
