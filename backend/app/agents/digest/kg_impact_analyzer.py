"""影响集分析器：基于图谱变更计算四层闭包影响集。

四层闭包规则：
1. 图谱层 — changed nodes → incident edges → 2-hop candidate recompute nodes
2. 教学单元层 — 包含 changed nodes 的 units + 强关系邻接 units
3. 树视图层 — affected units 的 tree memberships + 祖先路径 + 锚点子树
4. DAG 层 — source/target 落在 affected units 中的 dependency edges
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from sqlmodel import Session, or_, select

from app.models.curriculum import (
    PrereqDagVersion,
    TeachingUnitMembership,
    ThemeTreeNode,
    ThemeTreeVersion,
    UnitDependency,
    UnitTreeMembership,
)
from app.models.knowledge_graph import KnowledgeEdge

logger = structlog.get_logger(__name__)


@dataclass
class ImpactSet:
    """增量构建影响集，包含四层闭包。"""

    # === 图谱层闭包 ===
    changed_node_ids: set[int] = field(default_factory=set)
    affected_edge_ids: set[int] = field(default_factory=set)
    candidate_recompute_node_ids: set[int] = field(default_factory=set)

    # === 教学单元层闭包 ===
    affected_unit_ids: set[int] = field(default_factory=set)

    # === 树视图层闭包 ===
    affected_anchor_ids: set[int] = field(default_factory=set)
    affected_tree_node_ids: set[int] = field(default_factory=set)

    # === DAG 层闭包 ===
    affected_dag_edge_ids: set[int] = field(default_factory=set)


def analyze_impact(
    session: Session,
    subject: str,
    new_node_ids: list[int],
    updated_node_ids: list[int],
    merged_node_ids: list[int],
    split_node_ids: list[int],
) -> ImpactSet:
    """基于已落库状态 + 当前课程结构版本状态，计算四层闭包影响集。

    Args:
        session: 数据库会话
        subject: 学科标识
        new_node_ids: 本次新增的节点 ID
        updated_node_ids: 本次更新的节点 ID
        merged_node_ids: 本次合并的节点 ID
        split_node_ids: 本次拆分的节点 ID

    Returns:
        ImpactSet 包含四层闭包的完整影响集
    """
    impact = ImpactSet()

    # ── 第一层：图谱层闭包 ──
    _compute_graph_layer(session, subject, impact,
                         new_node_ids, updated_node_ids,
                         merged_node_ids, split_node_ids)

    # ── 第二层：教学单元层闭包 ──
    _compute_unit_layer(session, impact)

    # ── 第三层：树视图层闭包 ──
    _compute_tree_layer(session, subject, impact)

    # ── 第四层：DAG 层闭包 ──
    _compute_dag_layer(session, subject, impact)

    logger.info(
        "impact_analysis_complete",
        subject=subject,
        changed_nodes=len(impact.changed_node_ids),
        affected_edges=len(impact.affected_edge_ids),
        candidate_recompute_nodes=len(impact.candidate_recompute_node_ids),
        affected_units=len(impact.affected_unit_ids),
        affected_tree_nodes=len(impact.affected_tree_node_ids),
        affected_dag_edges=len(impact.affected_dag_edge_ids),
    )
    return impact


# ── 内部实现 ──────────────────────────────────────────────────────────


def _compute_graph_layer(
    session: Session,
    subject: str,
    impact: ImpactSet,
    new_node_ids: list[int],
    updated_node_ids: list[int],
    merged_node_ids: list[int],
    split_node_ids: list[int],
) -> None:
    """第一层：图谱层闭包。

    - changed_node_ids = 新增 ∪ 更新 ∪ 合并 ∪ 拆分
    - affected_edge_ids = 与 changed nodes incident 的 active edges
    - candidate_recompute_node_ids = incident edges 对端的 2-hop nodes
    """
    impact.changed_node_ids = set(new_node_ids) | set(updated_node_ids) | set(merged_node_ids) | set(split_node_ids)

    if not impact.changed_node_ids:
        return

    # 查询与 changed nodes incident 的 active edges（1-hop）
    incident_edges = session.exec(
        select(KnowledgeEdge).where(
            KnowledgeEdge.subject == subject,
            KnowledgeEdge.status == "active",
            or_(
                KnowledgeEdge.source_node_id.in_(impact.changed_node_ids),  # type: ignore[union-attr]
                KnowledgeEdge.target_node_id.in_(impact.changed_node_ids),  # type: ignore[union-attr]
            ),
        )
    ).all()

    # 收集 1-hop 邻居节点
    one_hop_neighbor_ids: set[int] = set()
    for edge in incident_edges:
        impact.affected_edge_ids.add(edge.id)  # type: ignore[arg-type]
        one_hop_neighbor_ids.add(edge.source_node_id)
        one_hop_neighbor_ids.add(edge.target_node_id)

    one_hop_neighbor_ids -= impact.changed_node_ids

    # 查询 2-hop edges（从 1-hop 邻居出发的 active edges）
    if one_hop_neighbor_ids:
        two_hop_edges = session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "active",
                or_(
                    KnowledgeEdge.source_node_id.in_(one_hop_neighbor_ids),  # type: ignore[union-attr]
                    KnowledgeEdge.target_node_id.in_(one_hop_neighbor_ids),  # type: ignore[union-attr]
                ),
            )
        ).all()

        two_hop_node_ids: set[int] = set()
        for edge in two_hop_edges:
            two_hop_node_ids.add(edge.source_node_id)
            two_hop_node_ids.add(edge.target_node_id)

        # candidate_recompute = 1-hop ∪ 2-hop 对端，排除 changed nodes 自身
        impact.candidate_recompute_node_ids = (
            one_hop_neighbor_ids | two_hop_node_ids
        ) - impact.changed_node_ids
    else:
        impact.candidate_recompute_node_ids = set()


def _compute_unit_layer(session: Session, impact: ImpactSet) -> None:
    """第二层：教学单元层闭包。

    affected_unit_ids =
      包含 changed nodes 的现有 units
      ∪ 与 changed nodes 存在强关系边的邻接 units（通过 affected edges 的对端节点）
    """
    if not impact.changed_node_ids:
        return

    # 查找包含 changed nodes 的 units（通过 membership）
    all_relevant_node_ids = impact.changed_node_ids | impact.candidate_recompute_node_ids

    memberships = session.exec(
        select(TeachingUnitMembership).where(
            TeachingUnitMembership.knowledge_node_id.in_(all_relevant_node_ids),  # type: ignore[union-attr]
        )
    ).all()

    # changed nodes 直接所属的 units
    for m in memberships:
        if m.knowledge_node_id in impact.changed_node_ids:
            impact.affected_unit_ids.add(m.unit_id)

    # 通过 affected edges 的对端节点找到邻接 units
    # （对端节点在 candidate_recompute_node_ids 中）
    neighbor_unit_ids: set[int] = set()
    for m in memberships:
        if m.knowledge_node_id in impact.candidate_recompute_node_ids:
            neighbor_unit_ids.add(m.unit_id)

    impact.affected_unit_ids |= neighbor_unit_ids


def _compute_tree_layer(
    session: Session,
    subject: str,
    impact: ImpactSet,
) -> None:
    """第三层：树视图层闭包。

    affected_tree_node_ids =
      affected units 的 UnitTreeMembership 对应的 tree nodes
      ∪ 其祖先路径
    affected_anchor_ids =
      affected tree nodes 关联的 anchor ids
    """
    if not impact.affected_unit_ids:
        return

    # 获取当前 published 的 ThemeTreeVersion
    current_tree = session.exec(
        select(ThemeTreeVersion).where(
            ThemeTreeVersion.subject == subject,
            ThemeTreeVersion.status == "published",
        )
    ).first()

    if current_tree is None:
        return

    # 查找 affected units 在当前树中的 memberships
    tree_memberships = session.exec(
        select(UnitTreeMembership).where(
            UnitTreeMembership.tree_version_id == current_tree.id,
            UnitTreeMembership.teaching_unit_id.in_(impact.affected_unit_ids),  # type: ignore[union-attr]
        )
    ).all()

    directly_affected_tree_node_ids: set[int] = set()
    for tm in tree_memberships:
        directly_affected_tree_node_ids.add(tm.tree_node_id)

    # 加载当前树版本的所有节点，构建 parent 映射以追溯祖先路径
    all_tree_nodes = session.exec(
        select(ThemeTreeNode).where(
            ThemeTreeNode.tree_version_id == current_tree.id,
        )
    ).all()

    node_map: dict[int, ThemeTreeNode] = {n.id: n for n in all_tree_nodes}  # type: ignore[misc]

    # 从直接受影响的 tree nodes 向上追溯祖先路径
    visited: set[int] = set()
    queue = list(directly_affected_tree_node_ids)
    while queue:
        nid = queue.pop()
        if nid in visited:
            continue
        visited.add(nid)
        node = node_map.get(nid)
        if node and node.parent_tree_node_id is not None:
            queue.append(node.parent_tree_node_id)

    impact.affected_tree_node_ids = visited

    # 收集受影响 tree nodes 关联的 anchor ids
    for nid in visited:
        node = node_map.get(nid)
        if node and node.anchor_id is not None:
            impact.affected_anchor_ids.add(node.anchor_id)


def _compute_dag_layer(
    session: Session,
    subject: str,
    impact: ImpactSet,
) -> None:
    """第四层：DAG 层闭包。

    affected_dag_edge_ids =
      source_unit_id 或 target_unit_id 落在 affected_unit_ids 中的 dependency edges
    """
    if not impact.affected_unit_ids:
        return

    # 获取当前 published 的 PrereqDagVersion
    current_dag = session.exec(
        select(PrereqDagVersion).where(
            PrereqDagVersion.subject == subject,
            PrereqDagVersion.status == "published",
        )
    ).first()

    if current_dag is None:
        return

    # 查找 source 或 target 落在 affected units 中的 dependencies
    deps = session.exec(
        select(UnitDependency).where(
            UnitDependency.dag_version_id == current_dag.id,
            or_(
                UnitDependency.source_unit_id.in_(impact.affected_unit_ids),  # type: ignore[union-attr]
                UnitDependency.target_unit_id.in_(impact.affected_unit_ids),  # type: ignore[union-attr]
            ),
        )
    ).all()

    for dep in deps:
        impact.affected_dag_edge_ids.add(dep.id)  # type: ignore[arg-type]
