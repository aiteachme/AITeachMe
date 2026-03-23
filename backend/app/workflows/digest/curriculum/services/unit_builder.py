"""教学单元生成器：局部子图提取 + graph-aware 聚类 + LLM 命名 + 单元 Upsert。

从 Impact Set 中受影响的 active 节点出发，提取局部子图，
通过多维距离函数 + 层次聚类生成 leaf-level 教学单元。

硬规则：
- 禁止在 unit_builder 内部调用任何 publish/archive helper
- 只能创建 pending 状态的 TeachingUnit / TeachingUnitRevision / TeachingUnitMembership
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import NamedTuple

import structlog
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, or_, select

from app.workflows.digest.kg.services.impact_analyzer import ImpactSet
from app.workflows.digest.prompts import (
    SYSTEM_PROMPT_KG_UNIT_NAMING,
    USER_PROMPT_KG_UNIT_NAMING,
)
from app.core.embedding import aembed_texts
from app.core.llm import acompletion_structured
from app.core.prompt_loader import populate_prompt
from app.models.curriculum import (
    TeachingUnit,
    TeachingUnitMembership,
    TeachingUnitRevision,
)
from app.models.knowledge_graph import (
    EvidenceLink,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeRevision,
)
from app.repositories import curriculum_repo, kg_repo
from app.schemas.llm import ChatMessage, SYSTEM, USER
from app.utils.kg_helpers import compute_member_signature, normalize_name

logger = structlog.get_logger(__name__)

# ── 配置常量 ──────────────────────────────────────────────────

_CLUSTER_DISTANCE_THRESHOLD = 0.65
_MIN_CLUSTER_SIZE = 1
_MAX_CLUSTER_SIZE = 8


# ── 距离函数权重 ─────────────────────────────────────────────

@dataclass
class UnitDistanceWeights:
    """graph-aware 聚类距离函数权重。"""
    semantic: float = 0.30
    graph_relation: float = 0.25
    co_outline: float = 0.20
    prerequisite_penalty: float = 0.15
    type_compatibility: float = 0.10


_DEFAULT_WEIGHTS = UnitDistanceWeights()

# 类型兼容性矩阵：值越小越容易聚在一起
_TYPE_COMPAT: dict[tuple[str, str], float] = {
    ("Concept", "Definition"): 0.1,
    ("Concept", "Example"): 0.2,
    ("Concept", "Method"): 0.3,
    ("Definition", "Example"): 0.2,
    ("Method", "Example"): 0.2,
    ("Topic", "Concept"): 0.6,
    ("Topic", "Topic"): 0.8,
    ("Topic", "Definition"): 0.7,
    ("Topic", "Method"): 0.7,
    ("Topic", "Example"): 0.7,
}

# 强关系边类型（距离更近）
_STRONG_RELATION_TYPES = {"defined_by", "illustrated_by", "part_of"}


# ── 数据类 ────────────────────────────────────────────────────

@dataclass
class UnitCandidate:
    """聚类产生的教学单元候选。"""
    core_node_ids: list[int] = field(default_factory=list)
    support_node_ids: list[int] = field(default_factory=list)
    example_node_ids: list[int] = field(default_factory=list)
    bridge_node_ids: list[int] = field(default_factory=list)
    cluster_score: float = 0.0


class UnitNamingResponse(BaseModel):
    """LLM 教学单元命名结构化输出。"""
    title: str = PydanticField(description="教学单元名称")
    summary: str = PydanticField(description="教学单元摘要")
    learning_objectives: list[str] = PydanticField(description="学习目标列表")


class _NodeInfo(NamedTuple):
    """节点信息缓存。"""
    node_id: int
    node_type: str
    canonical_name: str
    summary: str


# ── 局部子图提取 ──────────────────────────────────────────────

def extract_local_subgraph(
    session: Session,
    subject: str,
    impact_set: ImpactSet,
) -> tuple[list[KnowledgeNode], list[KnowledgeEdge]]:
    """从 Impact Set 中受影响的 active 节点出发，提取 changed + 1-hop + 2-hop 子图。

    Returns:
        (nodes, edges) — 子图中的节点和边列表。
    """
    seed_ids = impact_set.changed_node_ids | impact_set.candidate_recompute_node_ids
    if not seed_ids:
        return [], []

    # 加载所有 seed 节点（仅 active）
    nodes_stmt = select(KnowledgeNode).where(
        KnowledgeNode.subject == subject,
        KnowledgeNode.status == "active",
        KnowledgeNode.id.in_(seed_ids),  # type: ignore[union-attr]
    )
    nodes = list(session.exec(nodes_stmt).all())
    node_ids = {n.id for n in nodes}

    # 加载子图内的 active 边
    if not node_ids:
        return [], []

    edges_stmt = select(KnowledgeEdge).where(
        KnowledgeEdge.subject == subject,
        KnowledgeEdge.status == "active",
        or_(
            KnowledgeEdge.source_node_id.in_(node_ids),  # type: ignore[union-attr]
            KnowledgeEdge.target_node_id.in_(node_ids),  # type: ignore[union-attr]
        ),
    )
    edges = list(session.exec(edges_stmt).all())

    logger.info(
        "subgraph_extracted",
        subject=subject,
        node_count=len(nodes),
        edge_count=len(edges),
    )
    return nodes, edges


# ── 距离计算 ──────────────────────────────────────────────────

def _cosine_distance(a: list[float], b: list[float]) -> float:
    """余弦距离 = 1 - 余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1.0 - dot / (norm_a * norm_b)


