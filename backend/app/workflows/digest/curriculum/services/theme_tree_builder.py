"""主题树构建器：Anchor 软约束骨架 + 教学单元挂载 + membership_score 多源融合。

按 Step A-E 派生主题树：
  A. 生成 Anchor Skeleton（按优先级排序）
  B. 挂载 TeachingUnit 到树节点
  C. 计算 membership_score（6 源证据融合）
  D. 确定归属（human_fixed 绝对优先 → 稳定规则 → 待归类池）
  E. 生成 ThemeTreeVersion(status="draft")

硬规则：
- 禁止在 theme_tree_builder 内部调用任何 publish/archive helper
- 只能创建 draft version + ThemeTreeNode + UnitTreeMembership
- 所有新建记录设置 created_by_job_id
- 每个 ThemeTreeVersion 必须包含一个 UNCATEGORIZED 固定节点
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, select

from app.workflows.digest.kg.services.impact_analyzer import ImpactSet
from app.workflows.digest.prompts import (
    SYSTEM_PROMPT_KG_THEME_TREE,
    USER_PROMPT_KG_THEME_TREE,
)
from app.core.embedding import aembed_texts
from app.core.llm import acompletion_structured
from app.core.prompt_loader import populate_prompt
from app.models.curriculum import (
    TaxonomyAnchor,
    TeachingUnit,
    TeachingUnitMembership,
    TeachingUnitRevision,
    ThemeTreeNode,
    ThemeTreeVersion,
    UnitTreeMembership,
)
from app.models.knowledge_graph import EvidenceLink, KnowledgeRevision
from app.repositories import curriculum_repo
from app.schemas.llm import ChatMessage, SYSTEM, USER

logger = structlog.get_logger(__name__)

# ── 配置常量 ──────────────────────────────────────────────────

MEMBERSHIP_THRESHOLD = 0.5
STABILITY_THRESHOLD = 0.08

# Anchor 优先级（数值越小优先级越高）
_ANCHOR_PRIORITY: dict[str, int] = {
    "teacher_defined": 0,
    "syllabus": 1,
    "textbook_toc": 2,
    "graph_discovered": 3,
    "system": 4,
}

# membership_score 权重
_DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "semantic": 0.30,
    "doc_outline": 0.25,
    "chunk_header": 0.15,
    "neighbor_vote": 0.15,
    "belongs_to_topic": 0.10,
    "taxonomy_hint": 0.05,
}


# ── 数据类 ────────────────────────────────────────────────────


@dataclass
class _AnchorSkeleton:
    """锚点骨架节点，用于构建树结构。"""
    anchor: TaxonomyAnchor
    children: list[_AnchorSkeleton] = field(default_factory=list)


@dataclass
class _UnitInfo:
    """教学单元信息缓存。"""
    unit_id: int
    subject: str
    canonical_name: str
    summary: str
    core_node_ids: list[int]
    taxonomy_hints: list[str]
    source_chunk_ids: list[int]


@dataclass
class _MembershipCandidate:
    """单元对树节点的归属候选。"""
    tree_node_id: int
    anchor_id: int | None
    score: float


# ── LLM 自动生成锚点的 Pydantic 模型 ─────────────────────────


class _ChapterSpec(BaseModel):
    """LLM 生成的章节规格。"""
    title: str = PydanticField(description="章节标题")
    order: int = PydanticField(description="章节在模块内的排序")


class _ModuleSpec(BaseModel):
    """LLM 生成的模块规格。"""
    title: str = PydanticField(description="模块标题")
    order: int = PydanticField(description="模块排序")
    chapters: list[_ChapterSpec] = PydanticField(description="模块下的章节列表")


class _ThemeTreeStructure(BaseModel):
    """LLM 生成的主题树层级结构。"""
    modules: list[_ModuleSpec] = PydanticField(description="模块列表")


# ── 辅助函数 ──────────────────────────────────────────────────


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """余弦相似度。"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _normalize_text(text: str) -> str:
    """简单文本归一化用于模糊匹配。"""
    return text.strip().lower()


