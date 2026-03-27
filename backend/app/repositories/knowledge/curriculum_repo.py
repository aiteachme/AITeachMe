"""Curriculum repository helpers."""

from __future__ import annotations

import json

from sqlmodel import Session, func, select

from app.core.exceptions import DagVersionConflictError, TreeVersionConflictError
from app.models.curriculum import (
    Curriculum,
    CurriculumSnapshot,
    PrereqDagVersion,
    TaxonomyAnchor,
    TeachingUnit,
    TeachingUnitMembership,
    TeachingUnitRevision,
    ThemeTreeNode,
    ThemeTreeVersion,
    UnitDependency,
    UnitTreeMembership,
)
from app.utils.time import utcnow


def _load_json_list(payload: str) -> list[dict[str, object]]:
    try:
        decoded = json.loads(payload or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, dict)]


def _dump_json_list(payload: list[dict[str, object]]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def create_teaching_unit(session: Session, unit: TeachingUnit) -> TeachingUnit:
    session.add(unit)
    session.commit()
    session.refresh(unit)
    return unit


def get_teaching_unit_by_id(session: Session, unit_id: int) -> TeachingUnit | None:
    return session.get(TeachingUnit, unit_id)


def find_unit_by_signature(
    session: Session,
    subject: str,
    member_signature: str,
) -> TeachingUnit | None:
    stmt = select(TeachingUnit).where(
        TeachingUnit.subject == subject,
        TeachingUnit.member_signature == member_signature,
    )
    return session.exec(stmt).first()


def find_units_overlapping_nodes(
    session: Session,
    subject: str,
    node_ids: list[int],
) -> list[TeachingUnit]:
    if not node_ids:
        return []

    node_id_set = set(node_ids)
    stmt = select(TeachingUnit).where(TeachingUnit.subject == subject)
    units = list(session.exec(stmt).all())
    matched: list[TeachingUnit] = []
    for unit in units:
        memberships = list_memberships_by_unit(session, unit.id or 0)
        if any(membership.knowledge_node_id in node_id_set for membership in memberships):
            matched.append(unit)
    return matched


def find_unit_by_normalized_name(
    session: Session,
    subject: str,
    normalized_name: str,
) -> TeachingUnit | None:
    stmt = select(TeachingUnit).where(
        TeachingUnit.subject == subject,
        TeachingUnit.normalized_name == normalized_name,
        TeachingUnit.status.in_(["active", "pending"]),  # type: ignore[union-attr]
    )
    return session.exec(stmt).first()


def list_units_by_subject(
    session: Session,
    subject: str,
    *,
    status: str | None = "active",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[TeachingUnit], int]:
    base = select(TeachingUnit).where(TeachingUnit.subject == subject)
    count_base = select(func.count(TeachingUnit.id)).where(TeachingUnit.subject == subject)

    if status is not None:
        base = base.where(TeachingUnit.status == status)
        count_base = count_base.where(TeachingUnit.status == status)

    total: int = session.exec(count_base).one()
    rows = list(session.exec(base.offset(offset).limit(limit).order_by(TeachingUnit.id)).all())
    return rows, total


def create_unit_revision(
    session: Session,
    revision: TeachingUnitRevision,
) -> TeachingUnitRevision:
    unit = session.get(TeachingUnit, revision.unit_id)
    if unit is None:
        return revision

    revision.id = unit.id
    unit.title = revision.title
    unit.summary = revision.summary
    unit.learning_objectives_json = revision.learning_objectives_json
    unit.current_revision_id = revision.id
    unit.updated_at = utcnow()
    session.add(unit)
    session.commit()
    return revision


def deactivate_old_unit_revisions(session: Session, unit_id: int) -> None:
    del session, unit_id


def create_unit_membership(
    session: Session,
    membership: TeachingUnitMembership,
) -> TeachingUnitMembership:
    unit = session.get(TeachingUnit, membership.unit_id)
    if unit is None:
        return membership

    payload = _load_json_list(unit.member_node_refs_json)
    payload.append(
        {
            "knowledge_node_id": membership.knowledge_node_id,
            "role": membership.role,
            "score": membership.score,
        }
    )
    unit.member_node_refs_json = _dump_json_list(payload)
    unit.updated_at = utcnow()
    session.add(unit)
    session.commit()
    return membership


def list_memberships_by_unit(
    session: Session,
    unit_id: int,
) -> list[TeachingUnitMembership]:
    unit = session.get(TeachingUnit, unit_id)
    if unit is None:
        return []

    memberships: list[TeachingUnitMembership] = []
    for index, item in enumerate(_load_json_list(unit.member_node_refs_json), start=1):
        raw_node_id = item.get("knowledge_node_id")
        if not isinstance(raw_node_id, int):
            continue
        memberships.append(
            TeachingUnitMembership(
                id=index,
                unit_id=unit_id,
                knowledge_node_id=raw_node_id,
                role=str(item.get("role", "primary")),
                score=float(item.get("score", 0.0) or 0.0),
            )
        )
    return memberships


def find_unit_by_node(session: Session, knowledge_node_id: int) -> TeachingUnit | None:
    stmt = select(TeachingUnit).where(TeachingUnit.status == "active")
    units = list(session.exec(stmt).all())
    for unit in units:
        memberships = list_memberships_by_unit(session, unit.id or 0)
        if any(item.knowledge_node_id == knowledge_node_id for item in memberships):
            return unit
    return None


def create_curriculum_job(session: Session, job: object) -> None:
    del session, job


def update_curriculum_job(session: Session, job_id: int, **kwargs: object) -> None:
    del session, job_id, kwargs


def create_taxonomy_anchor(session: Session, anchor: TaxonomyAnchor) -> TaxonomyAnchor:
    session.add(anchor)
    session.commit()
    session.refresh(anchor)
    return anchor


def list_anchors_by_subject(session: Session, subject: str) -> list[TaxonomyAnchor]:
    stmt = (
        select(TaxonomyAnchor)
        .where(TaxonomyAnchor.subject == subject)
        .order_by(TaxonomyAnchor.order_index)
    )
    return list(session.exec(stmt).all())


def get_uncategorized_anchor(session: Session, subject: str) -> TaxonomyAnchor:
    stmt = select(TaxonomyAnchor).where(
        TaxonomyAnchor.subject == subject,
        TaxonomyAnchor.anchor_type == "system",
        TaxonomyAnchor.is_system == True,  # noqa: E712
    )
    anchor = session.exec(stmt).first()
    if anchor is not None:
        return anchor

    anchor = TaxonomyAnchor(
        subject=subject,
        anchor_type="system",
        title="未归类",
        normalized_title="未归类",
        is_system=True,
        status="active",
    )
    session.add(anchor)
    session.commit()
    session.refresh(anchor)
    return anchor


def get_curriculum_by_id(session: Session, curriculum_id: int) -> Curriculum | None:
    return session.get(Curriculum, curriculum_id)


def create_curriculum_snapshot(
    session: Session,
    snapshot: CurriculumSnapshot,
) -> CurriculumSnapshot:
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


def get_current_curriculum_snapshot(
    session: Session,
    subject: str,
) -> CurriculumSnapshot | None:
    stmt = (
        select(CurriculumSnapshot)
        .where(
            CurriculumSnapshot.subject == subject,
            CurriculumSnapshot.status == "published",
        )
        .order_by(CurriculumSnapshot.version_no.desc(), CurriculumSnapshot.id.desc())
    )
    return session.exec(stmt).first()


def _get_existing_draft_curriculum(session: Session, subject: str) -> Curriculum | None:
    stmt = (
        select(Curriculum)
        .where(
            Curriculum.subject == subject,
            Curriculum.status == "draft",
        )
        .order_by(Curriculum.version_no.desc(), Curriculum.id.desc())
    )
    return session.exec(stmt).first()


def _ensure_curriculum_draft_with_optimistic_lock(
    session: Session,
    *,
    subject: str,
    expected_prev_version_no: int,
    conflict_error: type[Exception],
) -> Curriculum:
    current = get_current_curriculum_snapshot(session, subject)
    actual_prev = current.version_no if current is not None else 0
    draft = _get_existing_draft_curriculum(session, subject)
    if draft is not None:
        if draft.version_no != actual_prev + 1:
            raise conflict_error(subject)  # type: ignore[misc]
        return draft
    if actual_prev != expected_prev_version_no:
        raise conflict_error(subject)  # type: ignore[misc]

    draft = Curriculum(
        subject=subject,
        version_no=actual_prev + 1,
        status="draft",
        is_current=False,
    )
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


def create_theme_tree_version(
    session: Session,
    version: ThemeTreeVersion,
) -> ThemeTreeVersion:
    return create_curriculum_snapshot(session, version)


def get_current_theme_tree_version(
    session: Session,
    subject: str,
) -> ThemeTreeVersion | None:
    return get_current_curriculum_snapshot(session, subject)


def create_theme_tree_version_with_optimistic_lock(
    session: Session,
    subject: str,
    expected_prev_version_no: int,
) -> ThemeTreeVersion:
    return _ensure_curriculum_draft_with_optimistic_lock(
        session,
        subject=subject,
        expected_prev_version_no=expected_prev_version_no,
        conflict_error=TreeVersionConflictError,
    )


def create_theme_tree_node(
    session: Session,
    node: ThemeTreeNode,
) -> ThemeTreeNode:
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def create_unit_tree_membership(
    session: Session,
    membership: UnitTreeMembership,
) -> UnitTreeMembership:
    tree_node = session.get(ThemeTreeNode, membership.tree_node_id)
    if tree_node is None:
        return membership

    payload = _load_json_list(tree_node.unit_refs_json)
    payload.append(
        {
            "teaching_unit_id": membership.teaching_unit_id,
            "membership_role": membership.membership_role,
            "membership_source": membership.membership_source,
            "score": membership.score,
        }
    )
    tree_node.unit_refs_json = _dump_json_list(payload)
    session.add(tree_node)
    session.commit()
    return membership


def list_tree_nodes_by_version(
    session: Session,
    tree_version_id: int,
) -> list[ThemeTreeNode]:
    stmt = (
        select(ThemeTreeNode)
        .where(ThemeTreeNode.tree_version_id == tree_version_id)
        .order_by(ThemeTreeNode.order_index)
    )
    return list(session.exec(stmt).all())


def list_unit_memberships_by_version(
    session: Session,
    tree_version_id: int,
) -> list[UnitTreeMembership]:
    nodes = list_tree_nodes_by_version(session, tree_version_id)
    memberships: list[UnitTreeMembership] = []
    next_id = 1
    for node in nodes:
        for item in _load_json_list(node.unit_refs_json):
            raw_unit_id = item.get("teaching_unit_id")
            if not isinstance(raw_unit_id, int):
                continue
            memberships.append(
                UnitTreeMembership(
                    id=next_id,
                    tree_version_id=tree_version_id,
                    tree_node_id=node.id or 0,
                    teaching_unit_id=raw_unit_id,
                    membership_role=str(item.get("membership_role", "primary")),
                    membership_source=str(item.get("membership_source", "auto")),
                    score=float(item.get("score", 0.0) or 0.0),
                )
            )
            next_id += 1
    return memberships


def update_taxonomy_anchor(
    session: Session,
    anchor_id: int,
    **kwargs: object,
) -> TaxonomyAnchor | None:
    anchor = session.get(TaxonomyAnchor, anchor_id)
    if anchor is None:
        return None
    for key, value in kwargs.items():
        setattr(anchor, key, value)
    anchor.updated_at = utcnow()
    session.add(anchor)
    session.commit()
    session.refresh(anchor)
    return anchor


def delete_taxonomy_anchor(session: Session, anchor_id: int) -> bool:
    anchor = session.get(TaxonomyAnchor, anchor_id)
    if anchor is None or anchor.is_system:
        return False
    session.delete(anchor)
    session.commit()
    return True


def create_prereq_dag_version(
    session: Session,
    version: PrereqDagVersion,
) -> PrereqDagVersion:
    return create_curriculum_snapshot(session, version)


def get_current_prereq_dag_version(
    session: Session,
    subject: str,
) -> PrereqDagVersion | None:
    return get_current_curriculum_snapshot(session, subject)


def create_prereq_dag_version_with_optimistic_lock(
    session: Session,
    subject: str,
    expected_prev_version_no: int,
) -> PrereqDagVersion:
    return _ensure_curriculum_draft_with_optimistic_lock(
        session,
        subject=subject,
        expected_prev_version_no=expected_prev_version_no,
        conflict_error=DagVersionConflictError,
    )


def create_unit_dependency(
    session: Session,
    dep: UnitDependency,
) -> UnitDependency:
    session.add(dep)
    session.commit()
    session.refresh(dep)
    return dep


def list_dependencies_by_version(
    session: Session,
    dag_version_id: int,
) -> list[UnitDependency]:
    stmt = (
        select(UnitDependency)
        .where(UnitDependency.dag_version_id == dag_version_id)
        .order_by(UnitDependency.id)
    )
    return list(session.exec(stmt).all())


def list_dependencies_by_unit(
    session: Session,
    dag_version_id: int,
    unit_id: int,
) -> list[UnitDependency]:
    stmt = (
        select(UnitDependency)
        .where(
            UnitDependency.dag_version_id == dag_version_id,
            (UnitDependency.source_unit_id == unit_id)
            | (UnitDependency.target_unit_id == unit_id),
        )
        .order_by(UnitDependency.id)
    )
    return list(session.exec(stmt).all())
