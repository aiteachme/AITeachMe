"""知识图谱数据访问层：节点/边/修订/证据/别名/构建锁/任务 CRUD。"""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import Session, func, select, or_

from app.utils.time import utcnow

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

# ---------------------------------------------------------------------------
# 构建锁
# ---------------------------------------------------------------------------

_DEFAULT_LOCK_TTL_MINUTES = 30


def acquire_subject_build_lock(
    session: Session,
    subject: str,
    job_id: int,
    *,
    ttl_minutes: int = _DEFAULT_LOCK_TTL_MINUTES,
) -> bool:
    """尝试获取 subject 级构建锁。

    如果锁不存在则创建；如果已存在且未过期则返回 False；
    如果已过期则抢占。返回 True 表示获取成功。
    """
    now = utcnow()
    lock = session.exec(
        select(SubjectBuildLock).where(SubjectBuildLock.subject == subject)
    ).first()

    if lock is None:
        lock = SubjectBuildLock(
            subject=subject,
            job_id=job_id,
            locked_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
        )
        session.add(lock)
        session.commit()
        session.refresh(lock)
        return True

    # 锁已存在：检查是否过期
    if lock.expires_at is not None and lock.expires_at > now:
        return False

    # 过期锁 → 抢占
    lock.job_id = job_id
    lock.locked_at = now
    lock.expires_at = now + timedelta(minutes=ttl_minutes)
    session.add(lock)
    session.commit()
    return True


def release_subject_build_lock(session: Session, subject: str) -> None:
    """释放 subject 级构建锁。"""
    lock = session.exec(
        select(SubjectBuildLock).where(SubjectBuildLock.subject == subject)
    ).first()
    if lock is not None:
        session.delete(lock)
        session.commit()


# ---------------------------------------------------------------------------
# 节点 CRUD
# ---------------------------------------------------------------------------


def create_knowledge_node(
    session: Session, node: KnowledgeNode
) -> KnowledgeNode:
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def get_knowledge_node_by_id(
    session: Session, node_id: int
) -> KnowledgeNode | None:
    return session.get(KnowledgeNode, node_id)


def find_node_by_normalized_name(
    session: Session,
    subject: str,
    normalized_name: str,
    node_type: str,
    *,
    include_pending: bool = True,
) -> KnowledgeNode | None:
    """按 normalized_name + node_type 查找节点。

    默认只匹配 active | pending，不匹配 merged | deprecated。
    """
    allowed = ["active"]
    if include_pending:
        allowed.append("pending")
    stmt = (
        select(KnowledgeNode)
        .where(
            KnowledgeNode.subject == subject,
            KnowledgeNode.normalized_name == normalized_name,
            KnowledgeNode.node_type == node_type,
            KnowledgeNode.status.in_(allowed),  # type: ignore[union-attr]
        )
    )
    return session.exec(stmt).first()


def find_nodes_by_alias(
    session: Session,
    subject: str,
    normalized_alias: str,
    node_type: str,
) -> list[KnowledgeNode]:
    """通过别名表查找匹配的 active/pending 节点。"""
    stmt = (
        select(KnowledgeNode)
        .join(KnowledgeAlias, KnowledgeAlias.node_id == KnowledgeNode.id)
        .where(
            KnowledgeNode.subject == subject,
            KnowledgeNode.node_type == node_type,
            KnowledgeAlias.normalized_alias == normalized_alias,
            KnowledgeAlias.status == "active",
            KnowledgeNode.status.in_(["active", "pending"]),  # type: ignore[union-attr]
        )
    )
    return list(session.exec(stmt).all())


