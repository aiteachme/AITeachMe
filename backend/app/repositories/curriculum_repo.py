"""课程结构数据访问层：教学单元/修订/成员/课程任务 CRUD。

Phase 2 实现教学单元部分；Phase 3/4 追加锚点、主题树、先修 DAG 函数。
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, func, select

from app.core.exceptions import DagVersionConflictError, TreeVersionConflictError
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

# ---------------------------------------------------------------------------
# 教学单元 CRUD
# ---------------------------------------------------------------------------


def create_teaching_unit(
    session: Session, unit: TeachingUnit
) -> TeachingUnit:
    session.add(unit)
    session.commit()
    session.refresh(unit)
    return unit


def get_teaching_unit_by_id(
    session: Session, unit_id: int
) -> TeachingUnit | None:
    return session.get(TeachingUnit, unit_id)


def find_unit_by_signature(
    session: Session, subject: str, member_signature: str
) -> TeachingUnit | None:
    """通过结构签名定位教学单元（稳定身份查找）。"""
    stmt = select(TeachingUnit).where(
        TeachingUnit.subject == subject,
        TeachingUnit.member_signature == member_signature,
    )
    return session.exec(stmt).first()


def find_units_overlapping_nodes(
    session: Session, subject: str, node_ids: list[int]
) -> list[TeachingUnit]:
    """查找成员节点与给定 node_ids 有交集的教学单元。"""
    if not node_ids:
        return []
    stmt = (
        select(TeachingUnit)
        .join(
            TeachingUnitMembership,
            TeachingUnitMembership.unit_id == TeachingUnit.id,
        )
        .where(
            TeachingUnit.subject == subject,
            TeachingUnitMembership.knowledge_node_id.in_(node_ids),  # type: ignore[union-attr]
        )
        .distinct()
    )
    return list(session.exec(stmt).all())


def find_unit_by_normalized_name(
    session: Session, subject: str, normalized_name: str
) -> TeachingUnit | None:
    """辅助搜索（非身份定位），按 normalized_name 查找 active/pending 单元。"""
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
    """分页查询教学单元。默认只返回 active，传 status=None 返回全部。"""
    base = select(TeachingUnit).where(TeachingUnit.subject == subject)
    count_base = select(func.count(TeachingUnit.id)).where(
        TeachingUnit.subject == subject
    )

    if status is not None:
        base = base.where(TeachingUnit.status == status)
        count_base = count_base.where(TeachingUnit.status == status)

    total: int = session.exec(count_base).one()
    rows = list(
        session.exec(
            base.offset(offset).limit(limit).order_by(TeachingUnit.id)
        ).all()
    )
    return rows, total


# ---------------------------------------------------------------------------
# 教学单元修订
# ---------------------------------------------------------------------------


def create_unit_revision(
    session: Session, revision: TeachingUnitRevision
) -> TeachingUnitRevision:
    session.add(revision)
    session.commit()
    session.refresh(revision)
    return revision


def deactivate_old_unit_revisions(session: Session, unit_id: int) -> None:
    """将指定教学单元的所有修订标记为非当前。"""
    stmt = select(TeachingUnitRevision).where(
        TeachingUnitRevision.unit_id == unit_id,
        TeachingUnitRevision.is_current == True,  # noqa: E712
    )
    for rev in session.exec(stmt).all():
        rev.is_current = False
        session.add(rev)
    session.commit()


# ---------------------------------------------------------------------------
# 教学单元成员
# ---------------------------------------------------------------------------


def create_unit_membership(
    session: Session, membership: TeachingUnitMembership
) -> TeachingUnitMembership:
    session.add(membership)
    session.commit()
    session.refresh(membership)
    return membership


def list_memberships_by_unit(
    session: Session, unit_id: int
) -> list[TeachingUnitMembership]:
    stmt = select(TeachingUnitMembership).where(
        TeachingUnitMembership.unit_id == unit_id
    )
    return list(session.exec(stmt).all())


def find_unit_by_node(
    session: Session, knowledge_node_id: int
) -> TeachingUnit | None:
    """查找包含指定知识节点（任意角色）的 active 教学单元。"""
    stmt = (
        select(TeachingUnit)
        .join(
            TeachingUnitMembership,
            TeachingUnitMembership.unit_id == TeachingUnit.id,
        )
        .where(
            TeachingUnitMembership.knowledge_node_id == knowledge_node_id,
            TeachingUnit.status == "active",
        )
    )
    return session.exec(stmt).first()


# ---------------------------------------------------------------------------
# 课程派生任务
# ---------------------------------------------------------------------------


def create_curriculum_job(
    session: Session, job: CurriculumDeriveJob
) -> CurriculumDeriveJob:
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def update_curriculum_job(
    session: Session, job_id: int, **kwargs: object
) -> CurriculumDeriveJob | None:
    job = session.get(CurriculumDeriveJob, job_id)
    if job is None:
        return None
    for key, value in kwargs.items():
        setattr(job, key, value)
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


# ---------------------------------------------------------------------------
# 分类锚点
# ---------------------------------------------------------------------------


def create_taxonomy_anchor(
    session: Session, anchor: TaxonomyAnchor
) -> TaxonomyAnchor:
    session.add(anchor)
    session.commit()
    session.refresh(anchor)
    return anchor


def list_anchors_by_subject(
    session: Session, subject: str
) -> list[TaxonomyAnchor]:
    stmt = (
        select(TaxonomyAnchor)
        .where(TaxonomyAnchor.subject == subject)
        .order_by(TaxonomyAnchor.order_index)
    )
    return list(session.exec(stmt).all())


def get_uncategorized_anchor(
    session: Session, subject: str
) -> TaxonomyAnchor:
    """获取学科的"待归类"系统锚点。如果不存在则自动创建。"""
    stmt = select(TaxonomyAnchor).where(
        TaxonomyAnchor.subject == subject,
        TaxonomyAnchor.anchor_type == "system",
        TaxonomyAnchor.is_system == True,  # noqa: E712
    )
    anchor = session.exec(stmt).first()
    if anchor is not None:
        return anchor
    # 自动创建系统锚点
    anchor = TaxonomyAnchor(
        subject=subject,
        anchor_type="system",
        title="待归类",
        normalized_title="待归类",
        is_system=True,
        status="active",
    )
    session.add(anchor)
    session.commit()
    session.refresh(anchor)
    return anchor


# ---------------------------------------------------------------------------
# 主题树
# ---------------------------------------------------------------------------


def create_theme_tree_version(
    session: Session, version: ThemeTreeVersion
) -> ThemeTreeVersion:
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def get_current_theme_tree_version(
    session: Session, subject: str
) -> ThemeTreeVersion | None:
    """获取当前已发布的主题树版本。"""
    stmt = select(ThemeTreeVersion).where(
        ThemeTreeVersion.subject == subject,
        ThemeTreeVersion.status == "published",
    )
    return session.exec(stmt).first()


def create_theme_tree_version_with_optimistic_lock(
    session: Session,
    subject: str,
    expected_prev_version_no: int,
) -> ThemeTreeVersion:
    """使用乐观锁创建新主题树版本。

    检查当前最大 version_no 是否等于 expected_prev_version_no，
    不匹配则抛出 TreeVersionConflictError。
    """
    stmt = select(func.max(ThemeTreeVersion.version_no)).where(
        ThemeTreeVersion.subject == subject,
    )
    current_max: int | None = session.exec(stmt).one()
    actual_prev = current_max if current_max is not None else 0

    if actual_prev != expected_prev_version_no:
        raise TreeVersionConflictError(subject)

    new_version = ThemeTreeVersion(
        subject=subject,
        version_no=actual_prev + 1,
        status="draft",
    )
    session.add(new_version)
    session.commit()
    session.refresh(new_version)
    return new_version


def create_theme_tree_node(
    session: Session, node: ThemeTreeNode
) -> ThemeTreeNode:
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def create_unit_tree_membership(
    session: Session, membership: UnitTreeMembership
) -> UnitTreeMembership:
    session.add(membership)
    session.commit()
    session.refresh(membership)
    return membership


def list_tree_nodes_by_version(
    session: Session, tree_version_id: int
) -> list[ThemeTreeNode]:
    """获取指定树版本的所有节点，按 order_index 排序。"""
    stmt = (
        select(ThemeTreeNode)
        .where(ThemeTreeNode.tree_version_id == tree_version_id)
        .order_by(ThemeTreeNode.order_index)
    )
    return list(session.exec(stmt).all())


def list_unit_memberships_by_version(
    session: Session, tree_version_id: int
) -> list[UnitTreeMembership]:
    """获取指定树版本的所有教学单元挂载关系。"""
    stmt = select(UnitTreeMembership).where(
        UnitTreeMembership.tree_version_id == tree_version_id
    )
    return list(session.exec(stmt).all())


def update_taxonomy_anchor(
    session: Session, anchor_id: int, **kwargs: object
) -> TaxonomyAnchor | None:
    """更新锚点字段。"""
    anchor = session.get(TaxonomyAnchor, anchor_id)
    if anchor is None:
        return None
    for key, value in kwargs.items():
        setattr(anchor, key, value)
    anchor.updated_at = datetime.utcnow()
    session.add(anchor)
    session.commit()
    session.refresh(anchor)
    return anchor


def delete_taxonomy_anchor(session: Session, anchor_id: int) -> bool:
    """删除锚点（仅非系统锚点可删除）。返回是否成功。"""
    anchor = session.get(TaxonomyAnchor, anchor_id)
    if anchor is None or anchor.is_system:
        return False
    session.delete(anchor)
    session.commit()
    return True


# ---------------------------------------------------------------------------
# 课程快照
# ---------------------------------------------------------------------------


def create_curriculum_snapshot(
    session: Session, snapshot: CurriculumSnapshot
) -> CurriculumSnapshot:
    session.add(snapshot)
    session.commit()
    session.refresh(snapshot)
    return snapshot


def get_current_curriculum_snapshot(
    session: Session, subject: str
) -> CurriculumSnapshot | None:
    """获取当前已发布的课程快照。"""
    stmt = select(CurriculumSnapshot).where(
        CurriculumSnapshot.subject == subject,
        CurriculumSnapshot.status == "published",
    )
    return session.exec(stmt).first()


# ---------------------------------------------------------------------------
# 先修 DAG
# ---------------------------------------------------------------------------


def create_prereq_dag_version(
    session: Session, version: PrereqDagVersion
) -> PrereqDagVersion:
    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def get_current_prereq_dag_version(
    session: Session, subject: str
) -> PrereqDagVersion | None:
    """获取当前已发布的先修 DAG 版本。"""
    stmt = select(PrereqDagVersion).where(
        PrereqDagVersion.subject == subject,
        PrereqDagVersion.status == "published",
    )
    return session.exec(stmt).first()


def create_prereq_dag_version_with_optimistic_lock(
    session: Session,
    subject: str,
    expected_prev_version_no: int,
) -> PrereqDagVersion:
    """使用乐观锁创建新先修 DAG 版本。

    检查当前最大 version_no 是否等于 expected_prev_version_no，
    不匹配则抛出 DagVersionConflictError。
    """
    stmt = select(func.max(PrereqDagVersion.version_no)).where(
        PrereqDagVersion.subject == subject,
    )
    current_max: int | None = session.exec(stmt).one()
    actual_prev = current_max if current_max is not None else 0

    if actual_prev != expected_prev_version_no:
        raise DagVersionConflictError(subject)

    new_version = PrereqDagVersion(
        subject=subject,
        version_no=actual_prev + 1,
        status="draft",
    )
    session.add(new_version)
    session.commit()
    session.refresh(new_version)
    return new_version


def create_unit_dependency(
    session: Session, dep: UnitDependency
) -> UnitDependency:
    session.add(dep)
    session.commit()
    session.refresh(dep)
    return dep


def list_dependencies_by_version(
    session: Session, dag_version_id: int
) -> list[UnitDependency]:
    """获取指定 DAG 版本的所有依赖边。"""
    stmt = (
        select(UnitDependency)
        .where(UnitDependency.dag_version_id == dag_version_id)
        .order_by(UnitDependency.id)
    )
    return list(session.exec(stmt).all())


def list_dependencies_by_unit(
    session: Session, dag_version_id: int, unit_id: int
) -> list[UnitDependency]:
    """获取指定 DAG 版本中与某教学单元相关的所有依赖边（作为 source 或 target）。"""
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
