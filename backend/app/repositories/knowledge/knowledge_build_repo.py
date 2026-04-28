"""Knowledge graph build coordination repository helpers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.models.subject import Subject
from app.utils.time import utcnow

_LOCK_KEY = "digest_graph_lock"
_JOBS_KEY = "digest_graph_jobs"
_MAX_JOB_RECORDS = 50


def _load_settings(subject_record: Subject) -> dict[str, object]:
    try:
        payload = json.loads(subject_record.settings_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return payload


def _store_settings(subject_record: Subject, payload: dict[str, object]) -> None:
    subject_record.settings_json = json.dumps(payload, ensure_ascii=False)


def _get_subject(session: Session, subject_id: str) -> Subject | None:
    return session.exec(select(Subject).where(Subject.id == subject_id)).first()


def _find_subject_by_job_id(session: Session, job_id: int) -> Subject | None:
    job_key = str(job_id)
    subjects = session.exec(select(Subject)).all()
    for subject in subjects:
        settings = _load_settings(subject)
        jobs_payload = settings.get(_JOBS_KEY, {})
        if isinstance(jobs_payload, dict) and job_key in jobs_payload:
            return subject
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


def acquire_subject_build_lock(
    session: Session,
    subject_id: str,
    job_id: int,
    *,
    ttl_minutes: int = 30,
) -> bool:
    subject_record = _get_subject(session, subject_id)
    if subject_record is None:
        return False

    settings = _load_settings(subject_record)
    existing_lock = settings.get(_LOCK_KEY, {})
    if isinstance(existing_lock, dict) and existing_lock:
        if not _lock_expired(existing_lock, ttl_minutes=ttl_minutes):
            return False

    settings[_LOCK_KEY] = {
        "job_id": int(job_id),
        "acquired_at": utcnow().isoformat(),
    }
    _store_settings(subject_record, settings)
    subject_record.updated_at = utcnow()
    session.add(subject_record)
    session.commit()
    return True


def release_subject_build_lock(session: Session, subject_id: str) -> None:
    subject_record = _get_subject(session, subject_id)
    if subject_record is None:
        return
    settings = _load_settings(subject_record)
    if _LOCK_KEY in settings:
        settings.pop(_LOCK_KEY, None)
        _store_settings(subject_record, settings)
        subject_record.updated_at = utcnow()
        session.add(subject_record)
        session.commit()


def update_digest_job(
    session: Session,
    job_id: int,
    *,
    subject_id: str | None = None,
    **kwargs: object,
) -> None:
    subject_record = _get_subject(session, subject_id) if subject_id else _find_subject_by_job_id(session, job_id)
    if subject_record is None:
        return

    settings = _load_settings(subject_record)
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
    _store_settings(subject_record, settings)
    subject_record.updated_at = utcnow()
    session.add(subject_record)
    session.commit()