def _graph_relation_distance(
    node_i: int,
    node_j: int,
    adjacency: dict[int, set[int]],
    strong_adjacency: dict[int, set[int]],
) -> float:
    """图关系距离：part_of/defined_by/illustrated_by 边越多距离越近。

    - 有强关系边直连 → 0.0
    - 有普通边直连 → 0.3
    - 共享邻居 → 0.6
    - 无关系 → 1.0
    """
    if node_j in strong_adjacency.get(node_i, set()):
        return 0.0
    if node_j in adjacency.get(node_i, set()):
        return 0.3
    # 共享邻居
    neighbors_i = adjacency.get(node_i, set())
    neighbors_j = adjacency.get(node_j, set())
    if neighbors_i & neighbors_j:
        return 0.6
    return 1.0


def _co_outline_distance(
    node_i: int,
    node_j: int,
    chunk_co_occurrence: dict[tuple[int, int], float],
) -> float:
    """文档结构邻近性：共现于同一 chunk/section 的节点距离更近。

    chunk_co_occurrence 值域 [0, 1]，1 表示完全共现。
    """
    key = (min(node_i, node_j), max(node_i, node_j))
    co = chunk_co_occurrence.get(key, 0.0)
    return 1.0 - co


def _prerequisite_penalty(
    node_i: int,
    node_j: int,
    prereq_pairs: set[tuple[int, int]],
) -> float:
    """强 prerequisite 关系的两端不一定应合并（惩罚项）。"""
    if (node_i, node_j) in prereq_pairs or (node_j, node_i) in prereq_pairs:
        return 1.0
    return 0.0


def _type_compatibility_penalty(type_i: str, type_j: str) -> float:
    """类型兼容性惩罚。Concept+Definition+Example 容易聚在一起；Topic 倾向独立。"""
    if type_i == type_j:
        return 0.0 if type_i != "Topic" else 0.8
    key = (min(type_i, type_j), max(type_i, type_j))
    return _TYPE_COMPAT.get(key, 0.5)


def compute_unit_distance(
    node_i: int,
    node_j: int,
    embeddings: dict[int, list[float]],
    adjacency: dict[int, set[int]],
    strong_adjacency: dict[int, set[int]],
    chunk_co_occurrence: dict[tuple[int, int], float],
    prereq_pairs: set[tuple[int, int]],
    node_types: dict[int, str],
    weights: UnitDistanceWeights | None = None,
) -> float:
    """多维距离函数。

    dist(i, j) =
        0.30 * semantic_distance
      + 0.25 * graph_relation_distance
      + 0.20 * co_outline_distance
      + 0.15 * prerequisite_penalty
      + 0.10 * type_compatibility_penalty
    """
    w = weights or _DEFAULT_WEIGHTS

    emb_i = embeddings.get(node_i, [])
    emb_j = embeddings.get(node_j, [])
    sem = _cosine_distance(emb_i, emb_j) if emb_i and emb_j else 1.0

    graph = _graph_relation_distance(node_i, node_j, adjacency, strong_adjacency)
    co = _co_outline_distance(node_i, node_j, chunk_co_occurrence)
    prereq = _prerequisite_penalty(node_i, node_j, prereq_pairs)
    compat = _type_compatibility_penalty(
        node_types.get(node_i, "Concept"),
        node_types.get(node_j, "Concept"),
    )

    return (
        w.semantic * sem
        + w.graph_relation * graph
        + w.co_outline * co
        + w.prerequisite_penalty * prereq
        + w.type_compatibility * compat
    )


