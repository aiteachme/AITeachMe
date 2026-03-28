"""蓝图规划服务。

Phase 3 的核心服务：
1. plan_document_blueprint — LLM 规划章节结构 + 学习目标
2. build_evidence_bundles — 给每章分配结构化证据
3. select_try_it_exercise — 为每章选 "尝试一下" 练习

使用方式：
    from app.workflows.digest.services.blueprint_planner import (
        plan_document_blueprint,
        build_evidence_bundles,
    )
"""

from __future__ import annotations

import json

import structlog

from app.workflows.digest.shared.blueprint import (
    ChapterArchetype,
    ChapterBlueprint,
    DocumentBlueprint,
    EvidenceBundle,
    EvidenceItem,
)
from app.workflows.digest.shared.primitives import (
    ContentPrimitive,
    DigestMode,
    DigestModeDecision,
    MaterialProfile,
    PedagogicalBlock,
    PrimitiveType,
    TopicCluster,
)

logger = structlog.get_logger()


# ── 章节原型自动分配 ────────────────────────────────────────────


def infer_archetype(cluster: TopicCluster) -> ChapterArchetype:
    """根据 TopicCluster 的内容特征推断章节原型。"""
    all_types: dict[str, int] = {}
    for block in cluster.blocks:
        for prim in block.primitives:
            t = prim.type.value
            all_types[t] = all_types.get(t, 0) + 1

    total = max(sum(all_types.values()), 1)

    # 习题/例题占比 > 50% → 题型突破
    practice_count = all_types.get("exercise", 0) + all_types.get("example", 0)
    if practice_count / total > 0.5:
        return ChapterArchetype.PROBLEM_TYPE

    # 方法占比 > 30% → 方法求解
    method_count = all_types.get("method", 0)
    if method_count / total > 0.3:
        return ChapterArchetype.METHOD_SOLVE

    # 定义+定理+公式占比 > 40% → 概念建立
    concept_count = (
        all_types.get("definition", 0)
        + all_types.get("theorem", 0)
        + all_types.get("formula", 0)
    )
    if concept_count / total > 0.4:
        return ChapterArchetype.CONCEPT_BUILD

    # 默认概念建立
    return ChapterArchetype.CONCEPT_BUILD


def _importance_label(cluster: TopicCluster) -> str:
    """将 TopicImportance 转为显示标签。"""
    return {
        "core": "★★★ 核心",
        "important": "★★ 重要",
        "supplementary": "★ 拓展",
    }.get(cluster.importance.value, "★★ 重要")


# ── 蓝图规划 ────────────────────────────────────────────────────


def plan_document_blueprint_from_clusters(
    clusters: list[TopicCluster],
    profile: MaterialProfile,
    mode_decision: DigestModeDecision,
    is_stem: bool = True,
) -> DocumentBlueprint:
    """从 TopicCluster 生成 DocumentBlueprint（规则版）。

    这是一个不依赖 LLM 的快速版本，用于：
    1. LLM 不可用时的 fallback
    2. 小规模材料的快速生成
    3. 大规模 LLM 蓝图的初始种子

    LLM 版本应在此基础上做 refinement。
    """
    if not clusters:
        return DocumentBlueprint(
            mode=mode_decision.mode.value,
            subject=profile.subject,
        )

    chapters: list[ChapterBlueprint] = []
    is_sprint = mode_decision.mode == DigestMode.SPRINT

    for i, cluster in enumerate(clusters):
        archetype = infer_archetype(cluster)

        # sprint 模式：concept_build 可压缩为简介
        if is_sprint and archetype == ChapterArchetype.CONCEPT_BUILD:
            # 仍保留，但标记为可压缩
            pass

        # 建议组件
        if is_stem:
            components = archetype.suggested_components_stem
        else:
            components = archetype.suggested_components_humanities

        chapter = ChapterBlueprint(
            index=i + 1,
            title=cluster.canonical_name or f"第{i + 1}章",
            archetype=archetype,
            learning_objectives=[],  # LLM 版本会填充
            target_clusters=[cluster.canonical_name],
            importance_label=_importance_label(cluster),
            suggested_components=components,
            evidence_budget_tokens=2500 if is_sprint else 4000,
        )
        chapters.append(chapter)

    # Sprint 模式：末尾补一章综合复习
    if is_sprint and len(chapters) >= 2:
        chapters.append(ChapterBlueprint(
            index=len(chapters) + 1,
            title="综合复习与速查",
            archetype=ChapterArchetype.REVIEW_SPRINT,
            learning_objectives=["快速回顾全部核心知识点", "掌握关键公式速查表"],
            target_clusters=[c.canonical_name for c in clusters[:5]],
            importance_label="★★★ 核心",
            suggested_components=ChapterArchetype.REVIEW_SPRINT.suggested_components_stem
            if is_stem
            else ChapterArchetype.REVIEW_SPRINT.suggested_components_humanities,
            evidence_budget_tokens=3000,
        ))

    blueprint = DocumentBlueprint(
        mode=mode_decision.mode.value,
        subject=profile.subject,
        main_theme=profile.subject or "知识讲义",
        chapters=chapters,
        total_estimated_tokens=sum(c.evidence_budget_tokens for c in chapters),
        quality_target="速查手册" if is_sprint else "系统讲义",
    )

    logger.info(
        "document_blueprint_planned",
        mode=blueprint.mode,
        chapter_count=len(chapters),
        archetypes={a.value: sum(1 for c in chapters if c.archetype == a)
                    for a in ChapterArchetype},
    )
    return blueprint