def list_nodes_by_subject(
    session: Session,
    subject: str,
    *,
    node_type: str | None = None,
    status: str | None = "active",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[KnowledgeNode], int]:
    """分页查询节点。默认只返回 active，传 status=None 返回全部。"""
    base = select(KnowledgeNode).where(KnowledgeNode.subject == subject)
    count_base = select(func.count(KnowledgeNode.id)).where(
        KnowledgeNode.subject == subject
    )

    if status is not None:
        base = base.where(KnowledgeNode.status == status)
        count_base = count_base.where(KnowledgeNode.status == status)
    if node_type is not None:
        base = base.where(KnowledgeNode.node_type == node_type)
        count_base = count_base.where(KnowledgeNode.node_type == node_type)

    total: int = session.exec(count_base).one()
    rows = list(
        session.exec(base.offset(offset).limit(limit).order_by(KnowledgeNode.id)).all()
    )
    return rows, total


def get_node_with_current_revision(
    session: Session, node_id: int
) -> tuple[KnowledgeNode, KnowledgeRevision] | None:
    """返回节点及其当前修订。repo 层不拦截非 active 节点，由服务层判断。"""
    node = session.get(KnowledgeNode, node_id)
    if node is None:
        return None
    if node.current_revision_id is None:
        # fallback: 查 is_current=True 的修订
        rev = session.exec(
            select(KnowledgeRevision).where(
                KnowledgeRevision.node_id == node_id,
                KnowledgeRevision.is_current == True,  # noqa: E712
            )
        ).first()
    else:
        rev = session.get(KnowledgeRevision, node.current_revision_id)
    if rev is None:
        return None
    return node, rev


# ---------------------------------------------------------------------------
# 别名 CRUD
# ---------------------------------------------------------------------------


def create_alias(session: Session, alias: KnowledgeAlias) -> KnowledgeAlias:
    session.add(alias)
    session.commit()
    session.refresh(alias)
    return alias


def find_alias(
    session: Session, subject: str, normalized_alias: str
) -> list[KnowledgeAlias]:
    """在指定学科下查找别名记录（通过 join node 限定 subject）。"""
    stmt = (
        select(KnowledgeAlias)
        .join(KnowledgeNode, KnowledgeAlias.node_id == KnowledgeNode.id)
        .where(
            KnowledgeNode.subject == subject,
            KnowledgeAlias.normalized_alias == normalized_alias,
            KnowledgeAlias.status == "active",
        )
    )
    return list(session.exec(stmt).all())


def list_aliases_by_node(
    session: Session, node_id: int
) -> list[KnowledgeAlias]:
    stmt = select(KnowledgeAlias).where(KnowledgeAlias.node_id == node_id)
    return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# 边 CRUD
# ---------------------------------------------------------------------------


def create_knowledge_edge(
    session: Session, edge: KnowledgeEdge
) -> KnowledgeEdge:
    session.add(edge)
    session.commit()
    session.refresh(edge)
    return edge


def find_edge(
    session: Session,
    source_node_id: int,
    target_node_id: int,
    edge_type: str,
) -> KnowledgeEdge | None:
    """按 source + target + edge_type 精确查找边。"""
    stmt = select(KnowledgeEdge).where(
        KnowledgeEdge.source_node_id == source_node_id,
        KnowledgeEdge.target_node_id == target_node_id,
        KnowledgeEdge.edge_type == edge_type,
    )
    return session.exec(stmt).first()


def list_edges_by_node(
    session: Session,
    node_id: int,
    *,
    status: str | None = "active",
) -> list[KnowledgeEdge]:
    """查询与指定节点关联的所有边（入边 + 出边）。默认只返回 active。"""
    stmt = select(KnowledgeEdge).where(
        or_(
            KnowledgeEdge.source_node_id == node_id,
            KnowledgeEdge.target_node_id == node_id,
        )
    )
    if status is not None:
        stmt = stmt.where(KnowledgeEdge.status == status)
    return list(session.exec(stmt).all())


def list_edges_by_type(
    session: Session,
    subject: str,
    edge_type: str,
    *,
    status: str | None = "active",
) -> list[KnowledgeEdge]:
    """按边类型查询。默认只返回 active。"""
    stmt = select(KnowledgeEdge).where(
        KnowledgeEdge.subject == subject,
        KnowledgeEdge.edge_type == edge_type,
    )
    if status is not None:
        stmt = stmt.where(KnowledgeEdge.status == status)
    return list(session.exec(stmt).all())