def compute_pairwise_distances(
    node_ids: list[int],
    embeddings: dict[int, list[float]],
    adjacency: dict[int, set[int]],
    strong_adjacency: dict[int, set[int]],
    chunk_co_occurrence: dict[tuple[int, int], float],
    prereq_pairs: set[tuple[int, int]],
    node_types: dict[int, str],
    weights: UnitDistanceWeights | None = None,
) -> dict[tuple[int, int], float]:
    """计算所有节点对的 pairwise 距离矩阵（上三角）。"""
    distances: dict[tuple[int, int], float] = {}
    for i in range(len(node_ids)):
        for j in range(i + 1, len(node_ids)):
            ni, nj = node_ids[i], node_ids[j]
            d = compute_unit_distance(
                ni, nj, embeddings, adjacency, strong_adjacency,
                chunk_co_occurrence, prereq_pairs, node_types, weights,
            )
            distances[(ni, nj)] = d
    return distances


# ── 辅助：构建图结构索引 ─────────────────────────────────────


def _build_graph_indices(
    edges: list[KnowledgeEdge],
) -> tuple[
    dict[int, set[int]],       # adjacency
    dict[int, set[int]],       # strong_adjacency
    set[tuple[int, int]],      # prereq_pairs
]:
    """从边列表构建邻接表、强关系邻接表和先修对集合。"""
    adjacency: dict[int, set[int]] = {}
    strong_adjacency: dict[int, set[int]] = {}
    prereq_pairs: set[tuple[int, int]] = set()

    for edge in edges:
        src, tgt = edge.source_node_id, edge.target_node_id
        adjacency.setdefault(src, set()).add(tgt)
        adjacency.setdefault(tgt, set()).add(src)

        if edge.edge_type in _STRONG_RELATION_TYPES:
            strong_adjacency.setdefault(src, set()).add(tgt)
            strong_adjacency.setdefault(tgt, set()).add(src)

        if edge.edge_type == "prerequisite_of":
            prereq_pairs.add((src, tgt))

    return adjacency, strong_adjacency, prereq_pairs


def _build_chunk_co_occurrence(
    session: Session,
    node_ids: set[int],
) -> dict[tuple[int, int], float]:
    """基于 EvidenceLink 的 chunk_id 计算节点对的文档共现度。

    两个节点共享的 chunk 数 / 两者 chunk 并集数。
    """
    # 查询所有相关节点的 evidence links
    if not node_ids:
        return {}

    stmt = select(EvidenceLink).where(
        EvidenceLink.entity_type == "node",
        EvidenceLink.entity_id.in_(node_ids),  # type: ignore[union-attr]
        EvidenceLink.is_active == True,  # noqa: E712
    )
    links = list(session.exec(stmt).all())

    # node_id → set of chunk_ids
    node_chunks: dict[int, set[int]] = {}
    for link in links:
        node_chunks.setdefault(link.entity_id, set()).add(link.chunk_id)

    # 计算 pairwise Jaccard
    co_occurrence: dict[tuple[int, int], float] = {}
    node_list = list(node_ids)
    for i in range(len(node_list)):
        for j in range(i + 1, len(node_list)):
            ni, nj = node_list[i], node_list[j]
            ci = node_chunks.get(ni, set())
            cj = node_chunks.get(nj, set())
            if not ci or not cj:
                continue
            intersection = len(ci & cj)
            if intersection == 0:
                continue
            union = len(ci | cj)
            key = (min(ni, nj), max(ni, nj))
            co_occurrence[key] = intersection / union

    return co_occurrence


# ── 层次聚类 ─────────────────────────────────────────────────


