"""Migration helpers for legacy knowledge graph rows and type values."""

from __future__ import annotations

from dataclasses import dataclass, field
import json

from sqlalchemy import inspect, text
from sqlmodel import Session, select

from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.knowledge_taxonomy import normalize_knowledge_unit_type, normalize_relation_type
from app.repositories import knowledge_relation_repo, knowledge_unit_repo
from app.utils.knowledge_helpers import normalize_name
from app.utils.time import utcnow


@dataclass(slots=True)
class KnowledgeGraphMigrationReport:
    """Summary for one legacy graph migration pass."""

    subject: str
    copied_legacy_units: int = 0
    copied_legacy_edges: int = 0
    normalized_units: int = 0
    normalized_edges: int = 0
    skipped_legacy_edges: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def changed_count(self) -> int:
        return (
            self.copied_legacy_units
            + self.copied_legacy_edges
            + self.normalized_units
            + self.normalized_edges
        )


def migrate_legacy_knowledge_graph(session: Session, *, subject: str) -> KnowledgeGraphMigrationReport:
    """Copy old ``knowledge_node`` rows if present and normalize current graph types."""

    report = KnowledgeGraphMigrationReport(subject=subject)
    legacy_id_map = _copy_legacy_units_if_present(session, subject=subject, report=report)
    _copy_legacy_edges_if_present(session, subject=subject, legacy_id_map=legacy_id_map, report=report)
    _normalize_current_unit_types(session, subject=subject, report=report)
    _normalize_current_edge_types(session, subject=subject, report=report)
    session.commit()
    return report


def _table_exists(session: Session, table_name: str) -> bool:
    return table_name in inspect(session.connection()).get_table_names()


def _copy_legacy_units_if_present(
    session: Session,
    *,
    subject: str,
    report: KnowledgeGraphMigrationReport,
) -> dict[int, int]:
    if not _table_exists(session, "knowledge_node"):
        return {}

    rows = list(session.execute(
        text("SELECT * FROM knowledge_node WHERE subject = :subject"),
        {"subject": subject},
    ).mappings())
    legacy_id_map: dict[int, int] = {}
    for row in rows:
        legacy_id = int(row.get("id") or 0)
        name = str(row.get("canonical_name") or row.get("name") or f"Legacy KnowledgeUnit {legacy_id}").strip()
        node_type = normalize_knowledge_unit_type(str(row.get("node_type") or row.get("type") or "concept"))
        normalized_name = str(row.get("normalized_name") or normalize_name(name))
        existing = knowledge_unit_repo.find_knowledge_unit_by_normalized_name(
            session,
            subject,
            normalized_name,
            node_type,
        )
        if existing is None:
            existing = knowledge_unit_repo.create_knowledge_unit(
                session,
                KnowledgeUnit(
                    subject=subject,
                    node_type=node_type,
                    canonical_name=name,
                    normalized_name=normalized_name,
                    summary=str(row.get("summary") or ""),
                    body=str(row.get("body") or row.get("body_markdown") or ""),
                    body_markdown=str(row.get("body_markdown") or row.get("body") or ""),
                    aliases_json=_legacy_alias_payload(legacy_id),
                    status="active",
                    confidence=float(row.get("confidence") or 1.0),
                    type_confidence=float(row.get("type_confidence") or 0.8),
                    type_source="manual",
                    build_revision_no=int(row.get("build_revision_no") or 1),
                ),
                auto_commit=False,
            )
            report.copied_legacy_units += 1
        if existing.id is not None:
            legacy_id_map[legacy_id] = existing.id
    session.flush()
    return legacy_id_map


def _copy_legacy_edges_if_present(
    session: Session,
    *,
    subject: str,
    legacy_id_map: dict[int, int],
    report: KnowledgeGraphMigrationReport,
) -> None:
    if not _table_exists(session, "knowledge_edge") or not legacy_id_map:
        return

    rows = list(session.execute(
        text("SELECT * FROM knowledge_edge WHERE subject = :subject"),
        {"subject": subject},
    ).mappings())
    for row in rows:
        source_id = legacy_id_map.get(int(row.get("source_node_id") or 0))
        target_id = legacy_id_map.get(int(row.get("target_node_id") or 0))
        if source_id is None or target_id is None:
            report.skipped_legacy_edges += 1
            continue
        edge_type = normalize_relation_type(str(row.get("edge_type") or row.get("type") or "prerequisite"))
        existing = knowledge_relation_repo.find_edge(session, source_id, target_id, edge_type)
        if existing is not None:
            continue
        knowledge_relation_repo.create_knowledge_edge(
            session,
            KnowledgeEdge(
                subject=subject,
                source_node_id=source_id,
                target_node_id=target_id,
                edge_type=edge_type,
                description=str(row.get("description") or "migrated legacy relation"),
                weight=float(row.get("weight") or 1.0),
                confidence=float(row.get("confidence") or 0.8),
                status="active",
                build_revision_no=int(row.get("build_revision_no") or 1),
            ),
            auto_commit=False,
        )
        report.copied_legacy_edges += 1
    session.flush()


def _normalize_current_unit_types(
    session: Session,
    *,
    subject: str,
    report: KnowledgeGraphMigrationReport,
) -> None:
    units = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.subject == subject)).all()
    for unit in units:
        normalized_type = normalize_knowledge_unit_type(unit.node_type)
        normalized_source = unit.type_source if unit.type_source in {"rule", "llm", "manual"} else "manual"
        changed = False
        if unit.node_type != normalized_type:
            unit.node_type = normalized_type
            changed = True
        if unit.type_source != normalized_source:
            unit.type_source = normalized_source
            changed = True
        if unit.normalized_name != normalize_name(unit.canonical_name):
            unit.normalized_name = normalize_name(unit.canonical_name)
            changed = True
        if changed:
            unit.updated_at = utcnow()
            session.add(unit)
            report.normalized_units += 1


def _normalize_current_edge_types(
    session: Session,
    *,
    subject: str,
    report: KnowledgeGraphMigrationReport,
) -> None:
    edges = session.exec(select(KnowledgeEdge).where(KnowledgeEdge.subject == subject)).all()
    for edge in edges:
        normalized_type = normalize_relation_type(edge.edge_type)
        if edge.edge_type == normalized_type:
            continue
        edge.edge_type = normalized_type
        edge.updated_at = utcnow()
        session.add(edge)
        report.normalized_edges += 1


def _legacy_alias_payload(legacy_id: int) -> str:
    return json.dumps(
        [
            {
                "alias": f"legacy_node:{legacy_id}",
                "normalized_alias": f"legacy_node:{legacy_id}",
                "language": "legacy",
                "source": "legacy_migration",
                "confidence": 1.0,
                "is_primary": False,
                "status": "active",
            }
        ],
        ensure_ascii=False,
    )


__all__ = ["KnowledgeGraphMigrationReport", "migrate_legacy_knowledge_graph"]
