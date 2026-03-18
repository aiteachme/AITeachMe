"""知识图谱服务层（Phase 1）：增量构建触发、状态查询、图谱查询。"""

from __future__ import annotations

import hashlib
import json
import traceback

import structlog
from sqlmodel import Session, select

from app.agents.digest.kg_workflow import KGDigestState, build_kg_digest_graph
from app.core.database import get_session
from app.agents.digest.curriculum_workflow import (
    CurriculumDeriveState,
    build_curriculum_derive_graph,
)
from app.core.exceptions import (
    DigestJobNotFoundError,
    EvidenceNotFoundError,
    KnowledgeNodeNotFoundError,
    NoPublishedCurriculumSnapshotError,
    NoPublishedDagError,
    NoPublishedTreeError,
    SubjectBuildLockConflictError,
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
from app.repositories import curriculum_repo, kg_repo, knowledge_repo
from app.schemas.common import PaginatedData, build_paginated_data
from app.utils.kg_helpers import normalize_name
from app.schemas.knowledge_graph import (
    AliasItem,
    CurriculumJobResponse,
    CurriculumSnapshotResponse,
    DigestBuildData,
    DigestStatusResponse,
    EvidenceContextResponse,
    EvidenceSummary,
    FullGraphResponse,
    GraphDigestJobResponse,
    GraphEdgeResponse,
    IncidentEdgeItem,
    KnowledgeNodeDetailResponse,
    KnowledgeNodeResponse,
    NodeRevisionItem,
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

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# 幂等键生成
# ---------------------------------------------------------------------------


def _compute_idempotency_key(subject: str, file_ids: list[int]) -> str:
    """基于 subject + 排序后 file_ids 计算幂等键。"""
    sorted_ids = sorted(file_ids)
    raw = f"{subject}:{json.dumps(sorted_ids)}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# 触发增量构建
# ---------------------------------------------------------------------------


def trigger_digest_build(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
    idempotency_key: str | None = None,
) -> DigestBuildData:
    """触发增量构建：三层检查（幂等键命中 → 运行中冲突 → 创建新 job）。

    不在此处获取构建锁，锁由工作流 acquire_lock_node 获取。
    """
    key = idempotency_key or _compute_idempotency_key(subject, file_ids)

    # 1) 幂等键命中 → 返回已有 job
    existing = kg_repo.find_job_by_idempotency_key(session, key)
    if existing is not None:
        return DigestBuildData(
            job_id=existing.id,  # type: ignore[arg-type]
            is_existing=True,
        )

    # 2) 同 subject 是否有运行中的 job → 409
    running = session.exec(
        select(GraphDigestJob).where(
            GraphDigestJob.subject == subject,
            GraphDigestJob.status == "processing",
        )
    ).first()
    if running is not None:
        raise SubjectBuildLockConflictError(subject)

    # 3) 创建新 job
    job = kg_repo.create_digest_job(
        session,
        GraphDigestJob(
            subject=subject,
            idempotency_key=key,
            status="pending",
            input_file_ids_json=json.dumps(sorted(file_ids)),
        ),
    )
    return DigestBuildData(job_id=job.id, is_existing=False)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 后台执行图谱构建
# ---------------------------------------------------------------------------


async def run_graph_digest_background(*, subject: str, job_id: int) -> None:
    """后台异步执行 GraphDigestJob 工作流。"""
    session = get_session()
    try:
        job = session.get(GraphDigestJob, job_id)
        if job is None:
            logger.error("graph_digest_job_not_found", job_id=job_id)
            return

        # 解析 file_ids
        file_ids: list[int] = json.loads(job.input_file_ids_json or "[]")

        # 构建初始状态
        initial_state: KGDigestState = {
            "subject": subject,
            "file_ids": file_ids,
            "job_id": job_id,
            "chunk_ids": [],
            "candidates": [],
            "all_candidate_edges": [],
            "clustered_candidates": [],
            "candidate_name_to_cluster_id": {},
            "candidate_name_to_resolved_node_id": {},
            "cluster_id_to_resolved_node_id": {},
            "new_node_ids": [],
            "updated_node_ids": [],
            "merged_node_ids": [],
            "new_edge_ids": [],
            "updated_edge_ids": [],
            "impact_set": None,
            "lock_acquired": False,
            "error": None,
        }

        graph = build_kg_digest_graph()
        compiled = graph.compile()
        await compiled.ainvoke(initial_state)

    except Exception:
        logger.exception("graph_digest_background_error", job_id=job_id)
        # 尝试标记 job 为 failed
        try:
            kg_repo.update_digest_job(
                session,
                job_id,
                status="failed",
                error_message=traceback.format_exc()[-500:],
            )
        except Exception:
            logger.exception("failed_to_mark_job_failed", job_id=job_id)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 状态查询
# ---------------------------------------------------------------------------


def _build_graph_job_response(job: GraphDigestJob) -> GraphDigestJobResponse:
    return GraphDigestJobResponse(
        id=job.id,  # type: ignore[arg-type]
        subject=job.subject,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        input_chunk_count=job.input_chunk_count,
        nodes_added=job.nodes_added,
        nodes_updated=job.nodes_updated,
        nodes_merged=job.nodes_merged,
        edges_added=job.edges_added,
        edges_updated=job.edges_updated,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _build_curriculum_job_response(
    job: CurriculumDeriveJob,
) -> CurriculumJobResponse:
    return CurriculumJobResponse(
        id=job.id,  # type: ignore[arg-type]
        subject=job.subject,
        graph_job_id=job.graph_job_id,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        units_added=job.units_added,
        units_updated=job.units_updated,
        theme_tree_version_id=job.theme_tree_version_id,
        prereq_dag_version_id=job.prereq_dag_version_id,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def get_digest_status(
    session: Session, *, subject: str, job_id: int
) -> DigestStatusResponse:
    """聚合查询：GraphDigestJob + 关联 CurriculumDeriveJob + 当前快照 ID。"""
    job = session.get(GraphDigestJob, job_id)
    if job is None or job.subject != subject:
        raise DigestJobNotFoundError(job_id)

    graph_resp = _build_graph_job_response(job)

    # 关联 CurriculumDeriveJob（Phase 1 可能为空）
    curriculum_resp: CurriculumJobResponse | None = None
    if job.curriculum_job_id is not None:
        cjob = session.get(CurriculumDeriveJob, job.curriculum_job_id)
        if cjob is not None:
            curriculum_resp = _build_curriculum_job_response(cjob)

    # 当前 published 快照（Phase 1 固定为 None）
    snapshot = session.exec(
        select(CurriculumSnapshot).where(
            CurriculumSnapshot.subject == subject,
            CurriculumSnapshot.status == "published",
        )
    ).first()
    snapshot_id = snapshot.id if snapshot is not None else None

    return DigestStatusResponse(
        graph_job=graph_resp,
        curriculum_job=curriculum_resp,
        current_curriculum_snapshot_id=snapshot_id,
    )


# ---------------------------------------------------------------------------
# 图谱查询
# ---------------------------------------------------------------------------


def get_graph_nodes(
    session: Session,
    *,
    subject: str,
    node_type: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PaginatedData[KnowledgeNodeResponse]:
    """分页查询知识节点。"""
    offset = (page - 1) * size
    nodes, total = kg_repo.list_nodes_by_subject(
        session, subject, node_type=node_type, limit=size, offset=offset,
    )
    items = [
        KnowledgeNodeResponse(
            id=n.id,  # type: ignore[arg-type]
            subject=n.subject,
            node_type=n.node_type,
            canonical_name=n.canonical_name,
            status=n.status,
            confidence=n.confidence,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n in nodes
    ]
    return build_paginated_data(items=items, page=page, size=size, total=total)


def get_graph_node_detail(
    session: Session, *, subject: str, node_id: int
) -> KnowledgeNodeDetailResponse:
    """节点详情：base info + revision + aliases + evidence + incident edges。"""
    result = kg_repo.get_node_with_current_revision(session, node_id)
    if result is None:
        raise KnowledgeNodeNotFoundError(node_id)

    node, revision = result
    if node.subject != subject:
        raise KnowledgeNodeNotFoundError(node_id)

    # 当前修订
    current_rev = NodeRevisionItem(
        title=revision.title,
        summary=revision.summary,
        body=revision.body,
    )

    # 别名
    aliases_raw = kg_repo.list_aliases_by_node(session, node_id)
    aliases = [
        AliasItem(
            id=a.id,  # type: ignore[arg-type]
            alias=a.alias,
            language=a.language,
            source=a.source,
            confidence=a.confidence,
            is_primary=a.is_primary,
        )
        for a in aliases_raw
    ]

    # 活跃证据
    evidence_raw = kg_repo.list_evidence_by_entity(session, "node", node_id)
    evidence = [
        EvidenceSummary(
            id=e.id,  # type: ignore[arg-type]
            document_id=e.document_id,
            chunk_id=e.chunk_id,
            quote_text=e.quote_text,
            evidence_role=e.evidence_role,
            field_scope=e.field_scope,
            confidence=e.confidence,
        )
        for e in evidence_raw
    ]

    # 关联边
    edges_raw = kg_repo.list_edges_by_node(session, node_id)
    incident_edges: list[IncidentEdgeItem] = []
    for edge in edges_raw:
        if edge.source_node_id == node_id:
            other_id = edge.target_node_id
            direction = "outgoing"
        else:
            other_id = edge.source_node_id
            direction = "incoming"

        other_node = session.get(KnowledgeNode, other_id)
        other_name = other_node.canonical_name if other_node else f"node#{other_id}"
        other_type = other_node.node_type if other_node else "unknown"

        incident_edges.append(
            IncidentEdgeItem(
                id=edge.id,  # type: ignore[arg-type]
                edge_type=edge.edge_type,
                direction=direction,
                other_node_id=other_id,
                other_node_name=other_name,
                other_node_type=other_type,
                confidence=edge.confidence,
            )
        )

    return KnowledgeNodeDetailResponse(
        id=node.id,  # type: ignore[arg-type]
        subject=node.subject,
        node_type=node.node_type,
        canonical_name=node.canonical_name,
        normalized_name=node.normalized_name,
        status=node.status,
        confidence=node.confidence,
        current_revision=current_rev,
        aliases=aliases,
        evidence=evidence,
        incident_edges=incident_edges,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


# ---------------------------------------------------------------------------
# 后台执行课程派生
# ---------------------------------------------------------------------------


async def run_curriculum_derive_background(
    *, subject: str, graph_job_id: int, curriculum_job_id: int
) -> None:
    """后台异步执行 CurriculumDeriveJob 工作流。"""
    session = get_session()
    try:
        # 从关联的 GraphDigestJob 获取 impact_set（序列化在 kg_workflow finalize 中）
        graph_job = session.get(GraphDigestJob, graph_job_id)
        if graph_job is None:
            logger.error("graph_job_not_found_for_curriculum", graph_job_id=graph_job_id)
            return

        graph = build_curriculum_derive_graph()
        compiled = graph.compile()

        initial_state: CurriculumDeriveState = {
            "subject": subject,
            "graph_job_id": graph_job_id,
            "curriculum_job_id": curriculum_job_id,
            "impact_set": None,  # impact_set 由 kg_workflow finalize 传递
            "derived_unit_ids": [],
            "theme_tree_version_id": None,
            "prereq_dag_version_id": None,
            "snapshot_id": None,
            "error": None,
        }

        await compiled.ainvoke(initial_state)

    except Exception:
        logger.exception(
            "curriculum_derive_background_error",
            curriculum_job_id=curriculum_job_id,
        )
        try:
            curriculum_repo.update_curriculum_job(
                session,
                curriculum_job_id,
                status="failed",
                error_message=traceback.format_exc()[-500:],
            )
        except Exception:
            logger.exception("failed_to_mark_curriculum_job_failed")
    finally:
        session.close()


# ---------------------------------------------------------------------------
# 全图查询（力导向图可视化）
# ---------------------------------------------------------------------------


def get_full_graph(
    session: Session, *, subject: str
) -> FullGraphResponse:
    """返回学科下所有 active 节点 + 边，用于力导向图可视化。"""
    nodes_raw, _ = kg_repo.list_nodes_by_subject(
        session, subject, limit=5000, offset=0,
    )
    edges_raw = kg_repo.list_all_edges_by_subject(session, subject)

    nodes = [
        KnowledgeNodeResponse(
            id=n.id,  # type: ignore[arg-type]
            subject=n.subject,
            node_type=n.node_type,
            canonical_name=n.canonical_name,
            status=n.status,
            confidence=n.confidence,
            created_at=n.created_at,
            updated_at=n.updated_at,
        )
        for n in nodes_raw
    ]
    edges = [
        GraphEdgeResponse(
            id=e.id,  # type: ignore[arg-type]
            source_node_id=e.source_node_id,
            target_node_id=e.target_node_id,
            edge_type=e.edge_type,
            weight=e.weight,
            confidence=e.confidence,
        )
        for e in edges_raw
    ]
    return FullGraphResponse(nodes=nodes, edges=edges)


def get_evidence_context(
    session: Session, *, subject: str, evidence_id: int
) -> EvidenceContextResponse:
    """获取证据的 chunk 上下文，用于前端高亮显示原文。"""
    from app.models.knowledge_graph import EvidenceLink

    ev = session.get(EvidenceLink, evidence_id)
    if ev is None or ev.subject != subject:
        raise EvidenceNotFoundError(evidence_id)

    chunk = knowledge_repo.get_chunk_by_id(session, ev.chunk_id)
    if chunk is None:
        raise EvidenceNotFoundError(evidence_id)

    doc = knowledge_repo.get_document_by_id(session, ev.document_id)
    doc_title = doc.title if doc else f"文档#{ev.document_id}"

    # 在 chunk content 中定位 quote_text 的位置
    highlight_start: int | None = None
    highlight_end: int | None = None

    if ev.source_span_start is not None and ev.source_span_end is not None:
        highlight_start = ev.source_span_start
        highlight_end = ev.source_span_end
    elif ev.quote_text:
        idx = chunk.content.find(ev.quote_text)
        if idx >= 0:
            highlight_start = idx
            highlight_end = idx + len(ev.quote_text)

    return EvidenceContextResponse(
        evidence_id=ev.id,  # type: ignore[arg-type]
        document_id=ev.document_id,
        document_title=doc_title,
        chunk_id=ev.chunk_id,
        chunk_title=chunk.title,
        chunk_header_path=chunk.header_path,
        chunk_content=chunk.content,
        quote_text=ev.quote_text,
        highlight_start=highlight_start,
        highlight_end=highlight_end,
    )


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
        raise NoPublishedCurriculumSnapshotError(subject)

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

    删除顺序按外键依赖从叶到根：
    1. UnitTreeMembership / UnitDependency（引用 tree/dag version + unit）
    2. ThemeTreeNode（引用 tree version + anchor）
    3. ThemeTreeVersion / PrereqDagVersion
    4. CurriculumSnapshot
    5. TeachingUnitMembership / TeachingUnitRevision
    6. TeachingUnit
    7. CurriculumDeriveJob
    8. TaxonomyAnchor
    9. EvidenceLink / EdgeRevision / KnowledgeRevision / KnowledgeAlias
    10. KnowledgeEdge / KnowledgeNode
    11. GraphDigestJob / SubjectBuildLock

    Returns:
        各表删除行数统计。
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

    logger.info(
        "subject_knowledge_cleared",
        subject=subject,
        counts=counts,
    )
    return counts