def _text_overlap_score(text_a: str, text_b: str) -> float:
    """基于字符重叠的简单匹配分数。"""
    a = _normalize_text(text_a)
    b = _normalize_text(text_b)
    if not a or not b:
        return 0.0
    # 检查包含关系
    if a in b or b in a:
        return 1.0
    # 基于共同字符比例
    set_a = set(a)
    set_b = set(b)
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    return len(intersection) / max(len(set_a), len(set_b))


def _load_unit_infos(
    session: Session,
    units: list[TeachingUnit],
) -> dict[int, _UnitInfo]:
    """加载教学单元的详细信息（名称、摘要、核心节点、taxonomy_hints）。"""
    infos: dict[int, _UnitInfo] = {}
    for unit in units:
        summary = ""
        if unit.current_revision_id is not None:
            rev = session.get(TeachingUnitRevision, unit.current_revision_id)
            if rev:
                summary = rev.summary

        # 加载成员节点
        memberships = curriculum_repo.list_memberships_by_unit(
            session, unit.id,  # type: ignore[arg-type]
        )
        core_node_ids = [
            m.knowledge_node_id for m in memberships if m.role == "core"
        ]

        # 收集 taxonomy_hints（从 evidence_links 中提取）
        taxonomy_hints: list[str] = []
        source_chunk_ids: list[int] = []
        for m in memberships:
            evidence_stmt = select(EvidenceLink).where(
                EvidenceLink.entity_type == "node",
                EvidenceLink.entity_id == m.knowledge_node_id,
                EvidenceLink.is_active == True,  # noqa: E712
            )
            for ev in session.exec(evidence_stmt).all():
                if ev.chunk_id not in source_chunk_ids:
                    source_chunk_ids.append(ev.chunk_id)
                if ev.evidence_role == "taxonomy_hint" and ev.quote_text:
                    taxonomy_hints.append(ev.quote_text)

        infos[unit.id] = _UnitInfo(  # type: ignore[arg-type]
            unit_id=unit.id,  # type: ignore[arg-type]
            subject=unit.subject,
            canonical_name=unit.canonical_name,
            summary=summary,
            core_node_ids=core_node_ids,
            taxonomy_hints=taxonomy_hints,
            source_chunk_ids=source_chunk_ids,
        )
    return infos


# ── Step A-0: LLM 自动生成锚点 ───────────────────────────────


async def _auto_generate_anchors(
    session: Session,
    subject: str,
    units: list[TeachingUnit],
) -> list[TaxonomyAnchor]:
    """当无用户定义锚点时，调用 LLM 自动生成 module/chapter 层级锚点。

    Args:
        session: 数据库会话。
        subject: 学科标识。
        units: 当前学科的教学单元列表。

    Returns:
        新创建的 TaxonomyAnchor 列表。
    """
    if not units:
        return []

    # 收集单元信息用于 LLM 输入
    unit_summaries: list[dict[str, str]] = []
    for unit in units:
        summary = ""
        if unit.current_revision_id is not None:
            rev = session.get(TeachingUnitRevision, unit.current_revision_id)
            if rev:
                summary = rev.summary
        unit_summaries.append({
            "name": unit.canonical_name,
            "summary": summary or unit.canonical_name,
        })

    user_content = populate_prompt(
        USER_PROMPT_KG_THEME_TREE,
        subject=subject,
        units=unit_summaries,
    )

    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_KG_THEME_TREE},
        {"role": USER, "content": user_content},
    ]

    structure = await acompletion_structured(
        response_model=_ThemeTreeStructure,
        messages=messages,
    )

    logger.info(
        "llm_theme_tree_generated",
        subject=subject,
        modules=len(structure.modules),
        chapters=sum(len(m.chapters) for m in structure.modules),
    )

    # 创建 TaxonomyAnchor 记录
    created_anchors: list[TaxonomyAnchor] = []
    for module in sorted(structure.modules, key=lambda m: m.order):
        module_anchor = curriculum_repo.create_taxonomy_anchor(
            session,
            TaxonomyAnchor(
                subject=subject,
                anchor_type="graph_discovered",
                title=module.title,
                normalized_title=module.title.strip().lower(),
                parent_anchor_id=None,
                order_index=module.order,
                confidence=0.8,
                is_system=False,
                status="active",
            ),
        )
        created_anchors.append(module_anchor)

        for chapter in sorted(module.chapters, key=lambda c: c.order):
            chapter_anchor = curriculum_repo.create_taxonomy_anchor(
                session,
                TaxonomyAnchor(
                    subject=subject,
                    anchor_type="graph_discovered",
                    title=chapter.title,
                    normalized_title=chapter.title.strip().lower(),
                    parent_anchor_id=module_anchor.id,
                    order_index=chapter.order,
                    confidence=0.8,
                    is_system=False,
                    status="active",
                ),
            )
            created_anchors.append(chapter_anchor)

    return created_anchors