def list_all_edges_by_subject(
    session: Session,
    subject: str,
    *,
    status: str | None = "active",
) -> list[KnowledgeEdge]:
    """查询学科下所有边。默认只返回 active。"""
    stmt = select(KnowledgeEdge).where(KnowledgeEdge.subject == subject)
    if status is not None:
        stmt = stmt.where(KnowledgeEdge.status == status)
    return list(session.exec(stmt).all())


# ---------------------------------------------------------------------------
# 修订
# ---------------------------------------------------------------------------


def create_knowledge_revision(
    session: Session, revision: KnowledgeRevision
) -> KnowledgeRevision:
    session.add(revision)
    session.commit()
    session.refresh(revision)
    return revision


def deactivate_old_revisions(session: Session, node_id: int) -> None:
    """将指定节点的所有修订标记为非当前。"""
    stmt = select(KnowledgeRevision).where(
        KnowledgeRevision.node_id == node_id,
        KnowledgeRevision.is_current == True,  # noqa: E712
    )
    for rev in session.exec(stmt).all():
        rev.is_current = False
        session.add(rev)
    session.commit()


def create_edge_revision(
    session: Session, revision: EdgeRevision
) -> EdgeRevision:
    session.add(revision)
    session.commit()
    session.refresh(revision)
    return revision


def deactivate_old_edge_revisions(session: Session, edge_id: int) -> None:
    """将指定边的所有修订标记为非当前。"""
    stmt = select(EdgeRevision).where(
        EdgeRevision.edge_id == edge_id,
        EdgeRevision.is_current == True,  # noqa: E712
    )
    for rev in session.exec(stmt).all():
        rev.is_current = False
        session.add(rev)
    session.commit()


# ---------------------------------------------------------------------------
# 证据
# ---------------------------------------------------------------------------


def create_evidence_link(
    session: Session, link: EvidenceLink
) -> EvidenceLink:
    session.add(link)
    session.commit()
    session.refresh(link)
    return link


def list_evidence_by_entity(
    session: Session,
    entity_type: str,
    entity_id: int,
    *,
    is_active: bool | None = True,
) -> list[EvidenceLink]:
    stmt = select(EvidenceLink).where(
        EvidenceLink.entity_type == entity_type,
        EvidenceLink.entity_id == entity_id,
    )
    if is_active is not None:
        stmt = stmt.where(EvidenceLink.is_active == is_active)
    return list(session.exec(stmt).all())


def count_active_evidence(
    session: Session, entity_type: str, entity_id: int
) -> int:
    stmt = select(func.count(EvidenceLink.id)).where(
        EvidenceLink.entity_type == entity_type,
        EvidenceLink.entity_id == entity_id,
        EvidenceLink.is_active == True,  # noqa: E712
    )
    return session.exec(stmt).one()


# ---------------------------------------------------------------------------
# 任务
# ---------------------------------------------------------------------------


def find_job_by_idempotency_key(
    session: Session, idempotency_key: str
) -> GraphDigestJob | None:
    stmt = select(GraphDigestJob).where(
        GraphDigestJob.idempotency_key == idempotency_key
    )
    return session.exec(stmt).first()


def create_digest_job(
    session: Session, job: GraphDigestJob
) -> GraphDigestJob:
    """创建增量构建任务，含幂等键检查。

    如果 idempotency_key 已存在，返回已有 job 而非创建新的。
    """
    existing = find_job_by_idempotency_key(session, job.idempotency_key)
    if existing is not None:
        return existing
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def update_digest_job(
    session: Session, job_id: int, **kwargs: object
) -> GraphDigestJob | None:
    job = session.get(GraphDigestJob, job_id)
    if job is None:
        return None
    for key, value in kwargs.items():
        setattr(job, key, value)
    job.updated_at = utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    return job