def agglomerative_cluster(
    node_ids: list[int],
    distances: dict[tuple[int, int], float],
    threshold: float = _CLUSTER_DISTANCE_THRESHOLD,
) -> list[list[int]]:
    """简单的凝聚层次聚类（single-linkage）。

    每步合并距离最小的两个簇，直到最小距离超过阈值。
    """
    if not node_ids:
        return []
    if len(node_ids) == 1:
        return [node_ids[:]]

    # 初始化：每个节点一个簇
    clusters: dict[int, list[int]] = {i: [nid] for i, nid in enumerate(node_ids)}
    # 簇间距离缓存（single-linkage: 最小距离）
    cluster_dist: dict[tuple[int, int], float] = {}

    for ci in clusters:
        for cj in clusters:
            if ci >= cj:
                continue
            min_d = _inter_cluster_distance(clusters[ci], clusters[cj], distances)
            cluster_dist[(ci, cj)] = min_d

    next_id = len(node_ids)

    while len(clusters) > 1:
        # 找最小距离的簇对
        best_pair = None
        best_dist = float("inf")
        for (ci, cj), d in cluster_dist.items():
            if ci not in clusters or cj not in clusters:
                continue
            if d < best_dist:
                best_dist = d
                best_pair = (ci, cj)

        if best_pair is None or best_dist > threshold:
            break

        ci, cj = best_pair
        # 合并后检查大小限制
        merged_size = len(clusters[ci]) + len(clusters[cj])
        if merged_size > _MAX_CLUSTER_SIZE:
            # 标记此对不可合并，设为无穷大
            cluster_dist[(ci, cj)] = float("inf")
            continue

        # 合并
        new_members = clusters[ci] + clusters[cj]
        del clusters[ci]
        del clusters[cj]

        new_id = next_id
        next_id += 1
        clusters[new_id] = new_members

        # 清理旧距离，计算新簇与其他簇的距离
        keys_to_remove = [
            k for k in cluster_dist
            if k[0] in (ci, cj) or k[1] in (ci, cj)
        ]
        for k in keys_to_remove:
            del cluster_dist[k]

        for other_id in clusters:
            if other_id == new_id:
                continue
            lo, hi = min(new_id, other_id), max(new_id, other_id)
            d = _inter_cluster_distance(clusters[new_id], clusters[other_id], distances)
            cluster_dist[(lo, hi)] = d

    return list(clusters.values())


def _inter_cluster_distance(
    cluster_a: list[int],
    cluster_b: list[int],
    distances: dict[tuple[int, int], float],
) -> float:
    """Single-linkage: 两簇间最小节点对距离。"""
    min_d = float("inf")
    for ni in cluster_a:
        for nj in cluster_b:
            key = (min(ni, nj), max(ni, nj))
            d = distances.get(key, 1.0)
            if d < min_d:
                min_d = d
    return min_d


# ── 角色分配 ─────────────────────────────────────────────────


def assign_roles(
    cluster_node_ids: list[int],
    node_types: dict[int, str],
    adjacency: dict[int, set[int]],
) -> UnitCandidate:
    """为聚类中的节点分配角色：core / support / example / prerequisite_bridge。

    规则：
    - core: Topic/Concept/Method 且 degree 最高
    - support: 与 core 有 defined_by/part_of 边的 Definition/Method
    - example: Example 类型
    - prerequisite_bridge: 与 core 有 prerequisite_of 边但属于其他 unit 的引用
      （此处仅标记 cluster 内的 prerequisite 关系节点）
    """
    core_types = {"Topic", "Concept", "Method"}
    support_types = {"Definition", "Method"}

    core_ids: list[int] = []
    support_ids: list[int] = []
    example_ids: list[int] = []
    bridge_ids: list[int] = []

    # 按 degree 排序，高 degree 优先作为 core
    sorted_nodes = sorted(
        cluster_node_ids,
        key=lambda nid: len(adjacency.get(nid, set())),
        reverse=True,
    )

    assigned: set[int] = set()

    # 第一轮：选 core（至少一个）
    for nid in sorted_nodes:
        nt = node_types.get(nid, "Concept")
        if nt in core_types and nid not in assigned:
            core_ids.append(nid)
            assigned.add(nid)

    # 如果没有 core 类型节点，选 degree 最高的作为 core
    if not core_ids and sorted_nodes:
        core_ids.append(sorted_nodes[0])
        assigned.add(sorted_nodes[0])

    # 第二轮：分配剩余节点
    for nid in cluster_node_ids:
        if nid in assigned:
            continue
        nt = node_types.get(nid, "Concept")
        if nt == "Example":
            example_ids.append(nid)
        elif nt in support_types:
            support_ids.append(nid)
        else:
            # 其他类型归入 support
            support_ids.append(nid)
        assigned.add(nid)

    return UnitCandidate(
        core_node_ids=core_ids,
        support_node_ids=support_ids,
        example_node_ids=example_ids,
        bridge_node_ids=bridge_ids,
        cluster_score=1.0 / max(len(cluster_node_ids), 1),
    )


# ── LLM 命名 ─────────────────────────────────────────────────


