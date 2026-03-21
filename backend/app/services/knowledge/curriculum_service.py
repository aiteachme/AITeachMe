"""课程结构服务层：教学单元、主题树、先修 DAG、锚点管理、清空知识。"""

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
from app.models.curriculum import (
    CurriculumDeriveJob,
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
from app.models.knowledge import Document, DocumentChunk
from app.models.knowledge_graph import (
    EdgeRevision,
    EvidenceLink,
    GraphDigestJob,
    KnowledgeAlias,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeRevision,
    SubjectBuildLock,
)
from app.repositories import curriculum_repo, knowledge_repo
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


# ---------------------------------------------------------------------------
# 教学单元查询
# ---------------------------------------------------------------------------


def get_teaching_units(
    session: Session,
    *,
    subject: str,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PaginatedData[TeachingUnitResponse]:
    """分页查询教学单元。"""
    offset = (page - 1) * size
    units, total = curriculum_repo.list_units_by_subject(
        session, subject, status=status or "active", limit=size, offset=offset,
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
    session: Session, *, subject: str, unit_id: int
) -> TeachingUnitDetailResponse:
    """教学单元详情：base info + revision + members。"""
    unit = curriculum_repo.get_teaching_unit_by_id(session, unit_id)
    if unit is None or unit.subject != subject:
        raise TeachingUnitNotFoundError(unit_id)

    # 当前修订
    current_rev: UnitRevisionItem | None = None
    if unit.current_revision_id is not None:
        rev = session.get(TeachingUnitRevision, unit.current_revision_id)
        if rev is not None:
            try:
                objectives = json.loads(rev.learning_objectives_json)
            except (ValueError, TypeError):
                objectives = []
            current_rev = UnitRevisionItem(
                title=rev.title,
                summary=rev.summary,
                learning_objectives=objectives,
            )

    # 成员节点
    memberships = curriculum_repo.list_memberships_by_unit(session, unit_id)
    members: list[UnitMembershipItem] = []
    for m in memberships:
        node = session.get(KnowledgeNode, m.knowledge_node_id)
        members.append(
            UnitMembershipItem(
                id=m.id,  # type: ignore[arg-type]
                knowledge_node_id=m.knowledge_node_id,
                node_canonical_name=node.canonical_name if node else f"node#{m.knowledge_node_id}",
                node_type=node.node_type if node else "unknown",
                role=m.role,
                score=m.score,
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


# ---------------------------------------------------------------------------
# 主题树查询
# ---------------------------------------------------------------------------


def get_current_theme_tree(
    session: Session, *, subject: str
) -> ThemeTreeResponse:
    """获取当前已发布的主题树完整结构。"""
    version = curriculum_repo.get_current_theme_tree_version(session, subject)
    if version is None:
        logger.warning("current_theme_tree_not_found", subject=subject)
        raise NoPublishedTreeError(subject)

    tree_nodes = curriculum_repo.list_tree_nodes_by_version(
        session, version.id  # type: ignore[arg-type]
    )
    memberships = curriculum_repo.list_unit_memberships_by_version(
        session, version.id  # type: ignore[arg-type]
    )

    # 按 tree_node_id 分组 memberships
    node_units: dict[int, list[TreeUnitItem]] = {}
    for m in memberships:
        unit = curriculum_repo.get_teaching_unit_by_id(session, m.teaching_unit_id)
        item = TreeUnitItem(
            teaching_unit_id=m.teaching_unit_id,
            canonical_name=unit.canonical_name if unit else f"unit#{m.teaching_unit_id}",
            membership_role=m.membership_role,
            membership_source=m.membership_source,
            score=m.score,
        )
        node_units.setdefault(m.tree_node_id, []).append(item)

    # 构建 node_id → response 映射
    node_map: dict[int, ThemeTreeNodeResponse] = {}
    for tn in tree_nodes:
        node_map[tn.id] = ThemeTreeNodeResponse(  # type: ignore[arg-type]
            id=tn.id,  # type: ignore[arg-type]
            tree_version_id=tn.tree_version_id,
            anchor_id=tn.anchor_id,
            parent_tree_node_id=tn.parent_tree_node_id,
            title=tn.title,
            node_type=tn.node_type,
            order_index=tn.order_index,
            summary=tn.summary,
            units=node_units.get(tn.id, []),  # type: ignore[arg-type]
        )

    # 组装树结构
    roots: list[ThemeTreeNodeResponse] = []
    for tn in tree_nodes:
        resp = node_map[tn.id]  # type: ignore[index]
        if tn.parent_tree_node_id is not None and tn.parent_tree_node_id in node_map:
            node_map[tn.parent_tree_node_id].children.append(resp)
        else:
            roots.append(resp)

    logger.info(
        "current_theme_tree_loaded",
        subject=subject,
        version_id=version.id,
        version_no=version.version_no,
        tree_node_count=len(tree_nodes),
        membership_count=len(memberships),
        root_count=len(roots),
    )

    return ThemeTreeResponse(
        version_id=version.id,  # type: ignore[arg-type]
        version_no=version.version_no,
        subject=version.subject,
        status=version.status,
        created_at=version.created_at,
        tree=roots,
    )


# ---------------------------------------------------------------------------
# 锚点管理
# ---------------------------------------------------------------------------


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
    """锚点管理：list / create / update / delete。始终返回操作后的完整锚点列表。"""

    if action == "create":
        if not title:
            raise ValueError("创建锚点需要 title 参数。")
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
            raise ValueError("更新锚点需要 anchor_id 参数。")
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
            raise ValueError("删除锚点需要 anchor_id 参数。")
        curriculum_repo.delete_taxonomy_anchor(session, anchor_id)

    # action == "list" 或操作完成后，返回完整列表
    anchors = curriculum_repo.list_anchors_by_subject(session, subject)
    return [
        TaxonomyAnchorResponse(
            id=a.id,  # type: ignore[arg-type]
            subject=a.subject,
            anchor_type=a.anchor_type,
            title=a.title,
            parent_anchor_id=a.parent_anchor_id,
            order_index=a.order_index,
            confidence=a.confidence,
            is_system=a.is_system,
            status=a.status,
            created_at=a.created_at,
            updated_at=a.updated_at,
        )
        for a in anchors
    ]


# ---------------------------------------------------------------------------
# 先修 DAG 查询
# ---------------------------------------------------------------------------


def get_current_prereq_dag(
    session: Session, *, subject: str
) -> PrereqDagResponse:
    """获取当前已发布的先修 DAG 完整结构。"""
    version = curriculum_repo.get_current_prereq_dag_version(session, subject)
    if version is None:
        logger.warning("current_prereq_dag_not_found", subject=subject)
        raise NoPublishedDagError(subject)

    deps = curriculum_repo.list_dependencies_by_version(
        session, version.id  # type: ignore[arg-type]
    )

    items: list[UnitDependencyItem] = []
    for d in deps:
        src = curriculum_repo.get_teaching_unit_by_id(session, d.source_unit_id)
        tgt = curriculum_repo.get_teaching_unit_by_id(session, d.target_unit_id)
        items.append(
            UnitDependencyItem(
                id=d.id,  # type: ignore[arg-type]
                source_unit_id=d.source_unit_id,
                source_unit_name=src.canonical_name if src else f"unit#{d.source_unit_id}",
                target_unit_id=d.target_unit_id,
                target_unit_name=tgt.canonical_name if tgt else f"unit#{d.target_unit_id}",
                dependency_type=d.dependency_type,
                confidence=d.confidence,
                supporting_edge_count=d.supporting_edge_count,
            )
        )

    logger.info(
        "current_prereq_dag_loaded",
        subject=subject,
        version_id=version.id,
        version_no=version.version_no,
        dependency_count=len(items),
    )

    return PrereqDagResponse(
        version_id=version.id,  # type: ignore[arg-type]
        version_no=version.version_no,
        subject=version.subject,
        status=version.status,
        created_at=version.created_at,
        dependencies=items,
    )


# ---------------------------------------------------------------------------
# 课程快照查询
# ---------------------------------------------------------------------------


def get_current_curriculum_snapshot(
    session: Session, *, subject: str
) -> CurriculumSnapshotResponse:
    """获取当前已发布的课程快照（tree + dag 组合版本）。"""
    snapshot = curriculum_repo.get_current_curriculum_snapshot(session, subject)
    if snapshot is None:
        logger.warning("current_curriculum_snapshot_not_found", subject=subject)
        raise NoPublishedCurriculumSnapshotError(subject)

    logger.info(
        "current_curriculum_snapshot_loaded",
        subject=subject,
        snapshot_id=snapshot.id,
        version_no=snapshot.version_no,
        theme_tree_version_id=snapshot.theme_tree_version_id,
        prereq_dag_version_id=snapshot.prereq_dag_version_id,
    )

    return CurriculumSnapshotResponse(
        id=snapshot.id,  # type: ignore[arg-type]
        subject=snapshot.subject,
        version_no=snapshot.version_no,
        status=snapshot.status,
        theme_tree_version_id=snapshot.theme_tree_version_id,
        prereq_dag_version_id=snapshot.prereq_dag_version_id,
        syllabus_version_id=snapshot.syllabus_version_id,
        created_at=snapshot.created_at,
    )


# ---------------------------------------------------------------------------
# 清空学科知识数据
# ---------------------------------------------------------------------------


def clear_subject_knowledge(session: Session, *, subject: str) -> dict[str, int]:
    """清空指定学科的所有知识数据（图谱 + 课程结构 + 构建任务）。

    删除顺序按外键依赖从叶到根。
    """
    counts: dict[str, int] = {}

    def _delete_all(model: type, label: str) -> None:
        stmt = select(model).where(model.subject == subject)  # type: ignore[attr-defined]
        rows = list(session.exec(stmt).all())
        for row in rows:
            session.delete(row)
        counts[label] = len(rows)

    # ── 课程结构（从叶到根） ──

    # 1. UnitTreeMembership（通过 tree_version 关联 subject）
    tree_version_ids = [
        v.id for v in session.exec(
            select(ThemeTreeVersion).where(ThemeTreeVersion.subject == subject)
        ).all()
    ]
    if tree_version_ids:
        utm_rows = list(session.exec(
            select(UnitTreeMembership).where(
                UnitTreeMembership.tree_version_id.in_(tree_version_ids)  # type: ignore[union-attr]
            )
        ).all())
        for r in utm_rows:
            session.delete(r)
        counts["unit_tree_membership"] = len(utm_rows)

        # ThemeTreeNode
        ttn_rows = list(session.exec(
            select(ThemeTreeNode).where(
                ThemeTreeNode.tree_version_id.in_(tree_version_ids)  # type: ignore[union-attr]
            )
        ).all())
        for r in ttn_rows:
            session.delete(r)
        counts["theme_tree_node"] = len(ttn_rows)

    # 2. UnitDependency（通过 dag_version 关联 subject）
    dag_version_ids = [
        v.id for v in session.exec(
            select(PrereqDagVersion).where(PrereqDagVersion.subject == subject)
        ).all()
    ]
    if dag_version_ids:
        ud_rows = list(session.exec(
            select(UnitDependency).where(
                UnitDependency.dag_version_id.in_(dag_version_ids)  # type: ignore[union-attr]
            )
        ).all())
        for r in ud_rows:
            session.delete(r)
        counts["unit_dependency"] = len(ud_rows)

    session.commit()

    # 3. ThemeTreeVersion / PrereqDagVersion / CurriculumSnapshot
    _delete_all(CurriculumSnapshot, "curriculum_snapshot")
    _delete_all(ThemeTreeVersion, "theme_tree_version")
    _delete_all(PrereqDagVersion, "prereq_dag_version")
    session.commit()

    # 4. TeachingUnitMembership / TeachingUnitRevision / TeachingUnit
    unit_ids = [
        u.id for u in session.exec(
            select(TeachingUnit).where(TeachingUnit.subject == subject)
        ).all()
    ]
    if unit_ids:
        tum_rows = list(session.exec(
            select(TeachingUnitMembership).where(
                TeachingUnitMembership.unit_id.in_(unit_ids)  # type: ignore[union-attr]
            )
        ).all())
        for r in tum_rows:
            session.delete(r)
        counts["teaching_unit_membership"] = len(tum_rows)

        tur_rows = list(session.exec(
            select(TeachingUnitRevision).where(
                TeachingUnitRevision.unit_id.in_(unit_ids)  # type: ignore[union-attr]
            )
        ).all())
        for r in tur_rows:
            session.delete(r)
        counts["teaching_unit_revision"] = len(tur_rows)

    session.commit()

    _delete_all(TeachingUnit, "teaching_unit")
    session.commit()

    # 5. CurriculumDeriveJob / TaxonomyAnchor
    _delete_all(CurriculumDeriveJob, "curriculum_derive_job")
    _delete_all(TaxonomyAnchor, "taxonomy_anchor")
    session.commit()

    # ── 知识图谱 ──

    # 6. EvidenceLink（通过 subject 直接过滤）
    _delete_all(EvidenceLink, "evidence_link")

    # 7. EdgeRevision（通过 edge 关联 subject）
    edge_ids = [
        e.id for e in session.exec(
            select(KnowledgeEdge).where(KnowledgeEdge.subject == subject)
        ).all()
    ]
    if edge_ids:
        er_rows = list(session.exec(
            select(EdgeRevision).where(
                EdgeRevision.edge_id.in_(edge_ids)  # type: ignore[union-attr]
            )
        ).all())
        for r in er_rows:
            session.delete(r)
        counts["edge_revision"] = len(er_rows)

    # 8. KnowledgeRevision（通过 node 关联 subject）
    node_ids = [
        n.id for n in session.exec(
            select(KnowledgeNode).where(KnowledgeNode.subject == subject)
        ).all()
    ]
    if node_ids:
        kr_rows = list(session.exec(
            select(KnowledgeRevision).where(
                KnowledgeRevision.node_id.in_(node_ids)  # type: ignore[union-attr]
            )
        ).all())
        for r in kr_rows:
            session.delete(r)
        counts["knowledge_revision"] = len(kr_rows)

        ka_rows = list(session.exec(
            select(KnowledgeAlias).where(
                KnowledgeAlias.node_id.in_(node_ids)  # type: ignore[union-attr]
            )
        ).all())
        for r in ka_rows:
            session.delete(r)
        counts["knowledge_alias"] = len(ka_rows)

    session.commit()

    # 9. KnowledgeEdge / KnowledgeNode
    _delete_all(KnowledgeEdge, "knowledge_edge")
    _delete_all(KnowledgeNode, "knowledge_node")
    session.commit()

    # 10. GraphDigestJob / SubjectBuildLock
    _delete_all(GraphDigestJob, "graph_digest_job")
    _delete_all(SubjectBuildLock, "subject_build_lock")
    session.commit()

    # ── 文档与向量切块 ──
    document_ids = [
        d.id for d in session.exec(
            select(Document).where(Document.subject == subject)
        ).all()
    ]
    if document_ids:
        chunk_rows = list(session.exec(
            select(DocumentChunk).where(
                DocumentChunk.document_id.in_(document_ids)  # type: ignore[union-attr]
            )
        ).all())
        chunk_ids = [chunk.id for chunk in chunk_rows if chunk.id is not None]
        if chunk_ids:
            knowledge_repo.delete_embeddings_by_chunk_ids(session, chunk_ids)
            counts["chunk_embeddings"] = len(chunk_ids)
        for chunk in chunk_rows:
            session.delete(chunk)
        counts["document_chunk"] = len(chunk_rows)
        session.commit()

        document_rows = list(session.exec(
            select(Document).where(Document.id.in_(document_ids))  # type: ignore[union-attr]
        ).all())
        for document in document_rows:
            session.delete(document)
        counts["document"] = len(document_rows)
        session.commit()

    logger.info(
        "subject_knowledge_cleared",
        subject=subject,
        counts=counts,
    )
    return counts
