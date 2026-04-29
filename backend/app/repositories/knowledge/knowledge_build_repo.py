"""Knowledge graph build coordination repository helpers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.models.course import Course
from app.utils.time import utcnow

_LOCK_KEY = "digest_graph_lock"
_JOBS_KEY = "digest_graph_jobs"
_MAX_JOB_RECORDS = 50


def _load_settings(course_record: Course) -> dict[str, object]:
    try:
        payload = json.loads(course_record.settings_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return payload


def _store_settings(course_record: Course, payload: dict[str, object]) -> None:
    course_record.settings_json = json.dumps(payload, ensure_ascii=False)


def _get_course(session: Session, course_id: str) -> Course | None:
    return session.exec(select(Course).where(Course.id == course_id)).first()


def _find_course_by_job_id(session: Session, job_id: int) -> Course | None:
    job_key = str(job_id)
    courses = session.exec(select(Course)).all()
    for course in courses:
        settings = _load_settings(course)
        jobs_payload = settings.get(_JOBS_KEY, {})
        if isinstance(jobs_payload, dict) and job_key in jobs_payload:
            return course
    return None


def _lock_expired(lock_payload: dict[str, object], *, ttl_minutes: int) -> bool:
    acquired_at_raw = lock_payload.get("acquired_at")
    if not isinstance(acquired_at_raw, str) or not acquired_at_raw.strip():
        return True
    try:
        acquired_at = datetime.fromisoformat(acquired_at_raw)
    except ValueError:
        return True
    return utcnow() - acquired_at > timedelta(minutes=max(1, ttl_minutes))


def acquire_course_build_lock(
    session: Session,
    course_id: str,
    job_id: int,
    *,
    ttl_minutes: int = 30,
) -> bool:
    course_record = _get_course(session, course_id)
    if course_record is None:
        return False

    settings = _load_settings(course_record)
    existing_lock = settings.get(_LOCK_KEY, {})
    if isinstance(existing_lock, dict) and existing_lock:
        if not _lock_expired(existing_lock, ttl_minutes=ttl_minutes):
            return False

    settings[_LOCK_KEY] = {
        "job_id": int(job_id),
        "acquired_at": utcnow().isoformat(),
    }
    _store_settings(course_record, settings)
    course_record.updated_at = utcnow()
    session.add(course_record)
    session.commit()
    return True


def release_course_build_lock(session: Session, course_id: str) -> None:
    course_record = _get_course(session, course_id)
    if course_record is None:
        return
    settings = _load_settings(course_record)
    if _LOCK_KEY in settings:
        settings.pop(_LOCK_KEY, None)
        _store_settings(course_record, settings)
        course_record.updated_at = utcnow()
        session.add(course_record)
        session.commit()


def update_digest_job(
    session: Session,
    job_id: int,
    *,
    course_id: str | None = None,
    **kwargs: object,
) -> None:
    course_record = _get_course(session, course_id) if course_id else _find_course_by_job_id(session, job_id)
    if course_record is None:
        return

    settings = _load_settings(course_record)
    jobs_payload = settings.get(_JOBS_KEY, {})
    jobs: dict[str, dict[str, object]]
    if isinstance(jobs_payload, dict):
        jobs = {str(key): dict(value) for key, value in jobs_payload.items() if isinstance(value, dict)}
    else:
        jobs = {}

    job_key = str(job_id)
    now_iso = utcnow().isoformat()
    record = dict(jobs.get(job_key, {}))
    if "created_at" not in record:
        record["created_at"] = now_iso
    record.update(kwargs)
    record["job_id"] = int(job_id)
    record["updated_at"] = now_iso
    jobs[job_key] = record

    if len(jobs) > _MAX_JOB_RECORDS:
        ordered = sorted(
            jobs.items(),
            key=lambda item: str(item[1].get("updated_at") or ""),
            reverse=True,
        )
        jobs = dict(ordered[:_MAX_JOB_RECORDS])

    settings[_JOBS_KEY] = jobs
    _store_settings(course_record, settings)
    course_record.updated_at = utcnow()
    session.add(course_record)
    session.commit()
