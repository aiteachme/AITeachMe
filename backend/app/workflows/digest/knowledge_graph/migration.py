"""Knowledge graph normalization helpers."""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_taxonomy import normalize_knowledge_unit_type, normalize_relation_type
from app.models.knowledge_unit import KnowledgeUnit
from app.utils.knowledge_helpers import normalize_name
from app.utils.time import utcnow


@dataclass(slots=True)
class KnowledgeGraphMigrationReport:
    """Summary for one graph normalization pass."""

    subject: str
    normalized_units: int = 0
    normalized_edges: int = 0

    @property
    def changed_count(self) -> int:
        return self.normalized_units + self.normalized_edges


def normalize_knowledge_graph(session: Session, *, subject: str) -> KnowledgeGraphMigrationReport:
    """Normalize current KnowledgeUnit and relation type values."""

    report = KnowledgeGraphMigrationReport(subject=subject)
    _normalize_current_unit_types(session, subject=subject, report=report)
    _normalize_current_edge_types(session, subject=subject, report=report)
    session.commit()
    return report


def _normalize_current_unit_types(
    session: Session,
    *,
    subject: str,
    report: KnowledgeGraphMigrationReport,
) -> None:
    units = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.subject == subject)).all()
    for unit in units:
        normalized_type = normalize_knowledge_unit_type(unit.knowledge_unit_type)
        normalized_source = unit.type_source if unit.type_source in {"rule", "llm", "manual"} else "manual"
        changed = False
        if unit.knowledge_unit_type != normalized_type:
            unit.knowledge_unit_type = normalized_type
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


__all__ = ["KnowledgeGraphMigrationReport", "normalize_knowledge_graph"]