# ── Step A: Anchor Skeleton ───────────────────────────────────


def _build_anchor_skeleton(
    session: Session,
    subject: str,
) -> list[_AnchorSkeleton]:
    """按优先级排序构建锚点骨架树。

    - teacher_defined / syllabus 作为高优先级约束
    - textbook_toc 作为中优先级参考
    - graph_discovered 作为自动发现补充
    - system（待归类）始终存在
    """
    anchors = curriculum_repo.list_anchors_by_subject(session, subject)
    if not anchors:
        # 确保至少有"待归类"系统锚点
        curriculum_repo.get_uncategorized_anchor(session, subject)
        anchors = curriculum_repo.list_anchors_by_subject(session, subject)

    # 按优先级 + order_index 排序
    anchors.sort(
        key=lambda a: (_ANCHOR_PRIORITY.get(a.anchor_type, 99), a.order_index)
    )

    # 构建 parent → children 映射
    anchor_map: dict[int, TaxonomyAnchor] = {
        a.id: a for a in anchors  # type: ignore[misc]
    }
    children_map: dict[int | None, list[TaxonomyAnchor]] = {}
    for a in anchors:
        parent_id = a.parent_anchor_id
        children_map.setdefault(parent_id, []).append(a)

    def _build_tree(parent_id: int | None) -> list[_AnchorSkeleton]:
        result: list[_AnchorSkeleton] = []
        for anchor in children_map.get(parent_id, []):
            skeleton = _AnchorSkeleton(
                anchor=anchor,
                children=_build_tree(anchor.id),  # type: ignore[arg-type]
            )
            result.append(skeleton)
        return result

    return _build_tree(None)


# ── Step C: membership_score 计算 ─────────────────────────────


def compute_unit_membership_score(
    unit_embedding: list[float],
    anchor_embedding: list[float],
    taxonomy_hints: list[str],
    anchor_title: str,
    neighbor_scores: float = 0.0,
    belongs_to_topic_score: float = 0.0,
    doc_outline_score: float = 0.0,
    chunk_header_score: float = 0.0,
    weights: dict[str, float] | None = None,
) -> float:
    """计算教学单元对锚点的 membership_score（6 源证据融合）。

    score = w1 * semantic_similarity
          + w2 * doc_outline_match
          + w3 * chunk_header_match
          + w4 * neighbor_vote
          + w5 * belongs_to_topic_propagation
          + w6 * taxonomy_hint_match
    """
    w = weights or _DEFAULT_SCORE_WEIGHTS

    # 1. 语义相似度
    semantic = _cosine_similarity(unit_embedding, anchor_embedding)

    # 2. taxonomy_hint 匹配
    hint_score = 0.0
    if taxonomy_hints:
        hint_scores = [
            _text_overlap_score(hint, anchor_title)
            for hint in taxonomy_hints
        ]
        hint_score = max(hint_scores) if hint_scores else 0.0

    score = (
        w["semantic"] * semantic
        + w["doc_outline"] * doc_outline_score
        + w["chunk_header"] * chunk_header_score
        + w["neighbor_vote"] * neighbor_scores
        + w["belongs_to_topic"] * belongs_to_topic_score
        + w["taxonomy_hint"] * hint_score
    )
    return max(0.0, min(1.0, score))


# ── Step B-D: 挂载 + 归属确定 ─────────────────────────────────


