"""Impact analysis for graph-driven curriculum rebuilds."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlmodel import Session, or_, select

from app.models.curriculum import PrereqDagVersion, ThemeTreeVersion
from app.models.knowledge_graph import KnowledgeEdge
from app.repositories import curriculum_repo

logger = structlog.get_logger(__name__)


@dataclass
class ImpactSet:
    """Four-layer closure used by digest incremental rebuilds."""

    changed_node_ids: set[int] = field(default_factory=set)
    affected_edge_ids: set[int] = field(default_factory=set)
    candidate_recompute_node_ids: set[int] = field(default_factory=set)
    affected_unit_ids: set[int] = field(default_factory=set)
    affected_anchor_ids: set[int] = field(default_factory=set)
    affected_tree_node_ids: set[int] = field(default_factory=set)
    affected_dag_edge_ids: set[int] = field(default_factory=set)


def analyze_impact(
    session: Session,
    subject: str,
    new_node_ids: list[int],
    updated_node_ids: list[int],
    merged_node_ids: list[int],
    split_node_ids: list[int],
) -> ImpactSet:
    """Calculate the impacted curriculum scope from graph mutations."""

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
    _compute_unit_layer(session, subject, impact)
    _compute_tree_layer(session, subject, impact)
    _compute_dag_layer(session, subject, impact)

    logger.info(
        "impact_analysis_complete",
        subject=subject,
        changed_nodes=len(impact.changed_node_ids),
        affected_edges=len(impact.affected_edge_ids),
        candidate_recompute_nodes=len(impact.candidate_recompute_node_ids),
        affected_units=len(impact.affected_unit_ids),
        affected_tree_nodes=len(impact.affected_tree_node_ids),
        affected_dag_edges=len(impact.affected_dag_edge_ids),
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


def _compute_unit_layer(session: Session, subject: str, impact: ImpactSet) -> None:
    relevant_node_ids = impact.changed_node_ids | impact.candidate_recompute_node_ids
    if not relevant_node_ids:
        return

    units = curriculum_repo.find_units_overlapping_nodes(
        session,
        subject,
        list(relevant_node_ids),
    )
    for unit in units:
        unit_id = unit.id
        if unit_id is None:
            continue
        memberships = curriculum_repo.list_memberships_by_unit(session, unit_id)
        member_node_ids = {membership.knowledge_node_id for membership in memberships}
        if member_node_ids & impact.changed_node_ids:
            impact.affected_unit_ids.add(unit_id)
            continue
        if member_node_ids & impact.candidate_recompute_node_ids:
            impact.affected_unit_ids.add(unit_id)


def _compute_tree_layer(session: Session, subject: str, impact: ImpactSet) -> None:
    if not impact.affected_unit_ids:
        return

    current_tree = session.exec(
        select(ThemeTreeVersion).where(
            ThemeTreeVersion.subject == subject,
            ThemeTreeVersion.status == "published",
        )
    ).first()
    if current_tree is None or current_tree.id is None:
        return

    tree_nodes = curriculum_repo.list_tree_nodes_by_version(session, current_tree.id)
    node_by_id = {
        node.id: node
        for node in tree_nodes
        if node.id is not None
    }
    memberships = [
        membership
        for membership in curriculum_repo.list_unit_memberships_by_version(session, current_tree.id)
        if membership.teaching_unit_id in impact.affected_unit_ids
    ]

    queue = [membership.tree_node_id for membership in memberships]
    visited: set[int] = set()
    while queue:
        node_id = queue.pop()
        if node_id in visited:
            continue
        visited.add(node_id)
        node = node_by_id.get(node_id)
        if node is None or node.parent_tree_node_id is None:
            continue
        queue.append(node.parent_tree_node_id)

    impact.affected_tree_node_ids = visited
    for node_id in visited:
        node = node_by_id.get(node_id)
        if node is not None and node.anchor_id is not None:
            impact.affected_anchor_ids.add(node.anchor_id)


def _compute_dag_layer(session: Session, subject: str, impact: ImpactSet) -> None:
    if not impact.affected_unit_ids:
        return

    current_dag = session.exec(
        select(PrereqDagVersion).where(
            PrereqDagVersion.subject == subject,
            PrereqDagVersion.status == "published",
        )
    ).first()
    if current_dag is None or current_dag.id is None:
        return

    dependencies = curriculum_repo.list_dependencies_by_version(session, current_dag.id)
    for dependency in dependencies:
        if dependency.id is None:
            continue
        if (
            dependency.source_unit_id in impact.affected_unit_ids
            or dependency.target_unit_id in impact.affected_unit_ids
        ):
            impact.affected_dag_edge_ids.add(dependency.id)
