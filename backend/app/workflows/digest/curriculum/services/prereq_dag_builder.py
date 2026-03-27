"""先修 DAG 构建器：从知识图谱依赖边聚合出教学单元级别的先修 DAG。

算法流程（5 步）：
1. 收集节点级依赖边（prerequisite_of + part_of 约束传播 + defined_by 保守策略）
2. 聚合为单元级依赖（同一 unit 内部的依赖边不产生 UnitDependency）
3. 去环处理（Tarjan SCC + 断开 confidence 最低边）
4. 传递约简（transitive reduction，移除冗余间接依赖）
5. 生成 PrereqDagVersion(status="draft")

硬规则：
- 先去环再约简（transitive reduction 定义基于 DAG，对含环图行为未定义）
- 禁止调用任何 publish/archive helper；只能创建 draft version + UnitDependency
- 新建记录不再写入任何 *_job_id 字段
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field

import structlog
from sqlmodel import Session, select

from app.workflows.digest.kg.services.impact_analyzer import ImpactSet
from app.models.curriculum import (
    PrereqDagVersion,
    TeachingUnit,
    TeachingUnitMembership,
    UnitDependency,
)
from app.models.knowledge_graph import KnowledgeEdge
from app.repositories import curriculum_repo, kg_repo

logger = structlog.get_logger(__name__)

# ── 配置常量 ──

DEFINED_BY_CONFIDENCE_THRESHOLD = 0.7
"""defined_by 边生成跨 unit 依赖的最低置信度阈值。"""


# ── 数据类 ──


@dataclass
class UnitDependencyCandidate:
    """单元级依赖候选。"""

    source_unit_id: int  # 前置单元
    target_unit_id: int  # 后续单元
    dependency_type: str  # "prerequisite" | "corequisite"
    confidence: float
    supporting_edge_ids: list[int] = field(default_factory=list)
    supporting_edge_count: int = 0
    cycle_broken: bool = False  # 是否因去环被移除


# ── 核心算法函数 ──


def _build_node_to_unit_map(
    session: Session,
    subject: str,
) -> dict[int, int]:
    """构建 knowledge_node_id → unit_id 映射（仅 active units 的 core 成员）。

    Returns:
        node_id → unit_id 的映射字典
    """
    # 查询所有 active 单元
    active_units = session.exec(
        select(TeachingUnit).where(
            TeachingUnit.subject == subject,
            TeachingUnit.status == "active",
        )
    ).all()

    node_to_unit: dict[int, int] = {}
    for unit in active_units:
        memberships = curriculum_repo.list_memberships_by_unit(session, unit.id)  # type: ignore[arg-type]
        for m in memberships:
            # core 角色优先；support/example/bridge 也记录（用于依赖传播）
            if m.knowledge_node_id not in node_to_unit or m.role == "core":
                node_to_unit[m.knowledge_node_id] = m.unit_id
    return node_to_unit


def _collect_dependency_edges(
    session: Session,
    subject: str,
    node_to_unit: dict[int, int],
) -> list[tuple[int, int, int, float, str]]:
    """Step 1：收集节点级依赖边，返回 (source_node, target_node, edge_id, confidence, dep_type)。

    - prerequisite_of: A prerequisite_of B → A 是 B 的前置 → UnitDep(source=unit_A, target=unit_B)
    - part_of: A part_of B → B 的前置也是 A 的前置（约束传播）
    - defined_by: 保守策略，MVP 仅当满足高置信度条件时才生成跨 unit 候选
    """
    result: list[tuple[int, int, int, float, str]] = []

    # prerequisite_of 边：source 是前置，target 是后续
    prereq_edges = kg_repo.list_edges_by_type(session, subject, "prerequisite_of")
    for edge in prereq_edges:
        result.append((
            edge.source_node_id,
            edge.target_node_id,
            edge.id,  # type: ignore[arg-type]
            edge.confidence,
            "prerequisite",
        ))

    # part_of 边：A part_of B → B 的前置也是 A 的前置
    # 实现：如果 B 有 prerequisite_of 边指向 C，则 A 也依赖 C
    part_of_edges = kg_repo.list_edges_by_type(session, subject, "part_of")
    # 构建 child → parent 映射
    child_to_parents: dict[int, list[int]] = defaultdict(list)
    for edge in part_of_edges:
        child_to_parents[edge.source_node_id].append(edge.target_node_id)

    # 对每条 prerequisite 边，传播到 part_of 子节点
    for edge in prereq_edges:
        source_id = edge.source_node_id
        # 如果 source 有 children（通过 part_of），这些 children 也依赖 target
        # 但这里我们关注的是：如果 B 有前置 A，且 C part_of B，则 C 也依赖 A
        # 即 target 的 children 也需要 source 作为前置
        # 查找 target 的 children
        pass  # part_of 传播在下面统一处理

    # part_of 约束传播：A part_of B → A 继承 B 的所有前置依赖
    # 构建 parent → [prerequisite source nodes] 映射
    parent_prereqs: dict[int, list[tuple[int, float]]] = defaultdict(list)
    for edge in prereq_edges:
        parent_prereqs[edge.target_node_id].append((
            edge.source_node_id, edge.confidence,
        ))

    for po_edge in part_of_edges:
        child_id = po_edge.source_node_id
        parent_id = po_edge.target_node_id
        # child 继承 parent 的前置依赖
        for prereq_source_id, prereq_conf in parent_prereqs.get(parent_id, []):
            # 置信度取 part_of 边和 prerequisite 边的较低值
            combined_conf = min(po_edge.confidence, prereq_conf)
            result.append((
                prereq_source_id,
                child_id,
                po_edge.id,  # type: ignore[arg-type]
                combined_conf,
                "prerequisite",
            ))

    # defined_by 边：保守策略
    # MVP：仅当 Concept 与 Definition 已被分到不同 units 且满足高置信度时
    defined_by_edges = kg_repo.list_edges_by_type(session, subject, "defined_by")
    for edge in defined_by_edges:
        if edge.confidence <= DEFINED_BY_CONFIDENCE_THRESHOLD:
            continue
        src_unit = node_to_unit.get(edge.source_node_id)
        tgt_unit = node_to_unit.get(edge.target_node_id)
        if src_unit is None or tgt_unit is None:
            continue
        if src_unit == tgt_unit:
            continue  # 同一 unit 内，不生成跨 unit 依赖
        # defined_by: A defined_by B → B 定义了 A → B 是 A 的前置
        result.append((
            edge.target_node_id,  # 定义者是前置
            edge.source_node_id,  # 被定义者是后续
            edge.id,  # type: ignore[arg-type]
            edge.confidence * 0.8,  # 降权，因为 defined_by 不如 prerequisite_of 强
            "prerequisite",
        ))

    return result


def aggregate_unit_dependencies(
    dependency_edges: list[tuple[int, int, int, float, str]],
    node_to_unit: dict[int, int],
) -> list[UnitDependencyCandidate]:
    """Step 2：将节点级依赖边聚合为单元级依赖。

    同一 unit 内部的依赖边不产生 UnitDependency。
    """
    # 聚合键：(source_unit_id, target_unit_id, dep_type)
    agg: dict[tuple[int, int, str], UnitDependencyCandidate] = {}

    for src_node, tgt_node, edge_id, confidence, dep_type in dependency_edges:
        src_unit = node_to_unit.get(src_node)
        tgt_unit = node_to_unit.get(tgt_node)

        if src_unit is None or tgt_unit is None:
            continue  # 节点不属于任何 unit，跳过
        if src_unit == tgt_unit:
            continue  # 同一 unit 内部，不产生 UnitDependency

        key = (src_unit, tgt_unit, dep_type)
        if key not in agg:
            agg[key] = UnitDependencyCandidate(
                source_unit_id=src_unit,
                target_unit_id=tgt_unit,
                dependency_type=dep_type,
                confidence=0.0,
                supporting_edge_ids=[],
                supporting_edge_count=0,
            )
        cand = agg[key]
        cand.supporting_edge_ids.append(edge_id)
        cand.supporting_edge_count += 1

    # 计算聚合 confidence：加权平均
    for key, cand in agg.items():
        # 从原始边中收集对应的 confidence 值
        edge_confidences = []
        for src_node, tgt_node, edge_id, confidence, dep_type in dependency_edges:
            if edge_id in cand.supporting_edge_ids:
                edge_confidences.append(confidence)
        if edge_confidences:
            # confidence = weighted_sum / max_possible
            cand.confidence = min(0.95, sum(edge_confidences) / max(len(edge_confidences), 1))

    return list(agg.values())


def break_cycles(
    edges: list[UnitDependencyCandidate],
) -> tuple[list[UnitDependencyCandidate], list[UnitDependencyCandidate]]:
    """Step 3：去环处理（Tarjan SCC + 断开 confidence 最低边）。

    Returns:
        (acyclic_edges, broken_edges) — 无环边列表和被断开的边列表
    """
    if not edges:
        return [], []

    # 构建邻接表
    graph: dict[int, list[int]] = defaultdict(list)
    edge_map: dict[tuple[int, int], UnitDependencyCandidate] = {}
    nodes: set[int] = set()

    for e in edges:
        graph[e.source_unit_id].append(e.target_unit_id)
        edge_map[(e.source_unit_id, e.target_unit_id)] = e
        nodes.add(e.source_unit_id)
        nodes.add(e.target_unit_id)

    # Tarjan SCC 算法
    sccs = _tarjan_scc(graph, nodes)

    broken: list[UnitDependencyCandidate] = []
    removed_keys: set[tuple[int, int]] = set()

    # 对每个大小 > 1 的 SCC，迭代断开最低 confidence 边直到无环
    for scc in sccs:
        if len(scc) <= 1:
            continue

        scc_set = set(scc)
        # 收集 SCC 内部的边
        scc_edges = [
            e for e in edges
            if e.source_unit_id in scc_set
            and e.target_unit_id in scc_set
            and (e.source_unit_id, e.target_unit_id) not in removed_keys
        ]

        # 迭代断边直到 SCC 内无环
        while _has_cycle_in_subgraph(scc_edges):
            if not scc_edges:
                break
            # 找 confidence 最低的边
            weakest = min(scc_edges, key=lambda e: e.confidence)
            weakest.cycle_broken = True
            broken.append(weakest)
            removed_keys.add((weakest.source_unit_id, weakest.target_unit_id))
            scc_edges = [
                e for e in scc_edges
                if (e.source_unit_id, e.target_unit_id) not in removed_keys
            ]

    acyclic = [
        e for e in edges
        if (e.source_unit_id, e.target_unit_id) not in removed_keys
    ]

    if broken:
        logger.info(
            "dag_cycles_broken",
            broken_count=len(broken),
            broken_edges=[
                {"src": e.source_unit_id, "tgt": e.target_unit_id, "conf": e.confidence}
                for e in broken
            ],
        )

    return acyclic, broken


def _tarjan_scc(
    graph: dict[int, list[int]],
    nodes: set[int],
) -> list[list[int]]:
    """Tarjan 强连通分量算法。"""
    index_counter = [0]
    stack: list[int] = []
    on_stack: set[int] = set()
    index_map: dict[int, int] = {}
    lowlink: dict[int, int] = {}
    result: list[list[int]] = []

    def strongconnect(v: int) -> None:
        index_map[v] = index_counter[0]
        lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in graph.get(v, []):
            if w not in index_map:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index_map[w])

        if lowlink[v] == index_map[v]:
            component: list[int] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                component.append(w)
                if w == v:
                    break
            result.append(component)

    for node in nodes:
        if node not in index_map:
            strongconnect(node)

    return result


def _has_cycle_in_subgraph(edges: list[UnitDependencyCandidate]) -> bool:
    """检测边列表构成的子图是否含环（DFS 检测）。"""
    if not edges:
        return False

    graph: dict[int, list[int]] = defaultdict(list)
    nodes: set[int] = set()
    for e in edges:
        graph[e.source_unit_id].append(e.target_unit_id)
        nodes.add(e.source_unit_id)
        nodes.add(e.target_unit_id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[int, int] = {n: WHITE for n in nodes}

    def dfs(u: int) -> bool:
        color[u] = GRAY
        for v in graph.get(u, []):
            if color.get(v, WHITE) == GRAY:
                return True
            if color.get(v, WHITE) == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(color[n] == WHITE and dfs(n) for n in nodes)


def transitive_reduction(
    edges: list[UnitDependencyCandidate],
) -> list[UnitDependencyCandidate]:
    """Step 4：传递约简（Transitive Reduction）。

    对已确认无环的 DAG 执行传递约简：
    如果 A → B → C 且 A → C 同时存在，移除 A → C（冗余边）。

    算法：对每条边 (u, v)，检查是否存在不经过该边的 u → v 路径。
    若存在，则该边冗余，可移除。
    """
    if not edges:
        return []

    # 构建邻接表
    graph: dict[int, set[int]] = defaultdict(set)
    for e in edges:
        graph[e.source_unit_id].add(e.target_unit_id)

    # 对每条边检查是否冗余
    edge_set = {(e.source_unit_id, e.target_unit_id) for e in edges}
    redundant: set[tuple[int, int]] = set()

    for e in edges:
        u, v = e.source_unit_id, e.target_unit_id
        # 检查是否存在 u → ... → v 的路径（不直接经过 u → v）
        if _has_indirect_path(graph, u, v, edge_set):
            redundant.add((u, v))

    if redundant:
        logger.info(
            "dag_transitive_reduction",
            removed_count=len(redundant),
            removed_edges=list(redundant),
        )

    return [
        e for e in edges
        if (e.source_unit_id, e.target_unit_id) not in redundant
    ]


def _has_indirect_path(
    graph: dict[int, set[int]],
    source: int,
    target: int,
    all_edges: set[tuple[int, int]],
) -> bool:
    """检查从 source 到 target 是否存在不直接使用 source→target 边的路径。

    BFS 从 source 的其他邻居出发，看能否到达 target。
    """
    # 从 source 的邻居出发（排除直接到 target 的边）
    start_nodes = graph.get(source, set()) - {target}
    if not start_nodes:
        return False

    visited: set[int] = {source}
    queue = list(start_nodes)
    visited.update(start_nodes)

    while queue:
        current = queue.pop(0)
        if current == target:
            return True
        for neighbor in graph.get(current, set()):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)

    return False


# ── 主入口 ──


async def derive_prereq_dag(
    session: Session,
    subject: str,
    impact_set: ImpactSet,
    curriculum_job_id: int,
    prev_dag_version: PrereqDagVersion | None = None,
) -> PrereqDagVersion:
    """先修 DAG 派生主函数。

    按 Step 1-5 执行：收集 → 聚合 → 去环 → 约简 → 生成版本。
    MVP 采用"逻辑局部重算 + 存储全量快照"版本策略。

    Args:
        session: 数据库会话
        subject: 学科标识
        impact_set: 影响集
        curriculum_job_id: 当前 CurriculumDeriveJob ID
        prev_dag_version: 上一个 DAG 版本（用于确定版本号）

    Returns:
        新创建的 PrereqDagVersion（status="draft"）
    """
    logger.info(
        "prereq_dag_derive_start",
        subject=subject,
        curriculum_job_id=curriculum_job_id,
        affected_units=len(impact_set.affected_unit_ids),
    )

    # Step 1：构建 node → unit 映射 & 收集节点级依赖边
    node_to_unit = _build_node_to_unit_map(session, subject)
    dependency_edges = _collect_dependency_edges(session, subject, node_to_unit)

    logger.info(
        "prereq_dag_step1_edges_collected",
        total_dependency_edges=len(dependency_edges),
    )

    # Step 2：聚合为单元级依赖
    unit_deps = aggregate_unit_dependencies(dependency_edges, node_to_unit)

    logger.info(
        "prereq_dag_step2_aggregated",
        unit_dependency_candidates=len(unit_deps),
    )

    # Step 3：去环（硬规则：先去环再约简）
    acyclic_edges, broken_edges = break_cycles(unit_deps)

    logger.info(
        "prereq_dag_step3_cycles_broken",
        acyclic_count=len(acyclic_edges),
        broken_count=len(broken_edges),
    )

    # Step 4：传递约简
    reduced_edges = transitive_reduction(acyclic_edges)

    logger.info(
        "prereq_dag_step4_reduced",
        final_edge_count=len(reduced_edges),
        removed_by_reduction=len(acyclic_edges) - len(reduced_edges),
    )

    # Step 5：创建 PrereqDagVersion(status="draft") + UnitDependency 记录
    prev_version_no = prev_dag_version.version_no if prev_dag_version else 0
    dag_version = curriculum_repo.create_prereq_dag_version_with_optimistic_lock(
        session, subject, prev_version_no,
    )
    # 写入 UnitDependency 记录
    for edge_cand in reduced_edges:
        # 构建 derivation_metadata
        metadata = {
            "supporting_edge_ids": edge_cand.supporting_edge_ids,
            "confidence_details": {
                "aggregated_confidence": edge_cand.confidence,
                "supporting_edge_count": edge_cand.supporting_edge_count,
            },
        }

        dep = UnitDependency(
            subject=subject,
            dag_version_id=dag_version.id,  # type: ignore[arg-type]
            source_unit_id=edge_cand.source_unit_id,
            target_unit_id=edge_cand.target_unit_id,
            dependency_type=edge_cand.dependency_type,
            confidence=edge_cand.confidence,
            supporting_edge_count=edge_cand.supporting_edge_count,
            derivation_metadata_json=json.dumps(metadata, ensure_ascii=False),
        )
        curriculum_repo.create_unit_dependency(session, dep)

    # 记录被断开的环路边到日志（供人工审查）
    if broken_edges:
        for be in broken_edges:
            logger.warning(
                "prereq_dag_cycle_edge_broken",
                source_unit_id=be.source_unit_id,
                target_unit_id=be.target_unit_id,
                confidence=be.confidence,
                supporting_edge_ids=be.supporting_edge_ids,
            )

    logger.info(
        "prereq_dag_derive_complete",
        subject=subject,
        dag_version_id=dag_version.id,
        version_no=dag_version.version_no,
        total_dependencies=len(reduced_edges),
        cycles_broken=len(broken_edges),
    )

    return dag_version
