"""Knowledge graph build coordination repository helpers."""

from __future__ import annotations

from sqlmodel import Session

def acquire_subject_build_lock(
    session: Session,
    subject: str,
    job_id: int,
    *,
    ttl_minutes: int = 30,
) -> bool:
    del session, subject, job_id, ttl_minutes
    return True


def release_subject_build_lock(session: Session, subject: str) -> None:
    del session, subject


def update_digest_job(session: Session, job_id: int, **kwargs: object) -> None:
    del session, job_id, kwargs