async def _name_unit_with_llm(
    node_infos: dict[int, _NodeInfo],
    candidate: UnitCandidate,
) -> UnitNamingResponse:
    """调用 LLM 为教学单元生成名称、摘要和学习目标。"""
    def _format_nodes(ids: list[int]) -> str:
        parts = []
        for nid in ids:
            info = node_infos.get(nid)
            if info:
                parts.append(f"- {info.canonical_name}（{info.node_type}）：{info.summary}")
        return "\n".join(parts) if parts else "无"

    user_content = populate_prompt(
        USER_PROMPT_KG_UNIT_NAMING,
        core_nodes=_format_nodes(candidate.core_node_ids),
        support_nodes=_format_nodes(candidate.support_node_ids),
        example_nodes=_format_nodes(candidate.example_node_ids),
    )

    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_KG_UNIT_NAMING},
        {"role": USER, "content": user_content},
    ]

    return await acompletion_structured(
        response_model=UnitNamingResponse,
        messages=messages,
    )


def _fallback_unit_name(
    node_infos: dict[int, _NodeInfo],
    candidate: UnitCandidate,
) -> UnitNamingResponse:
    """LLM 命名失败时的 fallback：使用 core 节点名称。"""
    core_names = [
        node_infos[nid].canonical_name
        for nid in candidate.core_node_ids
        if nid in node_infos
    ]
    title = "、".join(core_names[:3]) if core_names else "未命名单元"
    return UnitNamingResponse(
        title=title,
        summary=f"包含 {title} 等知识点的教学单元",
        learning_objectives=[f"理解 {title} 的核心概念"],
    )


# ── 节点信息加载 ──────────────────────────────────────────────


def _load_node_infos(
    session: Session,
    nodes: list[KnowledgeNode],
) -> dict[int, _NodeInfo]:
    """加载节点的 canonical_name + current revision summary。"""
    infos: dict[int, _NodeInfo] = {}
    for node in nodes:
        summary = ""
        if node.current_revision_id is not None:
            rev = session.get(KnowledgeRevision, node.current_revision_id)
            if rev:
                summary = rev.summary
        infos[node.id] = _NodeInfo(  # type: ignore[arg-type]
            node_id=node.id,  # type: ignore[arg-type]
            node_type=node.node_type,
            canonical_name=node.canonical_name,
            summary=summary,
        )
    return infos


# ── 单元 Upsert ──────────────────────────────────────────────


def _get_max_revision_no(session: Session, unit_id: int) -> int:
    """获取教学单元当前最大 revision_no。"""
    stmt = select(TeachingUnitRevision.revision_no).where(
        TeachingUnitRevision.unit_id == unit_id,
    ).order_by(TeachingUnitRevision.revision_no.desc()).limit(1)  # type: ignore[union-attr]
    result = session.exec(stmt).first()
    return result if result is not None else 0


def _upsert_unit(
    session: Session,
    subject: str,
    candidate: UnitCandidate,
    naming: UnitNamingResponse,
    curriculum_job_id: int,
    node_infos: dict[int, _NodeInfo],
) -> TeachingUnit:
    """创建或更新教学单元。

    - 通过 member_signature 查找已有单元
    - 已有 → 更新 revision，不重建 unit，不改 unit status
    - 新建 → 创建 pending unit + revision + memberships
    """
    signature = compute_member_signature(candidate.core_node_ids)
    existing = curriculum_repo.find_unit_by_signature(session, subject, signature)

    if existing is not None:
        # 已有单元：更新 revision
        curriculum_repo.deactivate_old_unit_revisions(session, existing.id)  # type: ignore[arg-type]
        rev_no = _get_max_revision_no(session, existing.id) + 1  # type: ignore[arg-type]
        revision = TeachingUnitRevision(
            unit_id=existing.id,  # type: ignore[arg-type]
            revision_no=rev_no,
            title=naming.title,
            summary=naming.summary,
            learning_objectives_json=json.dumps(
                naming.learning_objectives, ensure_ascii=False,
            ),
            revision_reason="new_evidence",
            is_current=True,
        )
        revision = curriculum_repo.create_unit_revision(session, revision)
        existing.current_revision_id = revision.id
        existing.canonical_name = naming.title
        existing.normalized_name = normalize_name(naming.title)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        logger.info("unit_updated", unit_id=existing.id, title=naming.title)
        return existing

    # 新建单元
    unit = TeachingUnit(
        subject=subject,
        canonical_name=naming.title,
        normalized_name=normalize_name(naming.title),
        member_signature=signature,
        status="pending",
        confidence=1.0,
    )
    unit = curriculum_repo.create_teaching_unit(session, unit)

    # 创建初始 revision
    revision = TeachingUnitRevision(
        unit_id=unit.id,  # type: ignore[arg-type]
        revision_no=1,
        title=naming.title,
        summary=naming.summary,
        learning_objectives_json=json.dumps(
            naming.learning_objectives, ensure_ascii=False,
        ),
        revision_reason="new_evidence",
        is_current=True,
    )
    revision = curriculum_repo.create_unit_revision(session, revision)
    unit.current_revision_id = revision.id
    session.add(unit)
    session.commit()
    session.refresh(unit)

    # 创建 memberships
    _create_memberships(session, unit, candidate)

    logger.info("unit_created", unit_id=unit.id, title=naming.title)
    return unit


