"""增量构建任务生命周期辅助函数。

包含：
- update_job_progress — 进度单调递增更新
- cleanup_pending_by_job — 按 job_id 精确清理 pending 数据
- cleanup_orphan_pending_by_subject — 管理员/恢复路径清理
- publish / archive 版本辅助函数（仅供 finalize_curriculum_node 调用）
- activate_*_entities_by_job — pending → active 批量激活
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

import structlog
from sqlmodel import Session, select, update

from app.models.curriculum import (
    CurriculumDeriveJob,
    CurriculumSnapshot,
    PrereqDagVersion,
    TeachingUnit,
    TeachingUnitMembership,
    ThemeTreeNode,
    ThemeTreeVersion,
    UnitDependency,
    UnitTreeMembership,
)
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

logger = structlog.get_logger()


# ── update_job_progress ──────────────────────────────────────────────


def update_job_progress(
    session: Session,
    *,
    job_id: int,
    job_type: Literal["graph", "curriculum"],
    progress: int,
    current_step: str,
) -> None:
    """更新任务进度，保证单调递增：传入值 <= 当前值则跳过。

    GraphDigestJob 和 CurriculumDeriveJob 统一通过此函数更新进度。
    """
    model = GraphDigestJob if job_type == "graph" else CurriculumDeriveJob
    job = session.get(model, job_id)
    if job is None:
        logger.warning("update_job_progress_skip_not_found", job_id=job_id, job_type=job_type)
        return
    if progress <= job.progress:
        return
    job.progress = progress
    job.current_step = current_step
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()


# ── cleanup_pending_by_job ───────────────────────────────────────────


def cleanup_pending_by_job(
    session: Session,
    *,
    job_id: int,
    job_type: Literal["graph", "curriculum"],
) -> int:
    """常规失败补偿：通过 created_by_job_id 精确清理 pending 数据。

    Returns:
        清理的总行数。
    """
    total = 0
    if job_type == "graph":
        total += _delete_by_job(session, EvidenceLink, job_id)
        total += _delete_by_job(session, KnowledgeAlias, job_id)
        # KnowledgeRevision / EdgeRevision 使用 digest_job_id 而非 created_by_job_id
        total += _delete_by_field(session, KnowledgeRevision, "digest_job_id", job_id)
        total += _delete_by_field(session, EdgeRevision, "digest_job_id", job_id)
        total += _delete_by_job(session, KnowledgeEdge, job_id, status_field="status", status_value="pending")
        total += _delete_by_job(session, KnowledgeNode, job_id, status_field="status", status_value="pending")
    else:
        total += _delete_by_job(session, UnitDependency, job_id)
        total += _delete_by_job(session, UnitTreeMembership, job_id)
        total += _delete_by_job(session, ThemeTreeNode, job_id)
        total += _delete_by_job_with_status(session, PrereqDagVersion, job_id, "draft")
        total += _delete_by_job_with_status(session, ThemeTreeVersion, job_id, "draft")
        total += _delete_by_job_with_status(session, CurriculumSnapshot, job_id, "draft")
        total += _delete_by_job(session, TeachingUnitMembership, job_id)
        total += _delete_by_job(session, TeachingUnit, job_id, status_field="status", status_value="pending")
    session.commit()
    logger.info("cleanup_pending_by_job", job_id=job_id, job_type=job_type, deleted=total)
    return total


def _delete_by_job(
    session: Session,
    model: type,
    job_id: int,
    *,
    status_field: str | None = None,
    status_value: str | None = None,
) -> int:
    """删除 created_by_job_id = job_id 的记录，可选按 status 过滤。"""
    stmt = select(model).where(model.created_by_job_id == job_id)  # type: ignore[attr-defined]
    if status_field and status_value:
        stmt = stmt.where(getattr(model, status_field) == status_value)
    rows = session.exec(stmt).all()
    for row in rows:
        session.delete(row)
    return len(rows)


def _delete_by_field(
    session: Session,
    model: type,
    field_name: str,
    job_id: int,
) -> int:
    """删除指定字段 = job_id 的记录（用于 digest_job_id 等非标准字段名）。"""
    stmt = select(model).where(getattr(model, field_name) == job_id)
    rows = session.exec(stmt).all()
    for row in rows:
        session.delete(row)
    return len(rows)


def _delete_by_job_with_status(
    session: Session,
    model: type,
    job_id: int,
    status_value: str,
) -> int:
    """删除 created_by_job_id = job_id 且 status = status_value 的版本记录。"""
    stmt = select(model).where(
        model.created_by_job_id == job_id,  # type: ignore[attr-defined]
        model.status == status_value,  # type: ignore[attr-defined]
    )
    rows = session.exec(stmt).all()
    for row in rows:
        session.delete(row)
    return len(rows)


# ── cleanup_orphan_pending_by_subject ────────────────────────────────


def cleanup_orphan_pending_by_subject(
    session: Session,
    *,
    subject: str,
    ttl_hours: float = 1.0,
) -> int:
    """管理员/恢复路径：清理满足以下全部条件的 pending 数据：

    1. 超过 TTL（默认 1 小时）
    2. 无对应 processing 状态的 job
    3. 不在当前锁持有期内
    """
    cutoff = datetime.utcnow() - timedelta(hours=ttl_hours)

    # 收集当前 processing 状态的 job ids
    processing_graph_ids = {
        j.id
        for j in session.exec(
            select(GraphDigestJob).where(
                GraphDigestJob.subject == subject,
                GraphDigestJob.status == "processing",
            )
        ).all()
    }
    processing_curriculum_ids = {
        j.id
        for j in session.exec(
            select(CurriculumDeriveJob).where(
                CurriculumDeriveJob.subject == subject,
                CurriculumDeriveJob.status == "processing",
            )
        ).all()
    }

    # 当前锁持有的 job_id
    lock = session.exec(
        select(SubjectBuildLock).where(SubjectBuildLock.subject == subject)
    ).first()
    locked_job_id = lock.job_id if lock else None

    exclude_graph_ids = processing_graph_ids | ({locked_job_id} if locked_job_id else set())
    exclude_curriculum_ids = processing_curriculum_ids

    total = 0
    total += _delete_orphan_pending(session, KnowledgeNode, subject, cutoff, exclude_graph_ids)
    total += _delete_orphan_pending(session, KnowledgeEdge, subject, cutoff, exclude_graph_ids)
    total += _delete_orphan_pending(session, KnowledgeAlias, subject, cutoff, exclude_graph_ids, subject_via_node=True)
    total += _delete_orphan_pending(session, EvidenceLink, subject, cutoff, exclude_graph_ids)
    total += _delete_orphan_pending(session, TeachingUnit, subject, cutoff, exclude_curriculum_ids)
    total += _delete_orphan_pending(session, TeachingUnitMembership, subject, cutoff, exclude_curriculum_ids, subject_via_unit=True)
    session.commit()
    logger.info("cleanup_orphan_pending_by_subject", subject=subject, deleted=total)
    return total


def _delete_orphan_pending(
    session: Session,
    model: type,
    subject: str,
    cutoff: datetime,
    exclude_job_ids: set[int],
    *,
    subject_via_node: bool = False,
    subject_via_unit: bool = False,
) -> int:
    """删除超过 TTL 且不属于 processing job 的 pending 记录。"""
    # 对于有 subject 字段的模型直接过滤
    if subject_via_node or subject_via_unit:
        # KnowledgeAlias / TeachingUnitMembership 没有 subject 字段，
        # 通过 created_by_job_id 和 created_at 过滤
        stmt = select(model).where(
            model.created_at < cutoff,  # type: ignore[attr-defined]
        )
    else:
        stmt = select(model).where(
            model.subject == subject,  # type: ignore[attr-defined]
            model.created_at < cutoff,  # type: ignore[attr-defined]
        )

    # 仅清理 pending/draft 状态
    if hasattr(model, "status"):
        stmt = stmt.where(model.status.in_(["pending", "draft"]))  # type: ignore[attr-defined]

    rows = session.exec(stmt).all()
    count = 0
    for row in rows:
        job_id = getattr(row, "created_by_job_id", None)
        if job_id in exclude_job_ids:
            continue
        session.delete(row)
        count += 1
    return count


# ── 版本发布与归档辅助函数 ───────────────────────────────────────────
# 硬规则：这些函数仅供 finalize_curriculum_node 调用，禁止 builder 内部调用


def publish_theme_tree_version(session: Session, *, version_id: int) -> None:
    """将 draft 主题树版本发布为 published。"""
    version = session.get(ThemeTreeVersion, version_id)
    if version is None:
        return
    version.status = "published"
    session.add(version)


def publish_prereq_dag_version(session: Session, *, version_id: int) -> None:
    """将 draft 先修 DAG 版本发布为 published。"""
    version = session.get(PrereqDagVersion, version_id)
    if version is None:
        return
    version.status = "published"
    session.add(version)


def publish_curriculum_snapshot(session: Session, *, snapshot_id: int) -> None:
    """将 draft 课程快照发布为 published。"""
    snapshot = session.get(CurriculumSnapshot, snapshot_id)
    if snapshot is None:
        return
    snapshot.status = "published"
    session.add(snapshot)


def archive_old_versions(
    session: Session,
    *,
    subject: str,
    current_tree_version_id: int | None = None,
    current_dag_version_id: int | None = None,
    current_snapshot_id: int | None = None,
) -> None:
    """将旧的 published 版本归档为 archived。

    排除当前正在发布的版本 ID。
    """
    if current_tree_version_id is not None:
        old_trees = session.exec(
            select(ThemeTreeVersion).where(
                ThemeTreeVersion.subject == subject,
                ThemeTreeVersion.status == "published",
                ThemeTreeVersion.id != current_tree_version_id,
            )
        ).all()
        for v in old_trees:
            v.status = "archived"
            session.add(v)

    if current_dag_version_id is not None:
        old_dags = session.exec(
            select(PrereqDagVersion).where(
                PrereqDagVersion.subject == subject,
                PrereqDagVersion.status == "published",
                PrereqDagVersion.id != current_dag_version_id,
            )
        ).all()
        for v in old_dags:
            v.status = "archived"
            session.add(v)

    if current_snapshot_id is not None:
        old_snapshots = session.exec(
            select(CurriculumSnapshot).where(
                CurriculumSnapshot.subject == subject,
                CurriculumSnapshot.status == "published",
                CurriculumSnapshot.id != current_snapshot_id,
            )
        ).all()
        for s in old_snapshots:
            s.status = "archived"
            session.add(s)


# ── pending → active 批量激活集中 helper ─────────────────────────────


def activate_graph_entities_by_job(session: Session, *, job_id: int) -> int:
    """集中激活 graph 层 pending 实体：nodes/edges/aliases/evidence_links。

    Returns:
        激活的总行数。
    """
    total = 0
    total += _activate_entities(session, KnowledgeNode, job_id)
    total += _activate_entities(session, KnowledgeEdge, job_id)
    total += _activate_aliases_by_job(session, job_id)
    total += _activate_evidence_by_job(session, job_id)
    session.commit()
    logger.info("activate_graph_entities_by_job", job_id=job_id, activated=total)
    return total


def activate_curriculum_entities_by_job(session: Session, *, job_id: int) -> int:
    """集中激活 curriculum 层 pending 实体：units/memberships/unit tree memberships/unit dependencies。

    Returns:
        激活的总行数。
    """
    total = 0
    total += _activate_entities(session, TeachingUnit, job_id)
    # TeachingUnitMembership 没有 status 字段，无需激活
    # UnitTreeMembership 没有 status 字段，无需激活
    # UnitDependency 没有 status 字段，无需激活
    session.commit()
    logger.info("activate_curriculum_entities_by_job", job_id=job_id, activated=total)
    return total


def _activate_entities(session: Session, model: type, job_id: int) -> int:
    """将 created_by_job_id = job_id 且 status = 'pending' 的记录激活为 'active'。"""
    stmt = select(model).where(
        model.created_by_job_id == job_id,  # type: ignore[attr-defined]
        model.status == "pending",  # type: ignore[attr-defined]
    )
    rows = session.exec(stmt).all()
    for row in rows:
        row.status = "active"
        if hasattr(row, "updated_at"):
            row.updated_at = datetime.utcnow()
        session.add(row)
    return len(rows)


def _activate_aliases_by_job(session: Session, job_id: int) -> int:
    """激活 KnowledgeAlias（status 字段为 AliasStatus）。"""
    stmt = select(KnowledgeAlias).where(
        KnowledgeAlias.created_by_job_id == job_id,
    )
    rows = session.exec(stmt).all()
    count = 0
    for row in rows:
        if row.status != "active":
            row.status = "active"
            session.add(row)
            count += 1
    return count


def _activate_evidence_by_job(session: Session, job_id: int) -> int:
    """确保 EvidenceLink 的 is_active 为 True。"""
    stmt = select(EvidenceLink).where(
        EvidenceLink.created_by_job_id == job_id,
        EvidenceLink.is_active == False,  # noqa: E712
    )
    rows = session.exec(stmt).all()
    for row in rows:
        row.is_active = True
        session.add(row)
    return len(rows)
