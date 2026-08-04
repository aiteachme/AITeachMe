"""Persistence helpers for the one automatic initial exam per course."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models.course_initial_exam import CourseInitialExamJob
from app.utils.time import utcnow


def get_course_initial_exam_job(session: Session, *, course_id: str) -> CourseInitialExamJob | None:
    return session.exec(
        select(CourseInitialExamJob).where(CourseInitialExamJob.course_id == course_id)
    ).first()


def ensure_course_initial_exam_job(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    build_session_id: str = "",
    status: str = "pending",
    last_error_code: str = "",
    auto_commit: bool = False,
) -> CourseInitialExamJob:
    """Create the course marker once without reopening a completed job."""

    existing = get_course_initial_exam_job(session, course_id=course_id)
    if existing is not None:
        return existing
    now = utcnow()
    terminal = status == "completed"
    job = CourseInitialExamJob(
        course_id=course_id,
        user_id=user_id,
        status=status,
        build_session_id=str(build_session_id or ""),
        next_attempt_at=None if terminal else now,
        last_error_code=str(last_error_code or "")[:80],
        completed_at=now if terminal else None,
        created_at=now,
        updated_at=now,
    )
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        session.expire_all()
        existing = get_course_initial_exam_job(session, course_id=course_id)
        if existing is None:
            raise
        return existing
    if auto_commit:
        session.commit()
        session.refresh(job)
    return job


def claim_course_initial_exam_job(
    session: Session,
    *,
    course_id: str,
    claim_token: str,
    claimed_at: datetime,
    lease_expires_at: datetime,
) -> bool:
    result = session.exec(
        sa.update(CourseInitialExamJob)
        .where(
            CourseInitialExamJob.course_id == course_id,
            sa.or_(
                sa.and_(
                    CourseInitialExamJob.status.in_(("pending", "retry_wait")),
                    sa.or_(
                        CourseInitialExamJob.next_attempt_at.is_(None),
                        CourseInitialExamJob.next_attempt_at <= claimed_at,
                    ),
                ),
                sa.and_(
                    CourseInitialExamJob.status == "processing",
                    sa.or_(
                        CourseInitialExamJob.lease_expires_at.is_(None),
                        CourseInitialExamJob.lease_expires_at <= claimed_at,
                    ),
                ),
            ),
        )
        .values(
            status="processing",
            claim_token=claim_token,
            lease_expires_at=lease_expires_at,
            attempt_count=CourseInitialExamJob.attempt_count + 1,
            next_attempt_at=None,
            started_at=claimed_at,
            last_error_code="",
            updated_at=claimed_at,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def finalize_course_initial_exam_job(
    session: Session,
    *,
    course_id: str,
    claim_token: str,
    exam_paper_id: int,
    completed_at: datetime,
) -> bool:
    result = session.exec(
        sa.update(CourseInitialExamJob)
        .where(
            CourseInitialExamJob.course_id == course_id,
            CourseInitialExamJob.status == "processing",
            CourseInitialExamJob.claim_token == claim_token,
        )
        .values(
            status="completed",
            exam_paper_id=int(exam_paper_id),
            claim_token="",
            lease_expires_at=None,
            next_attempt_at=None,
            last_error_code="",
            completed_at=completed_at,
            updated_at=completed_at,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def release_course_initial_exam_job(
    session: Session,
    *,
    course_id: str,
    claim_token: str,
    status: str,
    next_attempt_at: datetime | None,
    error_code: str,
    exam_paper_id: int | None = None,
) -> bool:
    now = utcnow()
    values: dict[str, object] = {
        "status": status,
        "claim_token": "",
        "lease_expires_at": None,
        "next_attempt_at": next_attempt_at,
        "last_error_code": str(error_code or "initial_exam_failed")[:80],
        "exam_paper_id": int(exam_paper_id) if exam_paper_id is not None else None,
        "updated_at": now,
    }
    result = session.exec(
        sa.update(CourseInitialExamJob)
        .where(
            CourseInitialExamJob.course_id == course_id,
            CourseInitialExamJob.status == "processing",
            CourseInitialExamJob.claim_token == claim_token,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def renew_course_initial_exam_job_lease(
    session: Session,
    *,
    course_id: str,
    claim_token: str,
    lease_expires_at: datetime,
) -> bool:
    result = session.exec(
        sa.update(CourseInitialExamJob)
        .where(
            CourseInitialExamJob.course_id == course_id,
            CourseInitialExamJob.status == "processing",
            CourseInitialExamJob.claim_token == claim_token,
        )
        .values(lease_expires_at=lease_expires_at, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def list_recoverable_course_initial_exam_jobs(
    session: Session,
    *,
    as_of: datetime,
    limit: int = 100,
) -> list[CourseInitialExamJob]:
    stmt = (
        select(CourseInitialExamJob)
        .where(
            sa.or_(
                sa.and_(
                    CourseInitialExamJob.status.in_(("pending", "retry_wait")),
                    sa.or_(
                        CourseInitialExamJob.next_attempt_at.is_(None),
                        CourseInitialExamJob.next_attempt_at <= as_of,
                    ),
                ),
                sa.and_(
                    CourseInitialExamJob.status == "processing",
                    sa.or_(
                        CourseInitialExamJob.lease_expires_at.is_(None),
                        CourseInitialExamJob.lease_expires_at <= as_of,
                    ),
                ),
            )
        )
        .order_by(CourseInitialExamJob.next_attempt_at.asc(), CourseInitialExamJob.id.asc())
        .limit(max(1, limit))
    )
    return list(session.exec(stmt).all())
