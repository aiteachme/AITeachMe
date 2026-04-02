"""Curriculum and teaching-unit query services."""

from __future__ import annotations

import json

import structlog
from sqlmodel import Session, select

from app.core.exceptions import (
    NoPublishedCurriculumSnapshotError,
    NoPublishedDagError,
    NoPublishedTreeError,
    TeachingUnitNotFoundError,
)
from app.models import (
    Curriculum,
    KnowledgeNode,
    TaxonomyAnchor,
    TeachingUnit,
    ThemeTreeNode,
    UnitDependency,
)
from app.repositories import curriculum_repo
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.knowledge import (
    CurriculumSnapshotResponse,
    PrereqDagResponse,
    TaxonomyAnchorResponse,
    TeachingUnitDetailResponse,
    TeachingUnitResponse,
    ThemeTreeNodeResponse,
    ThemeTreeResponse,
    TreeUnitItem,
    UnitDependencyItem,
    UnitMembershipItem,
    UnitRevisionItem,
)
from app.utils.kg_helpers import normalize_name

logger = structlog.get_logger()


def _load_json_list(payload: str) -> list[dict[str, object]]:
    try:
        decoded = json.loads(payload or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, dict)]


def get_teaching_units(
    session: Session,
    *,
    subject: str,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PaginatedData[TeachingUnitResponse]:
    offset = (page - 1) * size
    units, total = curriculum_repo.list_units_by_subject(
        session,
        subject,
        status=status or "active",
        limit=size,
        offset=offset,
    )
    items = [
        TeachingUnitResponse(
            id=u.id,  # type: ignore[arg-type]
            subject=u.subject,
            canonical_name=u.canonical_name,
            status=u.status,
            confidence=u.confidence,
            created_at=u.created_at,
            updated_at=u.updated_at,
        )
        for u in units
    ]
    return build_paginated_data(items=items, page=page, size=size, total=total)


def get_teaching_unit_detail(
    session: Session,
    *,
    subject: str,
    unit_id: int,
) -> TeachingUnitDetailResponse:
    unit = curriculum_repo.get_teaching_unit_by_id(session, unit_id)
    if unit is None or unit.subject != subject:
        raise TeachingUnitNotFoundError(unit_id)

    try:
        objectives = json.loads(unit.learning_objectives_json or "[]")
    except (ValueError, TypeError):
        objectives = []

    current_rev = UnitRevisionItem(
        title=unit.title or unit.canonical_name,
        summary=unit.summary,
        learning_objectives=objectives if isinstance(objectives, list) else [],
    )

    memberships = curriculum_repo.list_memberships_by_unit(session, unit_id)
    members: list[UnitMembershipItem] = []
    for membership in memberships:
        node = session.get(KnowledgeNode, membership.knowledge_node_id)
        members.append(
            UnitMembershipItem(
                id=membership.id or 0,
                knowledge_node_id=membership.knowledge_node_id,
                node_canonical_name=node.canonical_name if node else f"node#{membership.knowledge_node_id}",
                node_type=node.node_type if node else "unknown",
                role=membership.role,
                score=membership.score,
            )
        )

    return TeachingUnitDetailResponse(
        id=unit.id,  # type: ignore[arg-type]
        subject=unit.subject,
        canonical_name=unit.canonical_name,
        normalized_name=unit.normalized_name,
        member_signature=unit.member_signature,
        status=unit.status,
        confidence=unit.confidence,
        current_revision=current_rev,
        members=members,
        created_at=unit.created_at,
        updated_at=unit.updated_at,
    )


def get_current_theme_tree(
    session: Session,
    *,
    subject: str,
) -> ThemeTreeResponse:
    version = curriculum_repo.get_current_theme_tree_version(session, subject)
    if version is None:
        logger.warning("current_theme_tree_not_found", subject=subject)
        raise NoPublishedTreeError(subject)

    tree_nodes = curriculum_repo.list_tree_nodes_by_version(session, version.id or 0)
    node_map: dict[int, ThemeTreeNodeResponse] = {}
    for tree_node in tree_nodes:
        units: list[TreeUnitItem] = []
        for item in _load_json_list(tree_node.unit_refs_json):
            raw_unit_id = item.get("teaching_unit_id")
            if not isinstance(raw_unit_id, int):
                continue
            unit = curriculum_repo.get_teaching_unit_by_id(session, raw_unit_id)
            units.append(
                TreeUnitItem(
                    teaching_unit_id=raw_unit_id,
                    canonical_name=unit.canonical_name if unit else f"unit#{raw_unit_id}",
                    membership_role=str(item.get("membership_role", "primary")),
                    membership_source=str(item.get("membership_source", "auto")),
                    score=float(item.get("score", 0.0) or 0.0),
                )
            )
        node_map[tree_node.id or 0] = ThemeTreeNodeResponse(
            id=tree_node.id or 0,
            tree_version_id=tree_node.tree_version_id,
            anchor_id=tree_node.anchor_id,
            parent_tree_node_id=tree_node.parent_tree_node_id,
            title=tree_node.title,
            node_type=tree_node.node_type,
            order_index=tree_node.order_index,
            summary=tree_node.summary,
            units=units,
        )

    roots: list[ThemeTreeNodeResponse] = []
    for tree_node in tree_nodes:
        response_node = node_map[tree_node.id or 0]
        parent_id = tree_node.parent_tree_node_id
        if parent_id is not None and parent_id in node_map:
            node_map[parent_id].children.append(response_node)
        else:
            roots.append(response_node)

    return ThemeTreeResponse(
        version_id=version.id or 0,
        version_no=version.version_no,
        subject=version.subject,
        status=version.status,
        created_at=version.created_at,
        tree=roots,
    )


def manage_taxonomy_anchors(
    session: Session,
    *,
    subject: str,
    action: str,
    anchor_id: int | None = None,
    title: str | None = None,
    anchor_type: str | None = None,
    parent_anchor_id: int | None = None,
    order_index: int | None = None,
) -> list[TaxonomyAnchorResponse]:
    if action == "create":
        if not title:
            raise ValueError("Creating an anchor requires title.")
        anchor = TaxonomyAnchor(
            subject=subject,
            anchor_type=anchor_type or "teacher_defined",
            title=title,
            normalized_title=normalize_name(title),
            parent_anchor_id=parent_anchor_id,
            order_index=order_index or 0,
            status="active",
        )
        curriculum_repo.create_taxonomy_anchor(session, anchor)
    elif action == "update":
        if anchor_id is None:
            raise ValueError("Updating an anchor requires anchor_id.")
        updates: dict[str, object] = {}
        if title is not None:
            updates["title"] = title
            updates["normalized_title"] = normalize_name(title)
        if anchor_type is not None:
            updates["anchor_type"] = anchor_type
        if parent_anchor_id is not None:
            updates["parent_anchor_id"] = parent_anchor_id
        if order_index is not None:
            updates["order_index"] = order_index
        if updates:
            curriculum_repo.update_taxonomy_anchor(session, anchor_id, **updates)
    elif action == "delete":
        if anchor_id is None:
            raise ValueError("Deleting an anchor requires anchor_id.")
        curriculum_repo.delete_taxonomy_anchor(session, anchor_id)

    anchors = curriculum_repo.list_anchors_by_subject(session, subject)
    return [
        TaxonomyAnchorResponse(
            id=anchor.id,  # type: ignore[arg-type]
            subject=anchor.subject,
            anchor_type=anchor.anchor_type,
            title=anchor.title,
            parent_anchor_id=anchor.parent_anchor_id,
            order_index=anchor.order_index,
            confidence=anchor.confidence,
            is_system=anchor.is_system,
            status=anchor.status,
            created_at=anchor.created_at,
            updated_at=anchor.updated_at,
        )
        for anchor in anchors
    ]


def get_current_prereq_dag(
    session: Session,
    *,
    subject: str,
) -> PrereqDagResponse:
    version = curriculum_repo.get_current_prereq_dag_version(session, subject)
    if version is None:
        logger.warning("current_prereq_dag_not_found", subject=subject)
        raise NoPublishedDagError(subject)

    deps = curriculum_repo.list_dependencies_by_version(session, version.id or 0)
    items: list[UnitDependencyItem] = []
    for dep in deps:
        src = curriculum_repo.get_teaching_unit_by_id(session, dep.source_unit_id)
        tgt = curriculum_repo.get_teaching_unit_by_id(session, dep.target_unit_id)
        items.append(
            UnitDependencyItem(
                id=dep.id,  # type: ignore[arg-type]
                source_unit_id=dep.source_unit_id,
                source_unit_name=src.canonical_name if src else f"unit#{dep.source_unit_id}",
                target_unit_id=dep.target_unit_id,
                target_unit_name=tgt.canonical_name if tgt else f"unit#{dep.target_unit_id}",
                dependency_type=dep.dependency_type,
                confidence=dep.confidence,
                supporting_edge_count=dep.supporting_edge_count,
            )
        )

    return PrereqDagResponse(
        version_id=version.id or 0,
        version_no=version.version_no,
        subject=version.subject,
        status=version.status,
        created_at=version.created_at,
        dependencies=items,
    )


def get_current_curriculum_snapshot(
    session: Session,
    *,
    subject: str,
) -> CurriculumSnapshotResponse:
    snapshot = curriculum_repo.get_current_curriculum_snapshot(session, subject)
    if snapshot is None:
        logger.warning("current_curriculum_snapshot_not_found", subject=subject)
        raise NoPublishedCurriculumSnapshotError(subject)

    return CurriculumSnapshotResponse(
        id=snapshot.id or 0,
        subject=snapshot.subject,
        version_no=snapshot.version_no,
        status=snapshot.status,
        theme_tree_version_id=snapshot.id,
        prereq_dag_version_id=snapshot.id,
        syllabus_version_id=snapshot.syllabus_version_id,
        created_at=snapshot.created_at,
    )