def _create_memberships(
    session: Session,
    unit: TeachingUnit,
    candidate: UnitCandidate,
) -> None:
    """为教学单元创建成员关系。"""
    role_map = [
        (candidate.core_node_ids, "core"),
        (candidate.support_node_ids, "support"),
        (candidate.example_node_ids, "example"),
        (candidate.bridge_node_ids, "prerequisite_bridge"),
    ]
    for node_ids, role in role_map:
        for nid in node_ids:
            membership = TeachingUnitMembership(
                unit_id=unit.id,  # type: ignore[arg-type]
                knowledge_node_id=nid,
                role=role,
                score=1.0 if role == "core" else 0.5,
            )
            curriculum_repo.create_unit_membership(session, membership)


# ── 主入口 ────────────────────────────────────────────────────


async def derive_teaching_units(
    session: Session,
    subject: str,
    impact_set: ImpactSet,
    curriculum_job_id: int,
) -> list[TeachingUnit]:
    """教学单元生成主入口：子图提取 → 聚类 → 命名 → Upsert。

    Args:
        session: 数据库会话。
        subject: 学科标识。
        impact_set: 影响集。
        curriculum_job_id: 课程派生任务 ID。

    Returns:
        本次生成/更新的教学单元列表。
    """
    # Step 1: 提取局部子图
    nodes, edges = extract_local_subgraph(session, subject, impact_set)
    if not nodes:
        logger.info("no_nodes_for_unit_derivation", subject=subject)
        return []

    node_ids = [n.id for n in nodes]  # type: ignore[misc]
    node_types = {n.id: n.node_type for n in nodes}  # type: ignore[misc]
    node_infos = _load_node_infos(session, nodes)

    # Step 2: 生成 embeddings
    embed_texts = [
        f"{info.canonical_name}：{info.summary}"
        for info in node_infos.values()
    ]
    embed_ids = list(node_infos.keys())
    raw_embeddings = await aembed_texts(embed_texts)
    embeddings: dict[int, list[float]] = dict(zip(embed_ids, raw_embeddings))

    # Step 3: 构建图结构索引
    adjacency, strong_adjacency, prereq_pairs = _build_graph_indices(edges)
    chunk_co_occurrence = _build_chunk_co_occurrence(
        session, {n.id for n in nodes},  # type: ignore[misc]
    )

    # Step 4: 计算 pairwise 距离
    distances = compute_pairwise_distances(
        node_ids, embeddings, adjacency, strong_adjacency,
        chunk_co_occurrence, prereq_pairs, node_types,
    )

    # Step 5: 层次聚类
    clusters = agglomerative_cluster(node_ids, distances)
    logger.info("clustering_complete", cluster_count=len(clusters), node_count=len(node_ids))

    # Step 6: 角色分配 + 签名匹配 + LLM 命名 + Upsert
    units: list[TeachingUnit] = []
    for cluster_nodes in clusters:
        if len(cluster_nodes) < _MIN_CLUSTER_SIZE:
            continue

        candidate = assign_roles(cluster_nodes, node_types, adjacency)

        # LLM 命名（失败时 fallback）
        try:
            naming = await _name_unit_with_llm(node_infos, candidate)
        except Exception:
            logger.warning(
                "unit_naming_llm_failed",
                core_ids=candidate.core_node_ids,
                exc_info=True,
            )
            naming = _fallback_unit_name(node_infos, candidate)

        unit = _upsert_unit(
            session, subject, candidate, naming, curriculum_job_id, node_infos,
        )
        units.append(unit)

    logger.info(
        "derive_teaching_units_complete",
        subject=subject,
        units_count=len(units),
    )
    return units
