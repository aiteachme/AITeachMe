"""Release controls for ComputableTextbook graph alignment rollout."""

from __future__ import annotations

from dataclasses import dataclass, field
import json

from sqlmodel import Session, select

from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.subject import Subject
from app.utils.time import utcnow

_SETTINGS_KEY = "computable_textbook_release"


@dataclass(slots=True)
class KnowledgeGraphReleaseSnapshot:
    """Read-only rollout state for one subject."""

    subject: str
    rollout_enabled: bool
    active_revision_no: int
    previous_revision_no: int | None
    active_unit_count: int
    active_edge_count: int
    rollback_available: bool
    observability: dict[str, object] = field(default_factory=dict)


def enable_computable_textbook_rollout(
    session: Session,
    *,
    subject: str,
    revision_no: int,
    rollout_percent: int = 100,
) -> KnowledgeGraphReleaseSnapshot:
    """Enable the new KnowledgeUnit/KG path and keep the previous revision for rollback."""

    subject_record = _require_subject(session, subject)
    settings = _load_settings(subject_record)
    previous_revision = settings.get("active_revision_no")
    settings.update(
        {
            "rollout_enabled": True,
            "rollout_percent": max(0, min(100, int(rollout_percent))),
            "previous_revision_no": previous_revision,
            "active_revision_no": int(revision_no),
            "updated_at": utcnow().isoformat(),
        }
    )
    _store_settings(subject_record, settings)
    session.add(subject_record)
    session.commit()
    return get_release_snapshot(session, subject=subject)


def rollback_computable_textbook_rollout(
    session: Session,
    *,
    subject: str,
) -> KnowledgeGraphReleaseSnapshot:
    """Rollback to the previous active graph revision if one is recorded."""

    subject_record = _require_subject(session, subject)
    settings = _load_settings(subject_record)
    previous_revision = settings.get("previous_revision_no")
    if previous_revision is None:
        settings["rollout_enabled"] = False
    else:
        current_revision = settings.get("active_revision_no")
        settings["active_revision_no"] = int(previous_revision)
        settings["previous_revision_no"] = current_revision
        _restore_revision_status(session, subject=subject, revision_no=int(previous_revision))
    settings["updated_at"] = utcnow().isoformat()
    _store_settings(subject_record, settings)
    session.add(subject_record)
    session.commit()
    return get_release_snapshot(session, subject=subject)


def get_release_snapshot(session: Session, *, subject: str) -> KnowledgeGraphReleaseSnapshot:
    """Return rollout, rollback, and observability status for one subject."""

    subject_record = _require_subject(session, subject)
    settings = _load_settings(subject_record)
    active_revision = int(settings.get("active_revision_no") or _latest_revision_no(session, subject))
    previous_revision = settings.get("previous_revision_no")
    active_unit_count = len(
        session.exec(
            select(KnowledgeUnit.id).where(
                KnowledgeUnit.subject == subject,
                KnowledgeUnit.status == "active",
            )
        ).all()
    )
    active_edge_count = len(
        session.exec(
            select(KnowledgeEdge.id).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "active",
            )
        ).all()
    )
    observability = {
        "active_revision_no": active_revision,
        "active_unit_count": active_unit_count,
        "active_edge_count": active_edge_count,
        "deprecated_unit_count": _count_units(session, subject=subject, status="deprecated"),
        "deprecated_edge_count": _count_edges(session, subject=subject, status="deprecated"),
        "updated_at": settings.get("updated_at"),
        "rollout_percent": int(settings.get("rollout_percent") or 0),
    }
    return KnowledgeGraphReleaseSnapshot(
        subject=subject,
        rollout_enabled=bool(settings.get("rollout_enabled", False)),
        active_revision_no=active_revision,
        previous_revision_no=None if previous_revision is None else int(previous_revision),
        active_unit_count=active_unit_count,
        active_edge_count=active_edge_count,
        rollback_available=previous_revision is not None,
        observability=observability,
    )


def _restore_revision_status(session: Session, *, subject: str, revision_no: int) -> None:
    units = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.subject == subject)).all()
    for unit in units:
        unit.status = "active" if unit.build_revision_no == revision_no else "deprecated"
        unit.updated_at = utcnow()
        session.add(unit)
    edges = session.exec(select(KnowledgeEdge).where(KnowledgeEdge.subject == subject)).all()
    for edge in edges:
        edge.status = "active" if edge.build_revision_no == revision_no else "deprecated"
        edge.updated_at = utcnow()
        session.add(edge)


def _latest_revision_no(session: Session, subject: str) -> int:
    units = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.subject == subject)).all()
    edges = session.exec(select(KnowledgeEdge).where(KnowledgeEdge.subject == subject)).all()
    return max(
        [0]
        + [int(item.build_revision_no or 0) for item in units]
        + [int(item.build_revision_no or 0) for item in edges]
    )


def _count_units(session: Session, *, subject: str, status: str) -> int:
    return len(
        session.exec(
            select(KnowledgeUnit.id).where(
                KnowledgeUnit.subject == subject,
                KnowledgeUnit.status == status,
            )
        ).all()
    )


def _count_edges(session: Session, *, subject: str, status: str) -> int:
    return len(
        session.exec(
            select(KnowledgeEdge.id).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == status,
            )
        ).all()
    )


def _require_subject(session: Session, subject: str) -> Subject:
    record = session.exec(select(Subject).where(Subject.slug == subject)).first()
    if record is None:
        raise ValueError(f"Subject `{subject}` not found.")
    return record


def _load_settings(subject: Subject) -> dict[str, object]:
    try:
        payload = json.loads(subject.settings_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    release_payload = payload.get(_SETTINGS_KEY, {})
    return dict(release_payload) if isinstance(release_payload, dict) else {}


def _store_settings(subject: Subject, release_settings: dict[str, object]) -> None:
    try:
        payload = json.loads(subject.settings_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload[_SETTINGS_KEY] = release_settings
    subject.settings_json = json.dumps(payload, ensure_ascii=False)


__all__ = [
    "KnowledgeGraphReleaseSnapshot",
    "enable_computable_textbook_rollout",
    "get_release_snapshot",
    "rollback_computable_textbook_rollout",
]
