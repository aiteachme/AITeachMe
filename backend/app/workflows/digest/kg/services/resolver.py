"""对齐层：节点对齐（Entity Resolution）与边对齐（Relation Resolution）。

节点对齐分层递进流程：
- 一级实体（Topic/Concept/Method）：normalized_name → alias → embedding + LLM
- 二级说明对象（Definition/Example）：parent_entity_name + 内容语义相似度

边对齐使用名称映射解析端点：
- 优先 candidate_name_to_resolved_node_id
- 次选 candidate_name_to_cluster_id 间接查找
- fallback find_node_by_normalized_name
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select
import structlog

from app.workflows.digest.kg.services.clusterer import ClusteredCandidate
from app.workflows.digest.kg.services.extractor import CandidateEdge
from app.workflows.digest.prompts import (
    SYSTEM_PROMPT_KG_ENTITY_MATCH,
    USER_PROMPT_KG_ENTITY_MATCH,
)
from app.infra.embedding import aembed_texts
from app.infra.llm import acompletion_structured
from app.infra.prompt_loader import populate_prompt
from app.models.knowledge_graph import (
    EdgeRevision,
    EvidenceLink,
    KnowledgeAlias,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeRevision,
)
from app.repositories import kg_repo
from app.schemas.llm import ChatMessage, SYSTEM, USER
from app.utils.kg_helpers import normalize_name

logger = structlog.get_logger()

# ── 配置常量 ──────────────────────────────────────────────────

_EMBEDDING_SIMILARITY_THRESHOLD = 0.80
_SECONDARY_SIMILARITY_THRESHOLD = 0.85
_PRIMARY_NODE_TYPES = {"Topic", "Concept", "Method"}
_SECONDARY_NODE_TYPES = {"Definition", "Example"}


# ── 数据类 ────────────────────────────────────────────────────


@dataclass
class ResolveResult:
    """节点对齐结果。"""

    decision: str  # EntityMatchDecision value
    matched_node_id: int | None = None
    is_content_update: bool = False
    new_aliases: list[str] = field(default_factory=list)


class EntityMatchResponse(BaseModel):
    """LLM 实体对齐判定结构化输出。"""

    decision: Literal["EXACT", "ALIAS", "NO_MATCH"] = PydanticField(
        description="判定结果：EXACT（完全相同）/ ALIAS（别名）/ NO_MATCH（不同知识点）"
    )


# ── 辅助函数 ──────────────────────────────────────────────────


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _has_content_update(candidate_summary: str, existing_summary: str) -> bool:
    """简单判断候选摘要是否对已有摘要有实质性补充。

    如果候选摘要长度超过已有摘要的 20% 且包含不同内容，视为有补充。
    """
    if not candidate_summary.strip():
        return False
    if not existing_summary.strip():
        return True
    # 简单启发式：候选摘要中有超过 30% 的字符不在已有摘要中
    existing_chars = set(existing_summary)
    new_chars = sum(1 for c in candidate_summary if c not in existing_chars)
    return new_chars > len(candidate_summary) * 0.3


async def _llm_entity_match(
    candidate_name: str,
    candidate_type: str,
    candidate_summary: str,
    existing_name: str,
    existing_type: str,
    existing_summary: str,
) -> str:
    """调用 LLM 判断两个节点是否为同一知识点。

    Returns:
        EntityMatchDecision 值：exact / alias / no_match
    """
    user_content = populate_prompt(
        USER_PROMPT_KG_ENTITY_MATCH,
        candidate_name=candidate_name,
        candidate_type=candidate_type,
        candidate_summary=candidate_summary,
        existing_name=existing_name,
        existing_type=existing_type,
        existing_summary=existing_summary,
    )

    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_KG_ENTITY_MATCH},
        {"role": USER, "content": user_content},
    ]

    try:
        result = await acompletion_structured(
            response_model=EntityMatchResponse,
            messages=messages,
        )
        return result.decision.lower()
    except Exception:
        logger.warning("llm_entity_match_failed", candidate=candidate_name, existing=existing_name)
        return "no_match"


# ── 节点对齐：一级实体（Topic/Concept/Method）──────────────────


async def _resolve_primary_entity(
    session: Session,
    candidate: ClusteredCandidate,
    subject: str,
    candidate_embedding: list[float],
    similarity_threshold: float,
) -> ResolveResult:
    """一级实体对齐：normalized_name → alias → embedding + LLM。"""
    rep = candidate.representative
    norm_name = normalize_name(rep.name)

    # Step 1: normalized_name 精确匹配
    existing = kg_repo.find_node_by_normalized_name(
        session, subject, norm_name, rep.node_type,
    )
    if existing is not None:
        rev = _get_current_summary(session, existing)
        return ResolveResult(
            decision="exact",
            matched_node_id=existing.id,
            is_content_update=_has_content_update(candidate.merged_summary, rev),
        )

    # Step 2: 别名匹配
    alias_nodes = kg_repo.find_nodes_by_alias(session, subject, norm_name, rep.node_type)
    if alias_nodes:
        matched = alias_nodes[0]
        rev = _get_current_summary(session, matched)
        return ResolveResult(
            decision="alias",
            matched_node_id=matched.id,
            is_content_update=_has_content_update(candidate.merged_summary, rev),
        )

    # Step 3: embedding 相似度 + LLM 判断
    same_type_nodes = kg_repo.list_nodes_by_subject(
        session, subject, node_type=rep.node_type, status="active", limit=200, offset=0,
    )[0]

    if same_type_nodes and candidate_embedding:
        # 为已有节点生成 embedding 文本
        existing_texts = [
            f"{n.canonical_name}：{_get_current_summary(session, n)}"
            for n in same_type_nodes
        ]
        existing_embeddings = await aembed_texts(existing_texts)

        best_sim = 0.0
        best_node: KnowledgeNode | None = None
        for node, emb in zip(same_type_nodes, existing_embeddings):
            sim = _cosine_similarity(candidate_embedding, emb)
            if sim > best_sim:
                best_sim = sim
                best_node = node

        if best_sim >= similarity_threshold and best_node is not None:
            # LLM 最终判断
            existing_summary = _get_current_summary(session, best_node)
            decision = await _llm_entity_match(
                candidate_name=rep.name,
                candidate_type=rep.node_type,
                candidate_summary=candidate.merged_summary,
                existing_name=best_node.canonical_name,
                existing_type=best_node.node_type,
                existing_summary=existing_summary,
            )
            if decision in ("exact", "alias"):
                new_aliases = [rep.name] if decision == "alias" else []
                return ResolveResult(
                    decision=decision,
                    matched_node_id=best_node.id,
                    is_content_update=_has_content_update(candidate.merged_summary, existing_summary),
                    new_aliases=new_aliases,
                )

    # 未匹配 → 新节点
    return ResolveResult(decision="no_match")


def _get_current_summary(session: Session, node: KnowledgeNode) -> str:
    """获取节点当前修订的 summary。"""
    result = kg_repo.get_node_with_current_revision(session, node.id)  # type: ignore[arg-type]
    if result is None:
        return ""
    return result[1].summary


# ── 节点对齐：二级说明对象（Definition/Example）──────────────


async def _resolve_secondary_entity(
    session: Session,
    candidate: ClusteredCandidate,
    subject: str,
    candidate_embedding: list[float],
    candidate_name_to_resolved_node_id: dict[str, int],
) -> ResolveResult:
    """二级说明对象对齐：parent_entity_name + 内容语义相似度。"""
    rep = candidate.representative
    norm_name = normalize_name(rep.name)

    # Step 1: normalized_name 精确匹配（即使是二级对象也先尝试）
    existing = kg_repo.find_node_by_normalized_name(
        session, subject, norm_name, rep.node_type,
    )
    if existing is not None:
        rev = _get_current_summary(session, existing)
        return ResolveResult(
            decision="exact",
            matched_node_id=existing.id,
            is_content_update=_has_content_update(candidate.merged_summary, rev),
        )

    # Step 2: 通过 parent_entity_name 定位父实体
    parent_name = rep.parent_entity_name
    if not parent_name:
        return ResolveResult(decision="no_match")

    parent_node_id = candidate_name_to_resolved_node_id.get(parent_name)
    if parent_node_id is None:
        # 尝试在图谱中查找父实体
        parent_norm = normalize_name(parent_name)
        for ptype in ("Concept", "Method", "Topic"):
            parent_node = kg_repo.find_node_by_normalized_name(
                session, subject, parent_norm, ptype,
            )
            if parent_node is not None:
                parent_node_id = parent_node.id
                break

    if parent_node_id is None:
        return ResolveResult(decision="no_match")

    # Step 3: 查找同 parent 下同类型的已有节点，比较语义相似度
    edges = kg_repo.list_edges_by_node(session, parent_node_id, status="active")
    sibling_node_ids: list[int] = []
    for edge in edges:
        if edge.edge_type in ("defined_by", "illustrated_by"):
            target_id = edge.target_node_id
            if target_id != parent_node_id:
                sibling_node_ids.append(target_id)

    if not sibling_node_ids or not candidate_embedding:
        return ResolveResult(decision="no_match")

    siblings: list[KnowledgeNode] = []
    for sid in sibling_node_ids:
        snode = kg_repo.get_knowledge_node_by_id(session, sid)
        if snode and snode.node_type == rep.node_type and snode.status in ("active", "pending"):
            siblings.append(snode)

    if not siblings:
        return ResolveResult(decision="no_match")

    sibling_texts = [
        f"{s.canonical_name}：{_get_current_summary(session, s)}"
        for s in siblings
    ]
    sibling_embeddings = await aembed_texts(sibling_texts)

    best_sim = 0.0
    best_sibling: KnowledgeNode | None = None
    for sib, emb in zip(siblings, sibling_embeddings):
        sim = _cosine_similarity(candidate_embedding, emb)
        if sim > best_sim:
            best_sim = sim
            best_sibling = sib

    if best_sim >= _SECONDARY_SIMILARITY_THRESHOLD and best_sibling is not None:
        rev = _get_current_summary(session, best_sibling)
        return ResolveResult(
            decision="exact",
            matched_node_id=best_sibling.id,
            is_content_update=_has_content_update(candidate.merged_summary, rev),
        )

    return ResolveResult(decision="no_match")


# ── 节点对齐主入口 ────────────────────────────────────────────


async def resolve_node(
    session: Session,
    candidate: ClusteredCandidate,
    subject: str,
    candidate_embedding: list[float],
    similarity_threshold: float = _EMBEDDING_SIMILARITY_THRESHOLD,
    *,
    candidate_name_to_resolved_node_id: dict[str, int] | None = None,
) -> ResolveResult:
    """对齐单个聚类候选到已有图谱节点。

    分层递进流程：
    - 一级实体（Topic/Concept/Method）：normalized_name → alias → embedding + LLM
    - 二级说明对象（Definition/Example）：parent_entity_name + 内容语义相似度

    Args:
        session: 数据库会话。
        candidate: 聚类后的候选节点。
        subject: 学科标识。
        candidate_embedding: 候选节点的 embedding 向量。
        similarity_threshold: embedding 相似度阈值。
        candidate_name_to_resolved_node_id: 已对齐的候选名称映射。

    Returns:
        ResolveResult 包含对齐判定和匹配信息。
    """
    rep = candidate.representative

    if rep.node_type in _PRIMARY_NODE_TYPES:
        result = await _resolve_primary_entity(
            session, candidate, subject, candidate_embedding, similarity_threshold,
        )
    elif rep.node_type in _SECONDARY_NODE_TYPES:
        result = await _resolve_secondary_entity(
            session, candidate, subject, candidate_embedding,
            candidate_name_to_resolved_node_id or {},
        )
    else:
        logger.warning("unknown_node_type", node_type=rep.node_type, name=rep.name)
        result = ResolveResult(decision="no_match")

    logger.info(
        "resolve_node_complete",
        name=rep.name,
        node_type=rep.node_type,
        decision=result.decision,
        matched_node_id=result.matched_node_id,
    )
    return result


# ── 边置信度计算 ──────────────────────────────────────────────


def compute_edge_confidence(
    active_evidence_count: int,
    contradicting_evidence_count: int = 0,
    max_confidence: float = 0.95,
) -> float:
    """计算边置信度（非单调递增公式）。

    confidence = min(max_confidence, 1 - 1/(1 + active_count)) - 0.1 * contradicting_count

    active_evidence 越多 confidence 越高，contradicting_evidence 会降低 confidence。
    """
    if active_evidence_count == 0:
        return 0.0
    base = 1.0 - 1.0 / (1.0 + active_evidence_count)
    penalty = 0.1 * contradicting_evidence_count
    return max(0.0, min(max_confidence, base - penalty))


# ── 边对齐 ────────────────────────────────────────────────────


def _resolve_edge_endpoint(
    name: str,
    candidate_name_to_resolved_node_id: dict[str, int],
    candidate_name_to_cluster_id: dict[str, int],
    cluster_id_to_resolved_node_id: dict[int, int],
    session: Session,
    subject: str,
) -> int | None:
    """解析边端点名称到 KnowledgeNode ID。

    优先级：
    1. candidate_name_to_resolved_node_id（batch 内已对齐）
    2. candidate_name_to_cluster_id → cluster 代表的 resolved node id
    3. fallback: find_node_by_normalized_name（已有图谱）
    """
    # 优先级 1：直接映射
    node_id = candidate_name_to_resolved_node_id.get(name)
    if node_id is not None:
        return node_id

    # 优先级 2：通过聚类代表间接查找
    cluster_id = candidate_name_to_cluster_id.get(name)
    if cluster_id is not None:
        node_id = cluster_id_to_resolved_node_id.get(cluster_id)
        if node_id is not None:
            return node_id

    # 优先级 3：在已有图谱中按 normalized_name 查找
    norm = normalize_name(name)
    for node_type in ("Topic", "Concept", "Definition", "Method", "Example"):
        node = kg_repo.find_node_by_normalized_name(session, subject, norm, node_type)
        if node is not None:
            return node.id  # type: ignore[return-value]

    return None


def resolve_edge(
    session: Session,
    candidate: CandidateEdge,
    subject: str,
    candidate_name_to_resolved_node_id: dict[str, int],
    candidate_name_to_cluster_id: dict[str, int],
    cluster_id_to_resolved_node_id: dict[int, int],
) -> tuple[KnowledgeEdge | None, bool, float]:
    """对齐单条候选边。

    Args:
        session: 数据库会话。
        candidate: 候选边。
        subject: 学科标识。
        candidate_name_to_resolved_node_id: 候选名称 → 已对齐 node id。
        candidate_name_to_cluster_id: 候选名称 → 聚类代表索引。
        cluster_id_to_resolved_node_id: 聚类代表索引 → 已对齐 node id。

    Returns:
        (matched_edge | None, is_new, confidence) 元组。
        - matched_edge: 匹配到的已有边，或 None（端点无法解析时）。
        - is_new: True 表示需要创建新边，False 表示匹配到已有边。
        - confidence: 计算后的置信度。
    """
    source_id = _resolve_edge_endpoint(
        candidate.source_name,
        candidate_name_to_resolved_node_id,
        candidate_name_to_cluster_id,
        cluster_id_to_resolved_node_id,
        session, subject,
    )
    target_id = _resolve_edge_endpoint(
        candidate.target_name,
        candidate_name_to_resolved_node_id,
        candidate_name_to_cluster_id,
        cluster_id_to_resolved_node_id,
        session, subject,
    )

    if source_id is None or target_id is None:
        logger.warning(
            "edge_endpoint_unresolved",
            source=candidate.source_name,
            target=candidate.target_name,
            source_resolved=source_id is not None,
            target_resolved=target_id is not None,
        )
        return None, False, 0.0

    # 自环检查
    if source_id == target_id:
        logger.warning("edge_self_loop", source=candidate.source_name, target=candidate.target_name)
        return None, False, 0.0

    # 查找已有边
    existing_edge = kg_repo.find_edge(session, source_id, target_id, candidate.edge_type)

    if existing_edge is not None:
        # 已有边：重算 confidence
        active_count = kg_repo.count_active_evidence(session, "edge", existing_edge.id)  # type: ignore[arg-type]
        # +1 因为即将追加新 evidence
        confidence = compute_edge_confidence(active_count + 1)
        logger.info(
            "edge_matched_existing",
            edge_id=existing_edge.id,
            edge_type=candidate.edge_type,
            new_confidence=confidence,
        )
        return existing_edge, False, confidence

    # 新边
    confidence = compute_edge_confidence(1)
    logger.info(
        "edge_new",
        source_id=source_id,
        target_id=target_id,
        edge_type=candidate.edge_type,
        confidence=confidence,
    )
    # 构造临时 edge 对象（未持久化，由调用方决定何时写入）
    new_edge = KnowledgeEdge(
        subject=subject,
        source_node_id=source_id,
        target_node_id=target_id,
        edge_type=candidate.edge_type,
        confidence=confidence,
        status="pending",
    )
    return new_edge, True, confidence