def _compute_belongs_to_topic_score(
    session: Session,
    unit_info: _UnitInfo,
    anchor_title: str,
) -> float:
    """通过 belongs_to_topic 边传播计算分数。

    如果单元的核心节点有 belongs_to_topic 边指向名称匹配锚点的 Topic 节点，
    则返回较高分数。
    """
    from app.models.knowledge_graph import KnowledgeEdge, KnowledgeNode

    if not unit_info.core_node_ids:
        return 0.0

    # 查找核心节点的 belongs_to_topic 边
    edges_stmt = select(KnowledgeEdge).where(
        KnowledgeEdge.source_node_id.in_(unit_info.core_node_ids),  # type: ignore[union-attr]
        KnowledgeEdge.edge_type == "belongs_to_topic",
        KnowledgeEdge.status == "active",
    )
    edges = list(session.exec(edges_stmt).all())
    if not edges:
        return 0.0

    target_ids = [e.target_node_id for e in edges]
    topics_stmt = select(KnowledgeNode).where(
        KnowledgeNode.id.in_(target_ids),  # type: ignore[union-attr]
        KnowledgeNode.status == "active",
    )
    topics = list(session.exec(topics_stmt).all())

    best = 0.0
    for topic in topics:
        overlap = _text_overlap_score(topic.canonical_name, anchor_title)
        if overlap > best:
            best = overlap
    return best


def _compute_all_scores(
    session: Session,
    unit_infos: dict[int, _UnitInfo],
    unit_embeddings: dict[int, list[float]],
    anchor_nodes: list[tuple[int, int | None, str]],  # (tree_node_id, anchor_id, title)
    anchor_embeddings: dict[int, list[float]],  # tree_node_id → embedding
    prev_memberships: dict[int, int],  # unit_id → prev tree_node_id (primary)
) -> dict[int, list[_MembershipCandidate]]:
    """为每个单元计算对所有锚点树节点的 membership_score。"""
    # 预计算邻居投票（简化：同 subject 的 unit 如果已有归属，投票给同一节点）
    result: dict[int, list[_MembershipCandidate]] = {}

    for unit_id, info in unit_infos.items():
        unit_emb = unit_embeddings.get(unit_id)
        if unit_emb is None:
            result[unit_id] = []
            continue

        candidates: list[_MembershipCandidate] = []
        for tree_node_id, anchor_id, anchor_title in anchor_nodes:
            anchor_emb = anchor_embeddings.get(tree_node_id)
            if anchor_emb is None:
                continue

            # 邻居投票：如果上一版本中有邻居 unit 挂在这个节点下，加分
            neighbor_score = 0.0
            if prev_memberships:
                neighbor_count = sum(
                    1 for uid, tnid in prev_memberships.items()
                    if tnid == tree_node_id and uid != unit_id
                )
                # 归一化到 [0, 1]
                neighbor_score = min(1.0, neighbor_count / max(len(prev_memberships), 1))

            # belongs_to_topic 传播
            btt_score = _compute_belongs_to_topic_score(session, info, anchor_title)

            score = compute_unit_membership_score(
                unit_embedding=unit_emb,
                anchor_embedding=anchor_emb,
                taxonomy_hints=info.taxonomy_hints,
                anchor_title=anchor_title,
                neighbor_scores=neighbor_score,
                belongs_to_topic_score=btt_score,
            )
            candidates.append(_MembershipCandidate(
                tree_node_id=tree_node_id,
                anchor_id=anchor_id,
                score=score,
            ))

        # 按分数降序排列
        candidates.sort(key=lambda c: c.score, reverse=True)
        result[unit_id] = candidates

    return result


def _determine_primary_membership(
    unit_id: int,
    candidates: list[_MembershipCandidate],
    prev_primary_node_id: int | None,
    human_fixed_node_id: int | None,
    uncategorized_node_id: int,
) -> tuple[int, str]:
    """确定单元的 primary membership。

    归属优先级：
    1. human_fixed → 绝对优先
    2. score 最高且 > threshold → primary
    3. 前两名差距 < stability_threshold → 保持上一版归属
    4. 所有 score < threshold → 归入待归类

    Returns:
        (tree_node_id, membership_source)
    """
    # 1. human_fixed 绝对优先
    if human_fixed_node_id is not None:
        return human_fixed_node_id, "human_fixed"

    if not candidates:
        return uncategorized_node_id, "auto"

    top = candidates[0]

    # 4. 所有 score < threshold → 待归类
    if top.score < MEMBERSHIP_THRESHOLD:
        return uncategorized_node_id, "auto"

    # 3. 稳定规则：前两名差距 < stability_threshold → 保持上一版
    if len(candidates) >= 2:
        second = candidates[1]
        gap = top.score - second.score
        if gap < STABILITY_THRESHOLD and prev_primary_node_id is not None:
            # 检查上一版归属是否在候选中
            for c in candidates:
                if c.tree_node_id == prev_primary_node_id:
                    return prev_primary_node_id, "auto"

    # 2. score 最高 → primary
    return top.tree_node_id, "auto"


