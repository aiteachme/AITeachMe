"""鎵瑰唴鍊欓€夎仛绫伙細鍩轰簬 normalized_name + embedding 鐩镐技搴︾殑鎵瑰唴鍘婚噸鑱氱被銆?""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
import re

import structlog

from app.workflows.digest.knowledge_graph.services.candidate_identity import (
    bucket_scope,
    candidate_lookup_keys,
    token_bucket,
)
from app.workflows.digest.knowledge_graph.services.extractor import CandidateNode
from app.shared.infra.embedding import aembed_texts
from app.utils.kg_helpers import normalize_name

logger = structlog.get_logger()
_SECONDARY_NODE_TYPES = {"Definition", "Example"}


@dataclass
class ClusteredCandidate:
    """鑱氱被鍚庣殑鍊欓€夎妭鐐逛唬琛ㄣ€?""

    representative: CandidateNode
    members: list[CandidateNode] = field(default_factory=list)
    source_chunk_ids: list[int] = field(default_factory=list)
    merged_summary: str = ""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """璁＄畻涓や釜鍚戦噺鐨勪綑寮︾浉浼煎害銆?""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _merge_summaries(members: list[CandidateNode]) -> str:
    """鍚堝苟澶氫釜鍊欓€夎妭鐐圭殑鎽樿锛屽幓閲嶅悗鎷兼帴銆?""
    seen: set[str] = set()
    parts: list[str] = []
    for m in members:
        s = m.local_summary.strip()
        if s and s not in seen:
            seen.add(s)
            parts.append(s)
    return "锛?.join(parts)


async def cluster_candidates(
    candidates: list[tuple[CandidateNode, int]],
    similarity_threshold: float = 0.85,
) -> tuple[list[ClusteredCandidate], dict[str, int]]:
    """瀵瑰悓涓€鎵规鎶藉彇鐨勫€欓€夎妭鐐硅繘琛屾壒鍐呭幓閲嶈仛绫汇€?
    鑱氱被绛栫暐锛?    1. 鎸?(node_type, normalized_name) 绮剧‘鍒嗙粍鈥斺€斿悕绉板畬鍏ㄤ竴鑷寸殑鐩存帴鍚堝苟銆?    2. 鍚?node_type 鍐咃紝瀵瑰悕绉颁笉鍚岀殑鍊欓€夎绠?embedding 鐩镐技搴︼紝
       瓒呰繃 similarity_threshold 鐨勫悎骞跺埌鍚屼竴绨囥€?
    Args:
        candidates: (CandidateNode, chunk_id) 鍏冪粍鍒楄〃銆?        similarity_threshold: embedding 鐩镐技搴﹂槇鍊硷紝榛樿 0.85銆?
    Returns:
        (clustered_candidates, candidate_lookup_to_cluster_id) 鍏冪粍銆?        candidate_lookup_to_cluster_id 灏嗗€欓€?id / typed lookup key 鏄犲皠鍒拌仛绫讳唬琛ㄧ殑绱㈠紩锛?        渚涘悗缁竟瑙ｆ瀽浣跨敤銆?    """
    if not candidates:
        return [], {}

    # 鈹€鈹€ Step 1: 鎸?(node_type, normalized_name) 绮剧‘鍒嗙粍 鈹€鈹€
    group_key_to_members: dict[tuple[str, str], list[tuple[CandidateNode, int]]] = defaultdict(list)
    for cand, chunk_id in candidates:
        scope_key = bucket_scope(cand) if cand.node_type in _SECONDARY_NODE_TYPES else ""
        key = (cand.node_type, f"{normalize_name(cand.name)}::{scope_key}")
        group_key_to_members[key].append((cand, chunk_id))

    # 鏋勫缓鍒濆绨囧垪琛?    proto_clusters: list[list[tuple[CandidateNode, int]]] = list(group_key_to_members.values())

    # 鈹€鈹€ Step 2: 鍚?node_type 鍐?embedding 鐩镐技搴﹀悎骞?鈹€鈹€
    # 涓烘瘡涓皣鐨勪唬琛ㄧ敓鎴?embedding
    repr_texts = [cluster[0][0].name + "锛? + cluster[0][0].local_summary for cluster in proto_clusters]
    embeddings = await aembed_texts(repr_texts)

    # 鎸?node_type + taxonomy bucket + token bucket 鍒嗘《锛岄伩鍏?O(n虏) 鎵暣绫汇€?    bucket_to_indices: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for idx, cluster in enumerate(proto_clusters):
        representative = cluster[0][0]
        bucket_to_indices[
            (
                representative.node_type,
                bucket_scope(representative),
                token_bucket(representative.name),
            )
        ].append(idx)

    # Union-Find 鍚堝苟
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

    compared_pairs = 0
    for indices in bucket_to_indices.values():
        if len(indices) <= 1:
            continue
        for idx_a, idx_b in combinations(indices, 2):
            if find(idx_a) == find(idx_b):
                continue
            sim = _cosine_similarity(embeddings[idx_a], embeddings[idx_b])
            compared_pairs += 1
            if sim >= similarity_threshold:
                union(idx_a, idx_b)

    # 鏀堕泦鏈€缁堢皣
    root_to_members: dict[int, list[tuple[CandidateNode, int]]] = defaultdict(list)
    for idx, cluster in enumerate(proto_clusters):
        root = find(idx)
        root_to_members[root].extend(cluster)

    # 鈹€鈹€ Step 3: 鏋勫缓杈撳嚭 鈹€鈹€
    clustered: list[ClusteredCandidate] = []
    candidate_lookup_to_cluster_id: dict[str, int] = {}

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

        # 鏄犲皠鎵€鏈夋垚鍛?id / typed lookup key 鍒版绨囩储寮?        for node in nodes:
            for lookup_key in candidate_lookup_keys(node):
                candidate_lookup_to_cluster_id[lookup_key] = cluster_idx

    logger.info(
        "kg_cluster_complete",
        input_count=len(candidates),
        cluster_count=len(clustered),
        compared_pairs=compared_pairs,
        bucket_count=len(bucket_to_indices),
    )
    return clustered, candidate_lookup_to_cluster_id