# ── 证据打包 ────────────────────────────────────────────────────


def _primitive_to_evidence(prim: ContentPrimitive) -> EvidenceItem:
    """将 ContentPrimitive 转为 EvidenceItem。"""
    return EvidenceItem(
        content=prim.content[:500],  # 截断过长内容
        source_file=prim.source_filename,
        source_page=prim.source_page,
        source_section="",
        section_uid=prim.section_uid,
        confidence=prim.confidence,
    )


def build_evidence_bundles(
    blueprint: DocumentBlueprint,
    clusters: list[TopicCluster],
    all_primitives: list[ContentPrimitive],
) -> list[EvidenceBundle]:
    """为每章分配结构化证据包。

    根据 blueprint 的 target_clusters 找到对应的 primitive，
    按类型分桶装入 EvidenceBundle。
    """
    # cluster name → primitive 映射
    cluster_map: dict[str, list[ContentPrimitive]] = {}
    for cluster in clusters:
        prims: list[ContentPrimitive] = []
        for block in cluster.blocks:
            prims.extend(block.primitives)
        cluster_map[cluster.canonical_name] = prims

    bundles: list[EvidenceBundle] = []

    for chapter in blueprint.chapters:
        bundle = EvidenceBundle(chapter_index=chapter.index)

        # 收集本章相关的所有 primitive
        chapter_prims: list[ContentPrimitive] = []
        for cluster_name in chapter.target_clusters:
            chapter_prims.extend(cluster_map.get(cluster_name, []))

        # 按类型分桶
        for prim in chapter_prims:
            evidence = _primitive_to_evidence(prim)
            if prim.type == PrimitiveType.DEFINITION:
                bundle.definitions.append(evidence)
            elif prim.type == PrimitiveType.FORMULA:
                bundle.formulas.append(evidence)
            elif prim.type == PrimitiveType.METHOD:
                bundle.methods.append(evidence)
            elif prim.type == PrimitiveType.EXAMPLE:
                bundle.examples.append(evidence)
            elif prim.type == PrimitiveType.EXERCISE:
                bundle.exercises.append(evidence)
            elif prim.type == PrimitiveType.WARNING:
                bundle.warnings.append(evidence)

        bundles.append(bundle)

    logger.info(
        "evidence_bundles_built",
        total_bundles=len(bundles),
        total_items=sum(b.total_items for b in bundles),
    )
    return bundles


# ── LLM 蓝图规划 Prompt ────────────────────────────────────────

BLUEPRINT_PROMPT = """\
你是一位有 10 年教学经验的教研老师。请根据以下材料分析结果，规划一本讲义的章节结构。

## 设计原则（逆向设计法）
先想"学生学完每章应该能做到什么"，再决定每章需要什么内容。
每个学习目标必须具体、可衡量、可验证。

## 材料画像
- 学科：{subject}
- 总文件数：{total_sources}
- 总章节数：{total_sections}
- 公式密度：{formula_density}
- 习题密度：{exercise_density}

## 模式
{mode}

## 主题列表（已按内容分组）
{topic_list}

## 每个主题的内容类型分布
{topic_stats}

## 输出要求
返回严格 JSON：
{{
  "main_theme": "全书主线（一句话）",
  "chapters": [
    {{
      "index": 1,
      "title": "章节标题",
      "archetype": "concept_build",
      "learning_objectives": [
        "能准确写出XX的定义",
        "能用XX方法求解XX类型问题"
      ],
      "importance": "★★★",
      "prerequisite_chapters": [],
      "suggested_components": ["definition", "formula", "example", "try_it"],
      "target_topics": ["主题名1", "主题名2"]
    }}
  ]
}}

章节原型说明：
- concept_build: 概念建立（新概念引入，定义+公式+基础例题）
- method_solve: 方法求解（解题方法，步骤+判断点+变式）
- problem_type: 题型突破（题型识别+解题框架+例题）
- review_sprint: 综合复习（公式速查+记忆抓手+易错点）

模式要求：
- sprint（速成课）：章节更短，侧重题型和易错点，每章 3~5 个学习目标
- systematic（系统课）：章节更完整，侧重依赖链和推导，每章 5~8 个学习目标
"""


__all__ = [
    "BLUEPRINT_PROMPT",
    "build_evidence_bundles",
    "infer_archetype",
    "plan_document_blueprint_from_clusters",
]
