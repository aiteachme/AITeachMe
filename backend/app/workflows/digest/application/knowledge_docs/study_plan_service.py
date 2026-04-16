"""Study plan derivation from KnowledgeUnit prerequisite graph and mastery."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime

from pydantic import BaseModel, Field
from sqlmodel import Session

from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.repositories import profile_repo
from app.repositories.knowledge import knowledge_relation_repo, knowledge_unit_repo
from app.schemas.knowledge import (
    StudyPlanItemResponse,
    StudyPlanPhaseResponse,
    StudyPlanRequest,
    StudyPlanResponse,
)
from app.utils.docgen_store import read_knowledge_build_status
from app.utils.path_helpers import build_knowledge_study_plan_progress_path
from app.utils.time import utcnow

_ANCHOR_RE = re.compile(r"[^\w\u4e00-\u9fff]+")


class StudyPlanProgressStore(BaseModel):
    """Persisted checklist completion state."""

    updated_at: datetime
    completed_items: dict[str, bool] = Field(default_factory=dict)


def _anchorify(text: str) -> str:
    normalized = _ANCHOR_RE.sub("-", text.strip().lower()).strip("-")
    return f"ku_{normalized or 'study-item'}"


def _stable_id(prefix: str, *parts: object) -> str:
    payload = "||".join(str(part) for part in parts if str(part).strip())
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def _read_progress(subject: str) -> StudyPlanProgressStore:
    path = build_knowledge_study_plan_progress_path(subject)
    if not path.exists():
        return StudyPlanProgressStore(updated_at=utcnow())
    try:
        return StudyPlanProgressStore.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return StudyPlanProgressStore(updated_at=utcnow())


def _write_progress(subject: str, progress: StudyPlanProgressStore) -> None:
    path = build_knowledge_study_plan_progress_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(progress.model_dump_json(indent=2), encoding="utf-8")


def _mastery_by_unit_id(session: Session, *, subject: str, user_id: str) -> dict[int, float]:
    return {
        int(state.knowledge_node_id): float(state.mastery_score)
        for state in profile_repo.list_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            target_kind="node",
        )
        if state.knowledge_node_id is not None
    }


def _prerequisite_edges(session: Session, *, subject: str) -> list[KnowledgeEdge]:
    return [
        edge
        for edge in knowledge_relation_repo.list_all_edges_by_subject(session, subject)
        if edge.edge_type == "prerequisite"
    ]


def _sort_units_by_path_need(
    units: list[KnowledgeUnit],
    *,
    mastery: dict[int, float],
    prerequisite_edges: list[KnowledgeEdge],
) -> list[KnowledgeUnit]:
    dependent_count: dict[int, int] = {}
    for edge in prerequisite_edges:
        dependent_count[edge.source_node_id] = dependent_count.get(edge.source_node_id, 0) + 1

    def key(unit: KnowledgeUnit) -> tuple[float, int, int]:
        unit_id = int(unit.id or 0)
        mastery_score = mastery.get(unit_id, 0.0)
        return (mastery_score, -dependent_count.get(unit_id, 0), unit_id)

    return sorted(units, key=key)


def build_study_plan(session: Session, *, subject: str, user_id: str = "local") -> StudyPlanResponse:
    """Derive a learner-facing path from prerequisite graph and mastery state."""

    build_status = read_knowledge_build_status(subject)
    digest_mode = build_status.digest_mode if build_status is not None else None
    mode_reason = build_status.mode_reason if build_status is not None else None
    progress = _read_progress(subject)

    units, _ = knowledge_unit_repo.list_knowledge_units_by_subject(
        session,
        subject,
        status="active",
        limit=200,
        offset=0,
    )
    mastery = _mastery_by_unit_id(session, subject=subject, user_id=user_id)
    prerequisite_edges = _prerequisite_edges(session, subject=subject)
    item_id_by_unit_id = {
        int(unit.id): _stable_id("plan", subject, int(unit.id), unit.canonical_name)
        for unit in units
        if unit.id is not None
    }
    prereq_ids_by_target: dict[int, list[int]] = {}
    for edge in prerequisite_edges:
        prereq_ids_by_target.setdefault(edge.target_node_id, []).append(edge.source_node_id)

    sorted_units = _sort_units_by_path_need(
        units,
        mastery=mastery,
        prerequisite_edges=prerequisite_edges,
    )
    items: list[StudyPlanItemResponse] = []
    for unit in sorted_units[:40]:
        if unit.id is None:
            continue
        unit_id = int(unit.id)
        item_id = item_id_by_unit_id[unit_id]
        mastery_score = mastery.get(unit_id)
        if mastery_score is None:
            summary = f"Start with {unit.canonical_name}; no mastery data has been recorded yet."
        elif mastery_score < 0.6:
            summary = f"Repair weak point: current mastery {mastery_score:.0%}."
        elif mastery_score < 0.85:
            summary = f"Consolidate this KnowledgeUnit: current mastery {mastery_score:.0%}."
        else:
            summary = f"Use this as a stable prerequisite: current mastery {mastery_score:.0%}."
        depends_on_ids = [
            item_id_by_unit_id[prereq_id]
            for prereq_id in prereq_ids_by_target.get(unit_id, [])
            if prereq_id in item_id_by_unit_id
        ]
        items.append(
            StudyPlanItemResponse(
                id=item_id,
                title=unit.canonical_name,
                summary=summary,
                duration_minutes=20 if digest_mode == "sprint" else 30,
                depends_on_ids=depends_on_ids,
                theme_titles=[unit.node_type],
                unit_ids=[unit_id],
                doc_anchor=_anchorify(unit.canonical_name),
                completed=bool(progress.completed_items.get(item_id, False)),
            )
        )

    if not items:
        fallback_id = _stable_id("plan", subject, "empty")
        items = [
            StudyPlanItemResponse(
                id=fallback_id,
                title=f"{subject} study path",
                summary="Build KnowledgeUnits first, then revisit this path.",
                duration_minutes=30,
                depends_on_ids=[],
                theme_titles=[subject],
                unit_ids=[],
                doc_anchor=_anchorify(subject),
                completed=bool(progress.completed_items.get(fallback_id, False)),
            )
        ]

    weak_items = [item for item in items if not item.completed]
    phase = StudyPlanPhaseResponse(
        id=_stable_id("phase", subject, "knowledge_path"),
        title="Knowledge path",
        summary="Ordered by prerequisite structure and current mastery gaps.",
        duration_minutes=sum(item.duration_minutes for item in items),
        completed_items=sum(1 for item in items if item.completed),
        total_items=len(items),
        items=items,
    )
    return StudyPlanResponse(
        subject=subject,
        generated_at=utcnow(),
        digest_mode=digest_mode,
        mode_reason=mode_reason,
        total_items=len(items),
        completed_items=len(items) - len(weak_items),
        phases=[phase],
    )


def handle_study_plan_request(
    session: Session,
    *,
    subject: str,
    user_id: str = "local",
    payload: StudyPlanRequest | None = None,
) -> StudyPlanResponse:
    """Read or update the study plan through one shared request shape."""

    if payload is not None and payload.item_id and payload.completed is not None:
        progress = _read_progress(subject)
        progress.completed_items[payload.item_id] = payload.completed
        progress.updated_at = utcnow()
        _write_progress(subject, progress)
    return build_study_plan(session, subject=subject, user_id=user_id)


__all__ = [
    "build_study_plan",
    "handle_study_plan_request",
]