# ── Step E: 生成 ThemeTreeVersion ─────────────────────────────


def _materialize_skeleton(
    session: Session,
    tree_version_id: int,
    skeletons: list[_AnchorSkeleton],
    parent_tree_node_id: int | None,
    curriculum_job_id: int,
) -> list[tuple[int, int | None, str]]:
    """将锚点骨架物化为 ThemeTreeNode 记录。

    Returns:
        list of (tree_node_id, anchor_id, anchor_title) — 叶级可挂载节点。
    """
    mountable: list[tuple[int, int | None, str]] = []

    for idx, skel in enumerate(skeletons):
        anchor = skel.anchor
        # 确定节点类型
        if anchor.is_system and anchor.anchor_type == "system":
            node_type = "uncategorized"
        elif not skel.children:
            node_type = "theme"
        elif anchor.parent_anchor_id is None:
            node_type = "chapter"
        else:
            node_type = "section"

        tree_node = curriculum_repo.create_theme_tree_node(
            session,
            ThemeTreeNode(
                tree_version_id=tree_version_id,
                anchor_id=anchor.id,
                parent_tree_node_id=parent_tree_node_id,
                title=anchor.title,
                node_type=node_type,
                order_index=idx,
                summary="",
                created_by_job_id=curriculum_job_id,
            ),
        )

        if skel.children:
            # 递归创建子节点
            child_mountable = _materialize_skeleton(
                session, tree_version_id, skel.children,
                tree_node.id, curriculum_job_id,
            )
            mountable.extend(child_mountable)
        else:
            # 叶节点可挂载
            mountable.append((
                tree_node.id,  # type: ignore[arg-type]
                anchor.id,
                anchor.title,
            ))

    return mountable


def _get_prev_primary_memberships(
    session: Session,
    prev_tree_version: ThemeTreeVersion | None,
) -> dict[int, int]:
    """获取上一版本树中每个 unit 的 primary membership tree_node_id。"""
    if prev_tree_version is None:
        return {}

    stmt = select(UnitTreeMembership).where(
        UnitTreeMembership.tree_version_id == prev_tree_version.id,
        UnitTreeMembership.membership_role == "primary",
    )
    memberships = list(session.exec(stmt).all())
    return {m.teaching_unit_id: m.tree_node_id for m in memberships}


def _get_human_fixed_memberships(
    session: Session,
    prev_tree_version: ThemeTreeVersion | None,
) -> dict[int, int]:
    """获取上一版本树中 human_fixed 的归属映射 unit_id → tree_node_id。

    注意：返回的 tree_node_id 是旧版本的，需要通过 anchor_id 映射到新版本。
    这里返回 unit_id → anchor_id 更合适。
    """
    if prev_tree_version is None:
        return {}

    stmt = select(UnitTreeMembership).where(
        UnitTreeMembership.tree_version_id == prev_tree_version.id,
        UnitTreeMembership.membership_source == "human_fixed",
        UnitTreeMembership.membership_role == "primary",
    )
    memberships = list(session.exec(stmt).all())

    # 需要从旧 tree_node 找到 anchor_id
    result: dict[int, int] = {}
    for m in memberships:
        old_node = session.get(ThemeTreeNode, m.tree_node_id)
        if old_node and old_node.anchor_id is not None:
            result[m.teaching_unit_id] = old_node.anchor_id
    return result


# ── 主入口 ────────────────────────────────────────────────────


