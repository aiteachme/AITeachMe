"""Incremental Markdown-to-KnowledgeUnit graph synchronization."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import perf_counter

from sqlmodel import Session, select

from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.knowledge_taxonomy import normalize_knowledge_unit_type, normalize_relation_type
from app.repositories import knowledge_relation_repo, knowledge_unit_repo
from app.utils.knowledge_helpers import normalize_name
from app.utils.time import utcnow
from app.workflows.digest.shared.markdown_knowledge_anchors import (
    MarkdownKnowledgeUnit,
    extract_markdown_knowledge_units,
    validate_knowledge_unit_anchors,
)

_ANCHOR_ALIAS_SOURCE = "markdown_anchor"
_SYNC_EDGE_MARKER = "markdown_anchor_sync"


@dataclass(slots=True)
class KnowledgeSyncReport:
    """Summary of one incremental sync pass."""

    subject: str
    build_revision_no: int
    anchors_seen: list[str] = field(default_factory=list)
    created_unit_ids: list[int] = field(default_factory=list)
    updated_unit_ids: list[int] = field(default_factory=list)
    deprecated_unit_ids: list[int] = field(default_factory=list)
    created_edge_ids: list[int] = field(default_factory=list)
    updated_edge_ids: list[int] = field(default_factory=list)
    deprecated_edge_ids: list[int] = field(default_factory=list)
    elapsed_ms: int = 0

    @property
    def unit_change_count(self) -> int:
        return len(self.created_unit_ids) + len(self.updated_unit_ids) + len(self.deprecated_unit_ids)

    @property
    def edge_change_count(self) -> int:
        return len(self.created_edge_ids) + len(self.updated_edge_ids) + len(self.deprecated_edge_ids)


def sync_markdown_knowledge_graph(
    session: Session,
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None = None,
) -> KnowledgeSyncReport:
    """Synchronize anchored Markdown blocks into active KnowledgeUnits and KG edges."""

    started_at = perf_counter()
    validation = validate_knowledge_unit_anchors(markdown)
    if not validation.ok:
        raise ValueError(
            "invalid Markdown KnowledgeUnit anchors: "
            f"duplicates={validation.duplicate_anchors}, invalid={validation.invalid_anchors}"
        )

    revision_no = build_revision_no or _next_revision_no(session, subject)
    report = KnowledgeSyncReport(
        subject=subject,
        build_revision_no=revision_no,
        anchors_seen=validation.anchors,
    )
    units = extract_markdown_knowledge_units(markdown)
    unit_by_anchor: dict[str, KnowledgeUnit] = {}

    for item in units:
        unit, created = _upsert_unit(session, subject=subject, item=item, build_revision_no=revision_no)
        if unit.id is None:
            continue
        unit_by_anchor[item.anchor] = unit
        if created:
            report.created_unit_ids.append(unit.id)
        else:
            report.updated_unit_ids.append(unit.id)

    seen_edge_keys: set[tuple[int, int, str]] = set()
    for item in units:
        target = unit_by_anchor.get(item.anchor)
        if target is None or target.id is None:
            continue
        for prerequisite_name in item.prerequisites:
            source = _ensure_related_concept(
                session,
                subject=subject,
                name=prerequisite_name,
                build_revision_no=revision_no,
            )
            if source.id is None:
                continue
            edge, created = _upsert_edge(
                session,
                subject=subject,
                source_node_id=source.id,
                target_node_id=target.id,
                edge_type="prerequisite",
                description=f"{source.canonical_name} is a prerequisite for {target.canonical_name}.",
                build_revision_no=revision_no,
            )
            if edge.id is not None:
                seen_edge_keys.add((edge.source_node_id, edge.target_node_id, edge.edge_type))
                (report.created_edge_ids if created else report.updated_edge_ids).append(edge.id)
        for related_name in item.related:
            related = _ensure_related_concept(
                session,
                subject=subject,
                name=related_name,
                build_revision_no=revision_no,
            )
            if related.id is None:
                continue
            edge, created = _upsert_edge(
                session,
                subject=subject,
                source_node_id=target.id,
                target_node_id=related.id,
                edge_type="similar",
                description=f"{target.canonical_name} is related to {related.canonical_name}.",
                build_revision_no=revision_no,
            )
            if edge.id is not None:
                seen_edge_keys.add((edge.source_node_id, edge.target_node_id, edge.edge_type))
                (report.created_edge_ids if created else report.updated_edge_ids).append(edge.id)

    report.deprecated_unit_ids.extend(
        _deprecate_removed_anchor_units(
            session,
            subject=subject,
            active_anchors=set(report.anchors_seen),
            build_revision_no=revision_no,
        )
    )
    report.deprecated_edge_ids.extend(
        _deprecate_removed_sync_edges(
            session,
            subject=subject,
            seen_edge_keys=seen_edge_keys,
            build_revision_no=revision_no,
        )
    )
    session.commit()
    report.elapsed_ms = int((perf_counter() - started_at) * 1000)
    return report


def _next_revision_no(session: Session, subject: str) -> int:
    units = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.subject == subject)).all()
    edges = session.exec(select(KnowledgeEdge).where(KnowledgeEdge.subject == subject)).all()
    current = max(
        [0]
        + [int(item.build_revision_no or 0) for item in units]
        + [int(item.build_revision_no or 0) for item in edges]
    )
    return current + 1


def _upsert_unit(
    session: Session,
    *,
    subject: str,
    item: MarkdownKnowledgeUnit,
    build_revision_no: int,
) -> tuple[KnowledgeUnit, bool]:
    knowledge_unit_type = normalize_knowledge_unit_type(item.knowledge_unit_type)
    normalized_name = normalize_name(item.name)
    unit = _find_unit_by_anchor(session, subject=subject, anchor=item.anchor)
    if unit is None:
        unit = knowledge_unit_repo.find_knowledge_unit_by_normalized_name(
            session,
            subject,
            normalized_name,
            knowledge_unit_type,
        )
    created = unit is None
    if unit is None:
        unit = KnowledgeUnit(
            subject=subject,
            knowledge_unit_type=knowledge_unit_type,
            canonical_name=item.name,
            normalized_name=normalized_name,
            status="active",
        )
    unit.knowledge_unit_type = knowledge_unit_type
    unit.canonical_name = item.name
    unit.normalized_name = normalized_name
    unit.summary = item.summary or item.name
    unit.body_markdown = item.summary or item.name
    unit.type_source = "manual"
    unit.type_confidence = 1.0
    unit.status = "active"
    unit.build_revision_no = build_revision_no
    unit.updated_at = utcnow()
    unit.aliases_json = _add_anchor_alias(unit.aliases_json, item.anchor)
    if created:
        unit = knowledge_unit_repo.create_knowledge_unit(session, unit, auto_commit=False)
    else:
        session.add(unit)
    session.flush()
    return unit, created


def _ensure_related_concept(
    session: Session,
    *,
    subject: str,
    name: str,
    build_revision_no: int,
) -> KnowledgeUnit:
    normalized_name = normalize_name(name)
    existing = knowledge_unit_repo.find_knowledge_unit_by_normalized_name(
        session,
        subject,
        normalized_name,
        "concept",
    )
    if existing is not None:
        existing.status = "active"
        existing.build_revision_no = build_revision_no
        existing.updated_at = utcnow()
        session.add(existing)
        session.flush()
        return existing
    return knowledge_unit_repo.create_knowledge_unit(
        session,
        KnowledgeUnit(
            subject=subject,
            knowledge_unit_type="concept",
            canonical_name=name,
            normalized_name=normalized_name,
            summary=f"Markdown referenced concept: {name}.",
            type_source="manual",
            type_confidence=0.9,
            status="active",
            build_revision_no=build_revision_no,
        ),
        auto_commit=False,
    )


def _upsert_edge(
    session: Session,
    *,
    subject: str,
    source_node_id: int,
    target_node_id: int,
    edge_type: str,
    description: str,
    build_revision_no: int,
) -> tuple[KnowledgeEdge, bool]:
    normalized_type = normalize_relation_type(edge_type)
    existing = knowledge_relation_repo.find_edge(
        session,
        source_node_id,
        target_node_id,
        normalized_type,
    )
    created = existing is None
    edge = existing or KnowledgeEdge(
        subject=subject,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_type=normalized_type,
    )
    edge.description = f"{_SYNC_EDGE_MARKER}: {description}"
    edge.status = "active"
    edge.weight = 1.0
    edge.confidence = max(edge.confidence, 0.95)
    edge.build_revision_no = build_revision_no
    edge.updated_at = utcnow()
    if created:
        edge = knowledge_relation_repo.create_knowledge_edge(session, edge, auto_commit=False)
    else:
        session.add(edge)
    session.flush()
    return edge, created


def _find_unit_by_anchor(session: Session, *, subject: str, anchor: str) -> KnowledgeUnit | None:
    candidates = session.exec(
        select(KnowledgeUnit).where(
            KnowledgeUnit.subject == subject,
            KnowledgeUnit.status.in_(["active", "pending", "deprecated"]),
        )
    ).all()
    for unit in candidates:
        for alias in _load_aliases(unit.aliases_json):
            if alias.get("source") == _ANCHOR_ALIAS_SOURCE and alias.get("normalized_alias") == anchor:
                return unit
    return None


def _add_anchor_alias(raw_aliases: str, anchor: str) -> str:
    aliases = _load_aliases(raw_aliases)
    if not any(alias.get("source") == _ANCHOR_ALIAS_SOURCE and alias.get("normalized_alias") == anchor for alias in aliases):
        aliases.append(
            {
                "alias": anchor,
                "normalized_alias": anchor,
                "language": "anchor",
                "source": _ANCHOR_ALIAS_SOURCE,
                "confidence": 1.0,
                "is_primary": False,
                "status": "active",
            }
        )
    return json.dumps(aliases, ensure_ascii=False)


def _load_aliases(raw_aliases: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(raw_aliases or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _deprecate_removed_anchor_units(
    session: Session,
    *,
    subject: str,
    active_anchors: set[str],
    build_revision_no: int,
) -> list[int]:
    deprecated: list[int] = []
    units = session.exec(
        select(KnowledgeUnit).where(
            KnowledgeUnit.subject == subject,
            KnowledgeUnit.status == "active",
        )
    ).all()
    for unit in units:
        anchors = [
            str(alias.get("normalized_alias", ""))
            for alias in _load_aliases(unit.aliases_json)
            if alias.get("source") == _ANCHOR_ALIAS_SOURCE
        ]
        if not anchors:
            continue
        if any(anchor in active_anchors for anchor in anchors):
            continue
        unit.status = "deprecated"
        unit.build_revision_no = build_revision_no
        unit.updated_at = utcnow()
        session.add(unit)
        if unit.id is not None:
            deprecated.append(unit.id)
    return deprecated


def _deprecate_removed_sync_edges(
    session: Session,
    *,
    subject: str,
    seen_edge_keys: set[tuple[int, int, str]],
    build_revision_no: int,
) -> list[int]:
    deprecated: list[int] = []
    edges = session.exec(
        select(KnowledgeEdge).where(
            KnowledgeEdge.subject == subject,
            KnowledgeEdge.status == "active",
            KnowledgeEdge.description.startswith(f"{_SYNC_EDGE_MARKER}:"),
        )
    ).all()
    for edge in edges:
        key = (edge.source_node_id, edge.target_node_id, edge.edge_type)
        if key in seen_edge_keys:
            continue
        edge.status = "deprecated"
        edge.build_revision_no = build_revision_no
        edge.updated_at = utcnow()
        session.add(edge)
        if edge.id is not None:
            deprecated.append(edge.id)
    return deprecated


__all__ = ["KnowledgeSyncReport", "sync_markdown_knowledge_graph"]
