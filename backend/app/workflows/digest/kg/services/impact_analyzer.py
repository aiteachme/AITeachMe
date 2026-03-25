"""Impact analysis for graph-driven curriculum refresh."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from sqlmodel import Session, select

from app.models import (
    CurriculumDependency,
    CurriculumTreeNode,
    CurriculumUnitLink,
    CurriculumVersion,
    Subject,
    TeachingUnitMembership,
)

logger = structlog.get_logger(__name__)


@dataclass
class ImpactSet:
    """Incremental build impact set with lightweight closures."""

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
    """Compute a lightweight impact set against the flattened schema."""

    impact = ImpactSet(
        changed_node_ids=set(new_node_ids) | set(updated_node_ids) | set(merged_node_ids) | set(split_node_ids)
    )
    if not impact.changed_node_ids:
        return impact

    memberships = list(
        session.exec(
            select(TeachingUnitMembership).where(
                TeachingUnitMembership.knowledge_node_id.in_(impact.changed_node_ids)  # type: ignore[union-attr]
            )
        ).all()
    )
    impact.affected_unit_ids = {int(item.unit_id) for item in memberships}

    subject_row = session.exec(select(Subject).where(Subject.slug == subject)).first()
    version = None
    if subject_row is not None and subject_row.id is not None:
        version = session.exec(
            select(CurriculumVersion)
            .where(
                CurriculumVersion.subject_id == int(subject_row.id),
                CurriculumVersion.status == "published",
            )
            .order_by(CurriculumVersion.version_no.desc())  # type: ignore[union-attr]
        ).first()
    if version is not None and version.id is not None and impact.affected_unit_ids:
        tree_links = list(
            session.exec(
                select(CurriculumUnitLink).where(
                    CurriculumUnitLink.curriculum_version_id == int(version.id),
                    CurriculumUnitLink.teaching_unit_id.in_(impact.affected_unit_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        impact.affected_tree_node_ids = {int(item.tree_node_id) for item in tree_links}
        if impact.affected_tree_node_ids:
            tree_nodes = list(
                session.exec(
                    select(CurriculumTreeNode).where(
                        CurriculumTreeNode.id.in_(impact.affected_tree_node_ids)  # type: ignore[union-attr]
                    )
                ).all()
            )
            impact.affected_anchor_ids = {int(node.id or 0) for node in tree_nodes if node.id is not None}

        dependencies = list(
            session.exec(
                select(CurriculumDependency).where(
                    CurriculumDependency.curriculum_version_id == int(version.id),
                    (
                        CurriculumDependency.source_unit_id.in_(impact.affected_unit_ids)  # type: ignore[union-attr]
                    )
                    | (
                        CurriculumDependency.target_unit_id.in_(impact.affected_unit_ids)  # type: ignore[union-attr]
                    ),
                )
            ).all()
        )
        impact.affected_dag_edge_ids = {int(item.id or 0) for item in dependencies if item.id is not None}

    logger.info(
        "impact_analysis_complete",
        subject=subject,
        changed_nodes=len(impact.changed_node_ids),
        affected_units=len(impact.affected_unit_ids),
        affected_tree_nodes=len(impact.affected_tree_node_ids),
        affected_dag_edges=len(impact.affected_dag_edge_ids),
    )
    return impact
