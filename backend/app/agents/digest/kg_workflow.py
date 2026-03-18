"""GraphDigestJob 工作流状态机：LangGraph StateGraph 实现。

节点流程：
  acquire_lock → prepare → extract → cluster → resolve_nodes
  → resolve_edges → analyze_impact → finalize_graph → END

失败路径：
  任意节点异常 → fail → END

finalize_graph_node 完成后：
  1. activate_graph_entities_by_job 批量激活 pending → active
  2. 释放构建锁
  3. 创建 CurriculumDeriveJob 并回填到 GraphDigestJob
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime
from typing import TypedDict

import structlog
from langgraph.graph import END, StateGraph
from sqlmodel import Session, select

from app.agents.digest.kg_clusterer import ClusteredCandidate, cluster_candidates
from app.agents.digest.kg_extractor import (
    CandidateEdge,
    ChunkExtractionResult,
    extract_candidates,
)
from app.agents.digest.kg_impact_analyzer import ImpactSet, analyze_impact
from app.agents.digest.kg_resolver import (
    ResolveResult,
    compute_edge_confidence,
    resolve_edge,
    resolve_node,
)
from app.core.database import get_session
from app.core.embedding import aembed_texts
from app.models.curriculum import CurriculumDeriveJob
from app.models.knowledge import Document, DocumentChunk
from app.models.knowledge_graph import (
    EdgeRevision,
    EvidenceLink,
    GraphDigestJob,
    KnowledgeAlias,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeRevision,
)
from app.repositories import kg_repo
from app.utils.job_helpers import (
    activate_graph_entities_by_job,
    cleanup_pending_by_job,
    update_job_progress,
)
from app.utils.kg_helpers import normalize_name

logger = structlog.get_logger()


# ── State 定义 ────────────────────────────────────────────────


class KGDigestState(TypedDict, total=False):
    subject: str
    file_ids: list[int]
    job_id: int
    chunk_ids: list[int]
    candidates: list[ChunkExtractionResult]
    all_candidate_edges: list[tuple[CandidateEdge, int]]  # (edge, chunk_id)
    clustered_candidates: list[ClusteredCandidate]
    candidate_name_to_cluster_id: dict[str, int]
    candidate_name_to_resolved_node_id: dict[str, int]
    cluster_id_to_resolved_node_id: dict[int, int]
    new_node_ids: list[int]
    updated_node_ids: list[int]
    merged_node_ids: list[int]
    new_edge_ids: list[int]
    updated_edge_ids: list[int]
    impact_set: ImpactSet | None
    lock_acquired: bool
    error: str | None



# ── 工作流节点 ────────────────────────────────────────────────


async def acquire_lock_node(state: KGDigestState) -> KGDigestState:
    """获取 subject 级构建锁。失败时设置 error。"""
    session = get_session()
    try:
        acquired = kg_repo.acquire_subject_build_lock(
            session, state["subject"], state["job_id"],
        )
        if not acquired:
            logger.warning(
                "kg_workflow_lock_conflict",
                subject=state["subject"],
                job_id=state["job_id"],
            )
            return {**state, "lock_acquired": False, "error": "lock_conflict"}

        update_job_progress(
            session,
            job_id=state["job_id"],
            job_type="graph",
            progress=5,
            current_step="acquire_lock",
        )
        kg_repo.update_digest_job(session, state["job_id"], status="processing")
        return {**state, "lock_acquired": True}
    finally:
        session.close()


async def prepare_node(state: KGDigestState) -> KGDigestState:
    """加载待处理 chunks：仅处理 file_ids 对应的 DocumentChunk。"""
    session = get_session()
    try:
        file_ids: list[int] = state["file_ids"]

        # 查找 file_ids 对应的 Document → DocumentChunk
        documents = session.exec(
            select(Document).where(
                Document.subject == state["subject"],
                Document.source_file_id.in_(file_ids),  # type: ignore[union-attr]
            )
        ).all()

        doc_ids = [d.id for d in documents]
        if not doc_ids:
            logger.info("kg_workflow_no_documents", subject=state["subject"], file_ids=file_ids)
            return {**state, "chunk_ids": []}

        chunks = session.exec(
            select(DocumentChunk).where(
                DocumentChunk.document_id.in_(doc_ids),  # type: ignore[union-attr]
            )
        ).all()

        chunk_ids = [c.id for c in chunks]

        # 更新 job 的 input_chunk_count
        kg_repo.update_digest_job(
            session, state["job_id"],
            input_chunk_count=len(chunk_ids),
        )

        update_job_progress(
            session,
            job_id=state["job_id"],
            job_type="graph",
            progress=10,
            current_step="prepare",
        )

        logger.info(
            "kg_workflow_prepare_complete",
            subject=state["subject"],
            document_count=len(doc_ids),
            chunk_count=len(chunk_ids),
        )
        return {**state, "chunk_ids": chunk_ids}
    except Exception as exc:
        logger.error("kg_workflow_prepare_failed", error=str(exc))
        return {**state, "error": f"prepare_failed: {exc}"}
    finally:
        session.close()


async def extract_node(state: KGDigestState) -> KGDigestState:
    """对每个 chunk 调用 LLM 抽取候选节点和候选边。

    单个 chunk 抽取失败时跳过，不影响其余 chunk（Property 18）。
    """
    session = get_session()
    try:
        chunk_ids: list[int] = state.get("chunk_ids", [])
        if not chunk_ids:
            update_job_progress(
                session, job_id=state["job_id"], job_type="graph",
                progress=40, current_step="extract",
            )
            return {
                **state,
                "candidates": [],
                "all_candidate_edges": [],
            }

        # 批量加载 chunks
        chunks = session.exec(
            select(DocumentChunk).where(
                DocumentChunk.id.in_(chunk_ids),  # type: ignore[union-attr]
            )
        ).all()
        chunk_map = {c.id: c for c in chunks}

        all_results: list[ChunkExtractionResult] = []
        all_candidate_edges: list[tuple[CandidateEdge, int]] = []

        for i, cid in enumerate(chunk_ids):
            chunk = chunk_map.get(cid)
            if chunk is None:
                continue
            try:
                result = await extract_candidates(
                    chunk_content=chunk.content,
                    chunk_title=chunk.title,
                    header_path=chunk.header_path,
                )
                all_results.append(result)
                for edge in result.edges:
                    all_candidate_edges.append((edge, cid))
            except Exception as exc:
                # Property 18: 单 chunk 失败不影响其余
                logger.warning(
                    "kg_extract_chunk_failed",
                    chunk_id=cid,
                    error=str(exc),
                )
                continue

            # 每处理 10 个 chunk 更新一次进度
            if (i + 1) % 10 == 0:
                pct = 10 + int(30 * (i + 1) / len(chunk_ids))
                update_job_progress(
                    session, job_id=state["job_id"], job_type="graph",
                    progress=min(pct, 40), current_step="extract",
                )

        update_job_progress(
            session, job_id=state["job_id"], job_type="graph",
            progress=40, current_step="extract",
        )

        logger.info(
            "kg_workflow_extract_complete",
            total_chunks=len(chunk_ids),
            results_count=len(all_results),
            total_nodes=sum(len(r.nodes) for r in all_results),
            total_edges=len(all_candidate_edges),
        )
        return {
            **state,
            "candidates": all_results,
            "all_candidate_edges": all_candidate_edges,
        }
    except Exception as exc:
        logger.error("kg_workflow_extract_failed", error=str(exc))
        return {**state, "error": f"extract_failed: {exc}"}
    finally:
        session.close()


async def cluster_node(state: KGDigestState) -> KGDigestState:
    """批内候选聚类去重，生成 candidate_name_to_cluster_id 映射。"""
    session = get_session()
    try:
        results: list[ChunkExtractionResult] = state.get("candidates", [])
        chunk_ids: list[int] = state.get("chunk_ids", [])

        # 收集所有 (CandidateNode, chunk_id) 对
        all_pairs: list[tuple] = []
        # 按 result 顺序分配 chunk_id（每个 result 对应一个 chunk）
        result_idx = 0
        for cid in chunk_ids:
            if result_idx >= len(results):
                break
            r = results[result_idx]
            for node in r.nodes:
                all_pairs.append((node, cid))
            result_idx += 1

        if not all_pairs:
            update_job_progress(
                session, job_id=state["job_id"], job_type="graph",
                progress=50, current_step="cluster",
            )
            return {
                **state,
                "clustered_candidates": [],
                "candidate_name_to_cluster_id": {},
            }

        clustered, name_to_cluster = await cluster_candidates(all_pairs)

        update_job_progress(
            session, job_id=state["job_id"], job_type="graph",
            progress=50, current_step="cluster",
        )

        logger.info(
            "kg_workflow_cluster_complete",
            input_candidates=len(all_pairs),
            cluster_count=len(clustered),
        )
        return {
            **state,
            "clustered_candidates": clustered,
            "candidate_name_to_cluster_id": name_to_cluster,
        }
    except Exception as exc:
        logger.error("kg_workflow_cluster_failed", error=str(exc))
        return {**state, "error": f"cluster_failed: {exc}"}
    finally:
        session.close()


async def resolve_nodes_node(state: KGDigestState) -> KGDigestState:
    """节点对齐：将聚类候选与已有图谱节点匹配，生成 candidate_name_to_resolved_node_id。"""
    session = get_session()
    try:
        clustered: list[ClusteredCandidate] = state.get("clustered_candidates", [])
        subject = state["subject"]
        job_id = state["job_id"]

        candidate_name_to_resolved: dict[str, int] = {}
        cluster_id_to_resolved: dict[int, int] = {}
        new_node_ids: list[int] = []
        updated_node_ids: list[int] = []
        merged_node_ids: list[int] = []

        for cluster_idx, cc in enumerate(clustered):
            rep = cc.representative
            # 生成 embedding
            embed_text = f"{rep.name}：{cc.merged_summary}"
            embeddings = await aembed_texts([embed_text])
            candidate_embedding = embeddings[0] if embeddings else []

            result: ResolveResult = await resolve_node(
                session, cc, subject, candidate_embedding,
                candidate_name_to_resolved_node_id=candidate_name_to_resolved,
            )

            if result.decision in ("exact", "alias") and result.matched_node_id is not None:
                node_id = result.matched_node_id
                # 映射所有成员名称
                for member in cc.members:
                    candidate_name_to_resolved[member.name] = node_id
                cluster_id_to_resolved[cluster_idx] = node_id

                # 追加 evidence
                for chunk_id in cc.source_chunk_ids:
                    _create_node_evidence(
                        session, subject, node_id, chunk_id, job_id,
                    )

                # 注册新别名
                for alias_name in result.new_aliases:
                    _create_alias_if_new(session, node_id, alias_name, job_id)

                # 内容更新 → 新 revision
                if result.is_content_update:
                    _create_updated_revision(session, node_id, cc, job_id)
                    updated_node_ids.append(node_id)

            elif result.decision == "no_match":
                # 创建新节点
                node = _create_new_node(session, subject, cc, job_id)
                node_id = node.id  # type: ignore[assignment]
                for member in cc.members:
                    candidate_name_to_resolved[member.name] = node_id
                cluster_id_to_resolved[cluster_idx] = node_id

                # 创建 evidence
                for chunk_id in cc.source_chunk_ids:
                    _create_node_evidence(
                        session, subject, node_id, chunk_id, job_id,
                    )
                new_node_ids.append(node_id)

            # 每 20 个候选更新一次进度
            if (cluster_idx + 1) % 20 == 0:
                pct = 50 + int(15 * (cluster_idx + 1) / len(clustered))
                update_job_progress(
                    session, job_id=job_id, job_type="graph",
                    progress=min(pct, 65), current_step="resolve_nodes",
                )

        update_job_progress(
            session, job_id=job_id, job_type="graph",
            progress=65, current_step="resolve_nodes",
        )

        # 更新 job 统计
        kg_repo.update_digest_job(
            session, job_id,
            nodes_added=len(new_node_ids),
            nodes_updated=len(updated_node_ids),
            nodes_merged=len(merged_node_ids),
        )

        logger.info(
            "kg_workflow_resolve_nodes_complete",
            new_nodes=len(new_node_ids),
            updated_nodes=len(updated_node_ids),
            total_resolved=len(candidate_name_to_resolved),
        )
        return {
            **state,
            "candidate_name_to_resolved_node_id": candidate_name_to_resolved,
            "cluster_id_to_resolved_node_id": cluster_id_to_resolved,
            "new_node_ids": new_node_ids,
            "updated_node_ids": updated_node_ids,
            "merged_node_ids": merged_node_ids,
        }
    except Exception as exc:
        logger.error("kg_workflow_resolve_nodes_failed", error=str(exc))
        return {**state, "error": f"resolve_nodes_failed: {exc}"}
    finally:
        session.close()


async def resolve_edges_node(state: KGDigestState) -> KGDigestState:
    """边对齐：使用名称映射解析边端点，创建/更新 KnowledgeEdge。"""
    session = get_session()
    try:
        all_candidate_edges: list[tuple[CandidateEdge, int]] = state.get("all_candidate_edges", [])
        subject = state["subject"]
        job_id = state["job_id"]
        name_to_resolved = state.get("candidate_name_to_resolved_node_id", {})
        name_to_cluster = state.get("candidate_name_to_cluster_id", {})
        cluster_to_resolved = state.get("cluster_id_to_resolved_node_id", {})

        new_edge_ids: list[int] = []
        updated_edge_ids: list[int] = []

        for edge_candidate, chunk_id in all_candidate_edges:
            matched_edge, is_new, confidence = resolve_edge(
                session, edge_candidate, subject,
                name_to_resolved, name_to_cluster, cluster_to_resolved,
            )

            if matched_edge is None:
                continue

            if is_new:
                # 新边：设置 created_by_job_id 并持久化
                matched_edge.created_by_job_id = job_id
                edge = kg_repo.create_knowledge_edge(session, matched_edge)
                edge_id = edge.id  # type: ignore[assignment]

                # 创建初始 EdgeRevision
                rev = EdgeRevision(
                    edge_id=edge_id,
                    revision_no=1,
                    description=edge_candidate.description,
                    weight=edge.weight,
                    confidence=confidence,
                    revision_reason="new_evidence",
                    digest_job_id=job_id,
                    is_current=True,
                )
                rev = kg_repo.create_edge_revision(session, rev)
                edge.current_revision_id = rev.id
                edge.confidence = confidence
                session.add(edge)
                session.commit()

                # 创建 evidence
                _create_edge_evidence(session, subject, edge_id, chunk_id, job_id)
                new_edge_ids.append(edge_id)
            else:
                # 已有边：追加 evidence + 重算 confidence
                edge_id = matched_edge.id  # type: ignore[assignment]
                _create_edge_evidence(session, subject, edge_id, chunk_id, job_id)

                # 更新 confidence
                matched_edge.confidence = confidence
                matched_edge.updated_at = datetime.utcnow()
                session.add(matched_edge)
                session.commit()
                updated_edge_ids.append(edge_id)

        update_job_progress(
            session, job_id=job_id, job_type="graph",
            progress=75, current_step="resolve_edges",
        )

        kg_repo.update_digest_job(
            session, job_id,
            edges_added=len(new_edge_ids),
            edges_updated=len(updated_edge_ids),
        )

        logger.info(
            "kg_workflow_resolve_edges_complete",
            new_edges=len(new_edge_ids),
            updated_edges=len(updated_edge_ids),
        )
        return {
            **state,
            "new_edge_ids": new_edge_ids,
            "updated_edge_ids": updated_edge_ids,
        }
    except Exception as exc:
        logger.error("kg_workflow_resolve_edges_failed", error=str(exc))
        return {**state, "error": f"resolve_edges_failed: {exc}"}
    finally:
        session.close()


async def analyze_impact_node(state: KGDigestState) -> KGDigestState:
    """影响集分析：基于本次变更计算四层闭包。"""
    session = get_session()
    try:
        impact = analyze_impact(
            session,
            state["subject"],
            new_node_ids=state.get("new_node_ids", []),
            updated_node_ids=state.get("updated_node_ids", []),
            merged_node_ids=state.get("merged_node_ids", []),
            split_node_ids=[],  # MVP 暂不支持拆分
        )

        update_job_progress(
            session, job_id=state["job_id"], job_type="graph",
            progress=85, current_step="analyze_impact",
        )

        logger.info(
            "kg_workflow_impact_complete",
            changed_nodes=len(impact.changed_node_ids),
            affected_units=len(impact.affected_unit_ids),
        )
        return {**state, "impact_set": impact}
    except Exception as exc:
        logger.error("kg_workflow_analyze_impact_failed", error=str(exc))
        return {**state, "error": f"analyze_impact_failed: {exc}"}
    finally:
        session.close()


async def finalize_graph_node(state: KGDigestState) -> KGDigestState:
    """图谱构建完成：激活 pending → active → 释放锁 → 创建并启动 CurriculumDeriveJob。"""
    import asyncio

    from app.agents.digest.curriculum_workflow import run_curriculum_derive_workflow

    session = get_session()
    try:
        job_id = state["job_id"]
        subject = state["subject"]

        # 1. 批量激活 pending → active
        activated = activate_graph_entities_by_job(session, job_id=job_id)
        logger.info("kg_workflow_activated", job_id=job_id, activated=activated)

        # 2. 释放构建锁
        kg_repo.release_subject_build_lock(session, subject)

        # 3. 创建 CurriculumDeriveJob
        curriculum_job = CurriculumDeriveJob(
            subject=subject,
            graph_job_id=job_id,
            status="pending",
        )
        session.add(curriculum_job)
        session.commit()
        session.refresh(curriculum_job)

        curriculum_job_id: int = curriculum_job.id  # type: ignore[assignment]

        # 4. 回填 curriculum_job_id 到 GraphDigestJob
        kg_repo.update_digest_job(
            session, job_id,
            status="completed",
            curriculum_job_id=curriculum_job_id,
        )

        update_job_progress(
            session, job_id=job_id, job_type="graph",
            progress=100, current_step="finalize_graph",
        )

        logger.info(
            "kg_workflow_finalize_complete",
            job_id=job_id,
            curriculum_job_id=curriculum_job_id,
        )

        # 5. 异步启动 CurriculumDeriveJob 工作流（fire-and-forget）
        impact_set = state.get("impact_set")
        asyncio.create_task(
            _run_curriculum_derive_safe(
                subject=subject,
                graph_job_id=job_id,
                curriculum_job_id=curriculum_job_id,
                impact_set=impact_set,
            )
        )

        return {**state, "error": None}
    except Exception as exc:
        logger.error("kg_workflow_finalize_failed", error=str(exc))
        return {**state, "error": f"finalize_failed: {exc}"}
    finally:
        session.close()


async def _run_curriculum_derive_safe(
    *,
    subject: str,
    graph_job_id: int,
    curriculum_job_id: int,
    impact_set: ImpactSet | None,
) -> None:
    """安全包装：捕获 curriculum derive 异常，标记 job 为 failed。"""
    from app.agents.digest.curriculum_workflow import run_curriculum_derive_workflow
    from app.repositories import curriculum_repo

    try:
        await run_curriculum_derive_workflow(
            subject=subject,
            graph_job_id=graph_job_id,
            curriculum_job_id=curriculum_job_id,
            impact_set=impact_set,
        )
    except Exception:
        logger.exception(
            "curriculum_derive_auto_trigger_failed",
            curriculum_job_id=curriculum_job_id,
        )
        try:
            session = get_session()
            curriculum_repo.update_curriculum_job(
                session,
                curriculum_job_id,
                status="failed",
                error_message=traceback.format_exc()[-500:],
            )
            session.close()
        except Exception:
            logger.exception("failed_to_mark_curriculum_job_failed")


async def fail_node(state: KGDigestState) -> KGDigestState:
    """失败处理：清理 pending 数据 + 释放锁 + 更新 job 状态。"""
    session = get_session()
    try:
        job_id = state["job_id"]
        error_msg = state.get("error", "unknown_error")

        # 清理 pending 数据
        cleanup_pending_by_job(session, job_id=job_id, job_type="graph")

        # 释放锁（如果已获取）
        if state.get("lock_acquired", False):
            kg_repo.release_subject_build_lock(session, state["subject"])

        # 更新 job 状态
        kg_repo.update_digest_job(
            session, job_id,
            status="failed",
            error_message=error_msg,
        )

        logger.error(
            "kg_workflow_failed",
            job_id=job_id,
            error=error_msg,
        )
        return state
    except Exception as exc:
        logger.error("kg_workflow_fail_node_error", error=str(exc))
        return state
    finally:
        session.close()


# ── 辅助函数：节点/边创建 ────────────────────────────────────


def _create_new_node(
    session: Session,
    subject: str,
    cc: ClusteredCandidate,
    job_id: int,
) -> KnowledgeNode:
    """创建新的 KnowledgeNode + 初始 KnowledgeRevision + 主别名。"""
    rep = cc.representative
    node = KnowledgeNode(
        subject=subject,
        node_type=rep.node_type,
        canonical_name=rep.name,
        normalized_name=normalize_name(rep.name),
        status="pending",
        created_by_job_id=job_id,
    )
    node = kg_repo.create_knowledge_node(session, node)

    # 创建初始 revision
    rev = KnowledgeRevision(
        node_id=node.id,  # type: ignore[arg-type]
        revision_no=1,
        title=rep.name,
        summary=cc.merged_summary,
        body="",
        revision_reason="new_evidence",
        digest_job_id=job_id,
        is_current=True,
    )
    rev = kg_repo.create_knowledge_revision(session, rev)
    node.current_revision_id = rev.id
    session.add(node)
    session.commit()

    # 创建主别名
    alias = KnowledgeAlias(
        node_id=node.id,  # type: ignore[arg-type]
        alias=rep.name,
        normalized_alias=normalize_name(rep.name),
        source="llm",
        is_primary=True,
        created_by_job_id=job_id,
    )
    kg_repo.create_alias(session, alias)

    return node


def _create_updated_revision(
    session: Session,
    node_id: int,
    cc: ClusteredCandidate,
    job_id: int,
) -> None:
    """为已有节点创建新 revision（内容有实质性补充时）。"""
    # 获取当前最大 revision_no
    result = kg_repo.get_node_with_current_revision(session, node_id)
    if result is None:
        return
    node, current_rev = result
    new_rev_no = current_rev.revision_no + 1

    # 合并摘要
    merged_summary = current_rev.summary
    if cc.merged_summary and cc.merged_summary not in merged_summary:
        merged_summary = f"{merged_summary}；{cc.merged_summary}"

    kg_repo.deactivate_old_revisions(session, node_id)
    rev = KnowledgeRevision(
        node_id=node_id,
        revision_no=new_rev_no,
        title=current_rev.title,
        summary=merged_summary,
        body=current_rev.body,
        revision_reason="new_evidence",
        digest_job_id=job_id,
        is_current=True,
    )
    rev = kg_repo.create_knowledge_revision(session, rev)
    node.current_revision_id = rev.id
    node.updated_at = datetime.utcnow()
    session.add(node)
    session.commit()


def _create_alias_if_new(
    session: Session,
    node_id: int,
    alias_name: str,
    job_id: int,
) -> None:
    """如果别名不存在则创建。"""
    norm = normalize_name(alias_name)
    existing = kg_repo.list_aliases_by_node(session, node_id)
    for a in existing:
        if a.normalized_alias == norm:
            return
    alias = KnowledgeAlias(
        node_id=node_id,
        alias=alias_name,
        normalized_alias=norm,
        source="llm",
        is_primary=False,
        created_by_job_id=job_id,
    )
    kg_repo.create_alias(session, alias)


def _create_node_evidence(
    session: Session,
    subject: str,
    node_id: int,
    chunk_id: int,
    job_id: int,
) -> None:
    """为节点创建 EvidenceLink。"""
    # 获取 chunk 的 document_id
    chunk = session.get(DocumentChunk, chunk_id)
    if chunk is None:
        return
    link = EvidenceLink(
        subject=subject,
        entity_type="node",
        entity_id=node_id,
        document_id=chunk.document_id,
        chunk_id=chunk_id,
        evidence_role="supports",
        extraction_method="llm",
        field_scope="summary",
        created_by_job_id=job_id,
    )
    kg_repo.create_evidence_link(session, link)


def _create_edge_evidence(
    session: Session,
    subject: str,
    edge_id: int,
    chunk_id: int,
    job_id: int,
) -> None:
    """为边创建 EvidenceLink。"""
    chunk = session.get(DocumentChunk, chunk_id)
    if chunk is None:
        return
    link = EvidenceLink(
        subject=subject,
        entity_type="edge",
        entity_id=edge_id,
        document_id=chunk.document_id,
        chunk_id=chunk_id,
        evidence_role="supports",
        extraction_method="llm",
        field_scope="edge_description",
        created_by_job_id=job_id,
    )
    kg_repo.create_evidence_link(session, link)


# ── 条件分支路由 ──────────────────────────────────────────────


def _route_after_lock(state: KGDigestState) -> str:
    """锁获取后路由：成功 → prepare，失败 → fail。"""
    if state.get("error"):
        return "fail"
    return "prepare"


def _route_after_step(state: KGDigestState) -> str:
    """通用步骤后路由：有 error → fail，否则继续。"""
    if state.get("error"):
        return "fail"
    return "continue"


def _route_after_prepare(state: KGDigestState) -> str:
    """prepare 后路由：无 chunks → 直接 finalize，有 error → fail。"""
    if state.get("error"):
        return "fail"
    if not state.get("chunk_ids"):
        return "finalize_graph"
    return "extract"


# ── 构建 LangGraph StateGraph ────────────────────────────────


def build_kg_digest_graph() -> StateGraph:
    """构建 GraphDigestJob 工作流状态图。"""
    workflow = StateGraph(KGDigestState)

    # 添加节点
    workflow.add_node("acquire_lock", acquire_lock_node)
    workflow.add_node("prepare", prepare_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("cluster", cluster_node)
    workflow.add_node("resolve_nodes", resolve_nodes_node)
    workflow.add_node("resolve_edges", resolve_edges_node)
    workflow.add_node("analyze_impact", analyze_impact_node)
    workflow.add_node("finalize_graph", finalize_graph_node)
    workflow.add_node("fail", fail_node)

    # 入口
    workflow.set_entry_point("acquire_lock")

    # 条件分支
    workflow.add_conditional_edges(
        "acquire_lock",
        _route_after_lock,
        {"prepare": "prepare", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "prepare",
        _route_after_prepare,
        {"extract": "extract", "finalize_graph": "finalize_graph", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "extract",
        _route_after_step,
        {"continue": "cluster", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "cluster",
        _route_after_step,
        {"continue": "resolve_nodes", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "resolve_nodes",
        _route_after_step,
        {"continue": "resolve_edges", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "resolve_edges",
        _route_after_step,
        {"continue": "analyze_impact", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "analyze_impact",
        _route_after_step,
        {"continue": "finalize_graph", "fail": "fail"},
    )

    # 终止边
    workflow.add_edge("finalize_graph", END)
    workflow.add_edge("fail", END)

    return workflow


# ── 工作流入口 ────────────────────────────────────────────────


async def run_kg_digest_workflow(
    *,
    subject: str,
    job_id: int,
    file_ids: list[int],
) -> KGDigestState:
    """执行 GraphDigestJob 工作流。

    Args:
        subject: 学科标识。
        job_id: GraphDigestJob ID。
        file_ids: 待处理的文件 ID 列表。

    Returns:
        最终工作流状态。
    """
    graph = build_kg_digest_graph()
    app = graph.compile()

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

    result = await app.ainvoke(initial_state)
    return result
