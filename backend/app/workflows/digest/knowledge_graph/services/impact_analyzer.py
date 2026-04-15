"""Impact analysis for graph-only incremental rebuilds."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlmodel import Session, or_, select

from app.models.knowledge_graph import KnowledgeEdge

logger = structlog.get_logger(__name__)


@dataclass
class ImpactSet:
    """Graph-local closure used by digest incremental rebuilds."""

    changed_node_ids: set[int] = field(default_factory=set)
    affected_edge_ids: set[int] = field(default_factory=set)
    candidate_recompute_node_ids: set[int] = field(default_factory=set)


def analyze_impact(
    session: Session,
    subject: str,
    new_node_ids: list[int],
    updated_node_ids: list[int],
    merged_node_ids: list[int],
    split_node_ids: list[int],
) -> ImpactSet:
    """Calculate graph-local impact from graph mutations."""

    impact = ImpactSet()
    impact.changed_node_ids = (
        set(new_node_ids)
        | set(updated_node_ids)
        | set(merged_node_ids)
        | set(split_node_ids)
    )

    if not impact.changed_node_ids:
        return impact

    _compute_graph_layer(session, subject, impact)

    logger.info(
        "impact_analysis_complete",
        subject=subject,
        changed_nodes=len(impact.changed_node_ids),
        affected_edges=len(impact.affected_edge_ids),
        candidate_recompute_nodes=len(impact.candidate_recompute_node_ids),
    )
    return impact


def _compute_graph_layer(session: Session, subject: str, impact: ImpactSet) -> None:
    incident_edges = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "active",
                or_(
                    KnowledgeEdge.source_node_id.in_(impact.changed_node_ids),
                    KnowledgeEdge.target_node_id.in_(impact.changed_node_ids),
                ),
            )
        ).all()
    )

    one_hop_neighbor_ids: set[int] = set()
    for edge in incident_edges:
        if edge.id is not None:
            impact.affected_edge_ids.add(edge.id)
        one_hop_neighbor_ids.add(edge.source_node_id)
        one_hop_neighbor_ids.add(edge.target_node_id)

    one_hop_neighbor_ids -= impact.changed_node_ids
    if not one_hop_neighbor_ids:
        return

    second_hop_edges = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "active",
                or_(
                    KnowledgeEdge.source_node_id.in_(one_hop_neighbor_ids),
                    KnowledgeEdge.target_node_id.in_(one_hop_neighbor_ids),
                ),
            )
        ).all()
    )
    second_hop_node_ids = {
        node_id
        for edge in second_hop_edges
        for node_id in (edge.source_node_id, edge.target_node_id)
    }
    impact.candidate_recompute_node_ids = (
        one_hop_neighbor_ids | second_hop_node_ids
    ) - impact.changed_node_ids

