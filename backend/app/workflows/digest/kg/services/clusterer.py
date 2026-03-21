"""批内候选聚类：基于 normalized_name + embedding 相似度的批内去重聚类。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import structlog

from app.workflows.digest.kg.services.extractor import CandidateNode
from app.core.embedding import aembed_texts
from app.utils.kg_helpers import normalize_name

logger = structlog.get_logger()


@dataclass
class ClusteredCandidate:
    """聚类后的候选节点代表。"""

    representative: CandidateNode
    members: list[CandidateNode] = field(default_factory=list)
    source_chunk_ids: list[int] = field(default_factory=list)
    merged_summary: str = ""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _merge_summaries(members: list[CandidateNode]) -> str:
    """合并多个候选节点的摘要，去重后拼接。"""
    seen: set[str] = set()
    parts: list[str] = []
    for m in members:
        s = m.local_summary.strip()
        if s and s not in seen:
            seen.add(s)
            parts.append(s)
    return "；".join(parts)


async def cluster_candidates(
    candidates: list[tuple[CandidateNode, int]],
    similarity_threshold: float = 0.85,
) -> tuple[list[ClusteredCandidate], dict[str, int]]:
    """对同一批次抽取的候选节点进行批内去重聚类。

    聚类策略：
    1. 按 (node_type, normalized_name) 精确分组——名称完全一致的直接合并。
    2. 同 node_type 内，对名称不同的候选计算 embedding 相似度，
       超过 similarity_threshold 的合并到同一簇。

    Args:
        candidates: (CandidateNode, chunk_id) 元组列表。
        similarity_threshold: embedding 相似度阈值，默认 0.85。

    Returns:
        (clustered_candidates, candidate_name_to_cluster_id) 元组。
        candidate_name_to_cluster_id 将原始候选名称映射到聚类代表的索引，
        供后续边解析使用。
    """
    if not candidates:
        return [], {}

    # ── Step 1: 按 (node_type, normalized_name) 精确分组 ──
    group_key_to_members: dict[tuple[str, str], list[tuple[CandidateNode, int]]] = defaultdict(list)
    for cand, chunk_id in candidates:
        key = (cand.node_type, normalize_name(cand.name))
        group_key_to_members[key].append((cand, chunk_id))

    # 构建初始簇列表
    proto_clusters: list[list[tuple[CandidateNode, int]]] = list(group_key_to_members.values())

    # ── Step 2: 同 node_type 内 embedding 相似度合并 ──
    # 为每个簇的代表生成 embedding
    repr_texts = [cluster[0][0].name + "：" + cluster[0][0].local_summary for cluster in proto_clusters]
    embeddings = await aembed_texts(repr_texts)

    # 按 node_type 分组簇索引
    type_to_indices: dict[str, list[int]] = defaultdict(list)
    for idx, cluster in enumerate(proto_clusters):
        type_to_indices[cluster[0][0].node_type].append(idx)

    # Union-Find 合并
    parent = list(range(len(proto_clusters)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for indices in type_to_indices.values():
        for i in range(len(indices)):
            for j in range(i + 1, len(indices)):
                idx_a, idx_b = indices[i], indices[j]
                if find(idx_a) == find(idx_b):
                    continue
                sim = _cosine_similarity(embeddings[idx_a], embeddings[idx_b])
                if sim >= similarity_threshold:
                    union(idx_a, idx_b)

    # 收集最终簇
    root_to_members: dict[int, list[tuple[CandidateNode, int]]] = defaultdict(list)
    for idx, cluster in enumerate(proto_clusters):
        root = find(idx)
        root_to_members[root].extend(cluster)

    # ── Step 3: 构建输出 ──
    clustered: list[ClusteredCandidate] = []
    candidate_name_to_cluster_id: dict[str, int] = {}

    for cluster_idx, (_, members) in enumerate(sorted(root_to_members.items())):
        nodes = [m[0] for m in members]
        chunk_ids = [m[1] for m in members]
        representative = nodes[0]

        cc = ClusteredCandidate(
            representative=representative,
            members=nodes,
            source_chunk_ids=chunk_ids,
            merged_summary=_merge_summaries(nodes),
        )
        clustered.append(cc)

        # 映射所有成员名称到此簇索引
        for node in nodes:
            candidate_name_to_cluster_id[node.name] = cluster_idx

    logger.info(
        "kg_cluster_complete",
        input_count=len(candidates),
        cluster_count=len(clustered),
    )
    return clustered, candidate_name_to_cluster_id