async def derive_theme_tree(
    session: Session,
    subject: str,
    impact_set: ImpactSet,
    curriculum_job_id: int,
    prev_tree_version: ThemeTreeVersion | None = None,
) -> ThemeTreeVersion:
    """主题树派生主入口：Anchor Skeleton → 挂载 → 评分 → 归属 → draft 版本。

    MVP 采用"逻辑局部重算 + 存储全量快照"版本策略：
    仅对 Impact Set 影响范围内对象重新计算，但落库时生成完整新版本。

    Args:
        session: 数据库会话。
        subject: 学科标识。
        impact_set: 影响集。
        curriculum_job_id: 课程派生任务 ID。
        prev_tree_version: 上一版本的主题树（用于稳定规则），可为 None。

    Returns:
        新创建的 ThemeTreeVersion（status="draft"）。
    """
    # ── Step A: 生成 Anchor Skeleton ──
    skeletons = _build_anchor_skeleton(session, subject)
    logger.info("anchor_skeleton_built", subject=subject, anchor_count=len(skeletons))

    # 检查是否只有 uncategorized 系统锚点（无真实层级结构）
    has_real_anchors = any(
        skel.anchor.anchor_type != "system" for skel in skeletons
    )

    if not has_real_anchors:
        # 加载教学单元用于 LLM 生成
        all_units_for_gen, _ = curriculum_repo.list_units_by_subject(
            session, subject, status="active", limit=10000, offset=0,
        )
        pending_for_gen, _ = curriculum_repo.list_units_by_subject(
            session, subject, status="pending", limit=10000, offset=0,
        )
        units_for_gen = all_units_for_gen + [
            u for u in pending_for_gen if u.created_by_job_id == curriculum_job_id
        ]

        if units_for_gen:
            logger.info(
                "auto_generating_anchors",
                subject=subject,
                unit_count=len(units_for_gen),
            )
            await _auto_generate_anchors(session, subject, units_for_gen)
            # 重新构建骨架（现在包含 LLM 生成的锚点）
            skeletons = _build_anchor_skeleton(session, subject)
            logger.info(
                "anchor_skeleton_rebuilt",
                subject=subject,
                anchor_count=len(skeletons),
            )

    # 确定上一版本号（用于乐观锁）
    if prev_tree_version is None:
        prev_tree_version = curriculum_repo.get_current_theme_tree_version(session, subject)

    prev_version_no = prev_tree_version.version_no if prev_tree_version else 0

    # 使用乐观锁创建新版本
    tree_version = curriculum_repo.create_theme_tree_version_with_optimistic_lock(
        session, subject, expected_prev_version_no=prev_version_no,
    )
    tree_version.curriculum_job_id = curriculum_job_id
    tree_version.created_by_job_id = curriculum_job_id
    session.add(tree_version)
    session.commit()
    session.refresh(tree_version)

    # 物化骨架为 ThemeTreeNode
    mountable_nodes = _materialize_skeleton(
        session, tree_version.id, skeletons,  # type: ignore[arg-type]
        parent_tree_node_id=None,
        curriculum_job_id=curriculum_job_id,
    )

    # 确保 UNCATEGORIZED 节点存在
    uncategorized_node_id = _ensure_uncategorized_node(
        session, tree_version, mountable_nodes, curriculum_job_id,
    )

    logger.info(
        "tree_nodes_materialized",
        tree_version_id=tree_version.id,
        mountable_count=len(mountable_nodes),
    )

    # ── Step B-D: 加载单元 + 评分 + 归属 ──
    # 加载所有 active 教学单元
    all_units, _ = curriculum_repo.list_units_by_subject(
        session, subject, status="active", limit=10000, offset=0,
    )
    # 也包含本次新建的 pending 单元（由 unit_builder 创建）
    pending_units, _ = curriculum_repo.list_units_by_subject(
        session, subject, status="pending", limit=10000, offset=0,
    )
    all_units = all_units + [u for u in pending_units if u.created_by_job_id == curriculum_job_id]

    if not all_units:
        logger.info("no_units_for_tree_derivation", subject=subject)
        return tree_version

    unit_infos = _load_unit_infos(session, all_units)

    # 生成 embeddings
    unit_embed_texts = [
        f"{info.canonical_name}：{info.summary}"
        for info in unit_infos.values()
    ]
    unit_embed_ids = list(unit_infos.keys())

    # 锚点节点 embedding
    anchor_embed_texts = [title for _, _, title in mountable_nodes]

    all_texts = unit_embed_texts + anchor_embed_texts
    if all_texts:
        all_embeddings = await aembed_texts(all_texts)
        unit_embeddings: dict[int, list[float]] = dict(
            zip(unit_embed_ids, all_embeddings[:len(unit_embed_ids)])
        )
        anchor_embeddings: dict[int, list[float]] = {}
        for i, (tn_id, _, _) in enumerate(mountable_nodes):
            anchor_embeddings[tn_id] = all_embeddings[len(unit_embed_ids) + i]
    else:
        unit_embeddings = {}
        anchor_embeddings = {}

    # 获取上一版本的 primary memberships（用于稳定规则）
    prev_memberships = _get_prev_primary_memberships(session, prev_tree_version)

    # 获取 human_fixed 归属（anchor_id 映射）
    human_fixed_by_anchor = _get_human_fixed_memberships(session, prev_tree_version)
    # 构建 anchor_id → new tree_node_id 映射
    anchor_to_new_node: dict[int, int] = {}
    for tn_id, a_id, _ in mountable_nodes:
        if a_id is not None:
            anchor_to_new_node[a_id] = tn_id

    # 计算所有分数
    all_scores = _compute_all_scores(
        session, unit_infos, unit_embeddings,
        mountable_nodes, anchor_embeddings, prev_memberships,
    )

    # ── 确定归属并创建 UnitTreeMembership ──
    for unit_id in unit_infos:
        candidates = all_scores.get(unit_id, [])

        # 检查 human_fixed
        human_fixed_node_id: int | None = None
        if unit_id in human_fixed_by_anchor:
            fixed_anchor_id = human_fixed_by_anchor[unit_id]
            human_fixed_node_id = anchor_to_new_node.get(fixed_anchor_id)

        # 上一版本的 primary node（需映射到新版本）
        prev_primary: int | None = None
        if unit_id in prev_memberships:
            old_tn_id = prev_memberships[unit_id]
            old_node = session.get(ThemeTreeNode, old_tn_id)
            if old_node and old_node.anchor_id is not None:
                prev_primary = anchor_to_new_node.get(old_node.anchor_id)

        target_node_id, source = _determine_primary_membership(
            unit_id, candidates, prev_primary,
            human_fixed_node_id, uncategorized_node_id,
        )

        # 找到对应的 score
        score = 0.0
        for c in candidates:
            if c.tree_node_id == target_node_id:
                score = c.score
                break

        curriculum_repo.create_unit_tree_membership(
            session,
            UnitTreeMembership(
                tree_version_id=tree_version.id,  # type: ignore[arg-type]
                tree_node_id=target_node_id,
                teaching_unit_id=unit_id,
                membership_role="primary",
                membership_source=source,
                score=score,
                created_by_job_id=curriculum_job_id,
            ),
        )

    logger.info(
        "derive_theme_tree_complete",
        subject=subject,
        tree_version_id=tree_version.id,
        version_no=tree_version.version_no,
        units_mounted=len(unit_infos),
    )
    return tree_version


def _ensure_uncategorized_node(
    session: Session,
    tree_version: ThemeTreeVersion,
    mountable_nodes: list[tuple[int, int | None, str]],
    curriculum_job_id: int,
) -> int:
    """确保 UNCATEGORIZED 固定节点存在，返回其 tree_node_id。"""
    # 检查是否已在骨架中创建
    for tn_id, _, title in mountable_nodes:
        node = session.get(ThemeTreeNode, tn_id)
        if node and node.node_type == "uncategorized":
            return tn_id  # type: ignore[return-value]

    # 未找到，手动创建
    uncat_node = curriculum_repo.create_theme_tree_node(
        session,
        ThemeTreeNode(
            tree_version_id=tree_version.id,  # type: ignore[arg-type]
            anchor_id=None,
            parent_tree_node_id=None,
            title="待归类",
            node_type="uncategorized",
            order_index=9999,
            summary="",
            created_by_job_id=curriculum_job_id,
        ),
    )
    # 追加到 mountable_nodes
    mountable_nodes.append((uncat_node.id, None, "待归类"))  # type: ignore[arg-type]
    return uncat_node.id  # type: ignore[return-value]
