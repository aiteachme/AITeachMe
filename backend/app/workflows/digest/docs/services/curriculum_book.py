"""Build curriculum-aligned knowledge docs from the published theme tree."""

from __future__ import annotations

import json
import re
from collections import defaultdict

from pydantic import BaseModel, Field
from sqlmodel import select

from app.core.database import managed_session
from app.models.curriculum import (
    TeachingUnit,
    TeachingUnitMembership,
    TeachingUnitRevision,
    ThemeTreeNode,
    UnitTreeMembership,
)
from app.models.knowledge_graph import EvidenceLink, KnowledgeNode, KnowledgeRevision
from app.repositories import curriculum_repo
from app.workflows.digest.shared.models import SectionPacket, SharedInputs
from app.workflows.digest.unified.models import MaterializedSections

_SPACE_PATTERN = re.compile(r"\s+")
_QUESTION_PREFIX_PATTERN = re.compile(
    r"^(?:question\s*\d+\s*[:：]\s*|第\s*\d+\s*题\s*[:：]?\s*)",
    re.IGNORECASE,
)
_PROCEDURAL_HINTS = (
    "考试",
    "试卷",
    "答题",
    "注意",
    "须知",
    "说明",
    "时间",
    "满分",
    "准考证",
    "答题纸",
    "条形码",
    "作答",
    "规范",
)
_GENERIC_POINT_HINTS = (
    "page ocr",
    "fallback",
    "question-bank chunk extracted",
)
_POINT_TYPE_PRIORITY = {
    "Topic": 0,
    "Concept": 1,
    "Definition": 2,
    "Method": 3,
    "Example": 4,
}


class KnowledgePoint(BaseModel):
    """One graph-backed knowledge point inside a teaching unit."""

    name: str
    summary: str = ""
    role: str = "support"
    node_type: str = "Concept"


class TeachingUnitBundle(BaseModel):
    """Curriculum-aligned teaching-unit context for docs synthesis."""

    unit_id: int
    title: str
    summary: str = ""
    learning_objectives: list[str] = Field(default_factory=list)
    curriculum_path: list[str] = Field(default_factory=list)
    source_file_ids: list[int] = Field(default_factory=list)
    chunk_uids: list[str] = Field(default_factory=list)
    knowledge_points: list[KnowledgePoint] = Field(default_factory=list)
    example_points: list[KnowledgePoint] = Field(default_factory=list)
    evidence_packets: list[SectionPacket] = Field(default_factory=list)
    example_packets: list[SectionPacket] = Field(default_factory=list)
    is_procedural: bool = False


class CurriculumChapterBundle(BaseModel):
    """One final docs chapter synthesized from a theme-tree branch."""

    chapter_index: int
    title: str
    summary: str = ""
    curriculum_path: list[str] = Field(default_factory=list)
    section_titles: list[str] = Field(default_factory=list)
    source_file_ids: list[int] = Field(default_factory=list)
    chunk_uids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    markdown: str = ""


def build_curriculum_aligned_book(
    *,
    subject: str,
    theme_tree_version_id: int,
    shared_inputs: SharedInputs,
    materialized: MaterializedSections,
) -> tuple[list[dict], list[dict]]:
    """Build final docs chapters from the published curriculum tree."""

    del subject

    packets_by_uid = {
        packet.digest_chunk_uid: packet
        for packet in shared_inputs.section_packets
    }
    chunk_id_to_chunk_uid = dict(materialized.chunk_id_to_chunk_uid)

    with managed_session() as session:
        tree_nodes = curriculum_repo.list_tree_nodes_by_version(session, theme_tree_version_id)
        memberships = [
            membership
            for membership in curriculum_repo.list_unit_memberships_by_version(
                session,
                theme_tree_version_id,
            )
            if membership.membership_role == "primary"
        ]
        if not tree_nodes or not memberships:
            return [], []

        unit_ids = list(dict.fromkeys(membership.teaching_unit_id for membership in memberships))
        units = list(
            session.exec(select(TeachingUnit).where(TeachingUnit.id.in_(unit_ids))).all()
        )
        unit_by_id = {
            unit.id: unit
            for unit in units
            if unit.id is not None
        }

        revisions = list(
            session.exec(
                select(TeachingUnitRevision).where(
                    TeachingUnitRevision.unit_id.in_(unit_ids),
                    TeachingUnitRevision.is_current.is_(True),
                )
            ).all()
        )
        revision_by_unit_id = {
            revision.unit_id: revision
            for revision in revisions
        }

        unit_memberships = list(
            session.exec(
                select(TeachingUnitMembership).where(
                    TeachingUnitMembership.unit_id.in_(unit_ids)
                )
            ).all()
        )
        memberships_by_unit_id: dict[int, list[TeachingUnitMembership]] = defaultdict(list)
        for membership in unit_memberships:
            memberships_by_unit_id[membership.unit_id].append(membership)

        knowledge_node_ids = list(
            {
                membership.knowledge_node_id
                for membership in unit_memberships
            }
        )
        knowledge_nodes = list(
            session.exec(
                select(KnowledgeNode).where(
                    KnowledgeNode.id.in_(knowledge_node_ids)
                )
            ).all()
        ) if knowledge_node_ids else []
        node_by_id = {
            node.id: node
            for node in knowledge_nodes
            if node.id is not None
        }

        knowledge_revisions = list(
            session.exec(
                select(KnowledgeRevision).where(
                    KnowledgeRevision.node_id.in_(knowledge_node_ids),
                    KnowledgeRevision.is_current.is_(True),
                )
            ).all()
        ) if knowledge_node_ids else []
        revision_by_node_id = {
            revision.node_id: revision
            for revision in knowledge_revisions
        }

        evidence_links = list(
            session.exec(
                select(EvidenceLink).where(
                    EvidenceLink.entity_type == "node",
                    EvidenceLink.entity_id.in_(knowledge_node_ids),
                    EvidenceLink.is_active.is_(True),
                    EvidenceLink.chunk_id.in_(list(chunk_id_to_chunk_uid.keys())),
                )
            ).all()
        ) if knowledge_node_ids and chunk_id_to_chunk_uid else []

    chunk_uids_by_node_id: dict[int, list[str]] = defaultdict(list)
    for evidence in evidence_links:
        chunk_uid = chunk_id_to_chunk_uid.get(evidence.chunk_id)
        if chunk_uid:
            chunk_uids_by_node_id[evidence.entity_id].append(chunk_uid)

    children_by_parent_id: dict[int | None, list[ThemeTreeNode]] = defaultdict(list)
    for node in tree_nodes:
        children_by_parent_id[node.parent_tree_node_id].append(node)
    for siblings in children_by_parent_id.values():
        siblings.sort(key=lambda item: (item.order_index, item.title))

    primary_memberships_by_tree_node_id: dict[int, list[UnitTreeMembership]] = defaultdict(list)
    for membership in memberships:
        primary_memberships_by_tree_node_id[membership.tree_node_id].append(membership)
    for node_memberships in primary_memberships_by_tree_node_id.values():
        node_memberships.sort(key=lambda item: (-item.score, item.teaching_unit_id))

    unit_bundles_by_id = {
        unit_id: _build_teaching_unit_bundle(
            unit=unit_by_id[unit_id],
            unit_revision=revision_by_unit_id.get(unit_id),
            memberships=memberships_by_unit_id.get(unit_id, []),
            node_by_id=node_by_id,
            revision_by_node_id=revision_by_node_id,
            chunk_uids_by_node_id=chunk_uids_by_node_id,
            packets_by_uid=packets_by_uid,
        )
        for unit_id in unit_by_id
    }

    root_nodes = [
        node
        for node in children_by_parent_id.get(None, [])
        if node.node_type != "uncategorized"
    ]
    bundled_units_by_root_id: dict[int, list[TeachingUnitBundle]] = {}
    assigned_unit_ids: set[int] = set()
    for root in root_nodes:
        unit_bundles = _collect_unit_bundles_for_tree_node(
            node=root,
            path=[root.title],
            children_by_parent_id=children_by_parent_id,
            primary_memberships_by_tree_node_id=primary_memberships_by_tree_node_id,
            unit_bundles_by_id=unit_bundles_by_id,
        )
        bundled_units_by_root_id[root.id or 0] = unit_bundles
        assigned_unit_ids.update(bundle.unit_id for bundle in unit_bundles)

    orphan_units = [
        bundle
        for bundle in unit_bundles_by_id.values()
        if bundle.unit_id not in assigned_unit_ids
    ]
    soft_assigned_by_root_id = _soft_assign_orphan_units(
        orphan_units=orphan_units,
        root_nodes=root_nodes,
        children_by_parent_id=children_by_parent_id,
    )
    for root in root_nodes:
        root_id = root.id or 0
        bundled_units_by_root_id[root_id] = _merge_unit_bundles(
            bundled_units_by_root_id.get(root_id, []),
            soft_assigned_by_root_id.get(root_id, []),
        )

    chapters: list[CurriculumChapterBundle] = []
    for root in root_nodes:
        unit_bundles = bundled_units_by_root_id.get(root.id or 0, [])
        if not unit_bundles:
            continue
        chapters.append(
            _build_curriculum_chapter_bundle(
                chapter_index=len(chapters) + 1,
                tree_node=root,
                unit_bundles=unit_bundles,
            )
        )

    if not chapters:
        for root in children_by_parent_id.get(None, []):
            unit_bundles = _collect_unit_bundles_for_tree_node(
                node=root,
                path=[root.title],
                children_by_parent_id=children_by_parent_id,
                primary_memberships_by_tree_node_id=primary_memberships_by_tree_node_id,
                unit_bundles_by_id=unit_bundles_by_id,
            )
            if not unit_bundles:
                continue
            chapters.append(
                _build_curriculum_chapter_bundle(
                    chapter_index=len(chapters) + 1,
                    tree_node=root,
                    unit_bundles=unit_bundles,
                )
            )

    chapter_metadatas = [chapter.model_dump() for chapter in chapters]
    chapter_assignments = [
        {
            "chapter_index": chapter.chapter_index,
            "title": chapter.title,
            "section_titles": list(chapter.section_titles),
            "source_file_ids": list(chapter.source_file_ids),
            "chunk_uids": list(chapter.chunk_uids),
        }
        for chapter in chapters
    ]
    return chapter_metadatas, chapter_assignments


def _build_teaching_unit_bundle(
    *,
    unit: TeachingUnit,
    unit_revision: TeachingUnitRevision | None,
    memberships: list[TeachingUnitMembership],
    node_by_id: dict[int, KnowledgeNode],
    revision_by_node_id: dict[int, KnowledgeRevision],
    chunk_uids_by_node_id: dict[int, list[str]],
    packets_by_uid: dict[str, SectionPacket],
) -> TeachingUnitBundle:
    bundle_title = (
        (unit_revision.title if unit_revision else unit.canonical_name).strip()
        or unit.canonical_name
    )
    bundle_summary = _clean_sentence(unit_revision.summary if unit_revision else "", max_chars=180)
    is_procedural = _is_procedural_text(" ".join([bundle_title, bundle_summary]))

    knowledge_points: list[KnowledgePoint] = []
    example_points: list[KnowledgePoint] = []
    chunk_uids: list[str] = []

    sorted_memberships = sorted(
        memberships,
        key=lambda item: (
            _membership_role_priority(item.role),
            -item.score,
            item.knowledge_node_id,
        ),
    )
    for membership in sorted_memberships:
        node = node_by_id.get(membership.knowledge_node_id)
        if node is None or node.id is None:
            continue
        node_revision = revision_by_node_id.get(node.id)
        point = KnowledgePoint(
            name=node.canonical_name,
            summary=_clean_sentence(node_revision.summary if node_revision else "", max_chars=120),
            role=membership.role,
            node_type=node.node_type,
        )
        if _should_skip_knowledge_point(point):
            continue
        if _is_example_point(point):
            example_points.append(point)
        else:
            knowledge_points.append(point)
        chunk_uids.extend(chunk_uids_by_node_id.get(node.id, []))

    deduped_chunk_uids = [
        chunk_uid
        for chunk_uid in dict.fromkeys(chunk_uids)
        if chunk_uid in packets_by_uid
    ]
    packets = [packets_by_uid[chunk_uid] for chunk_uid in deduped_chunk_uids]
    example_packets = [packet for packet in packets if _looks_like_example_packet(packet)]
    evidence_packets = [packet for packet in packets if not _looks_like_example_packet(packet)]
    if not evidence_packets:
        evidence_packets = packets

    return TeachingUnitBundle(
        unit_id=unit.id or 0,
        title=bundle_title,
        summary=bundle_summary,
        learning_objectives=_parse_learning_objectives(unit_revision),
        source_file_ids=list(dict.fromkeys(packet.source_file_id for packet in packets)),
        chunk_uids=deduped_chunk_uids,
        knowledge_points=_dedupe_points(knowledge_points)[:6],
        example_points=_dedupe_points(example_points)[:4],
        evidence_packets=evidence_packets[:4],
        example_packets=example_packets[:3],
        is_procedural=is_procedural,
    )


def _collect_unit_bundles_for_tree_node(
    *,
    node: ThemeTreeNode,
    path: list[str],
    children_by_parent_id: dict[int | None, list[ThemeTreeNode]],
    primary_memberships_by_tree_node_id: dict[int, list[UnitTreeMembership]],
    unit_bundles_by_id: dict[int, TeachingUnitBundle],
) -> list[TeachingUnitBundle]:
    collected: list[TeachingUnitBundle] = []
    seen_unit_ids: set[int] = set()

    def _walk(current_node: ThemeTreeNode, current_path: list[str]) -> None:
        direct_memberships = primary_memberships_by_tree_node_id.get(current_node.id or 0, [])
        for membership in direct_memberships:
            base_bundle = unit_bundles_by_id.get(membership.teaching_unit_id)
            if base_bundle is None or base_bundle.unit_id in seen_unit_ids:
                continue
            seen_unit_ids.add(base_bundle.unit_id)
            collected.append(
                base_bundle.model_copy(update={"curriculum_path": list(current_path)})
            )
        for child in children_by_parent_id.get(current_node.id, []):
            _walk(child, [*current_path, child.title])

    _walk(node, path)
    return collected


def _build_curriculum_chapter_bundle(
    *,
    chapter_index: int,
    tree_node: ThemeTreeNode,
    unit_bundles: list[TeachingUnitBundle],
) -> CurriculumChapterBundle:
    sorted_unit_bundles = sorted(
        unit_bundles,
        key=lambda item: (item.curriculum_path, item.title),
    )
    chapter_title = tree_node.title.strip() or f"第{chapter_index}章"
    chapter_summary = _build_chapter_summary(tree_node, sorted_unit_bundles)
    section_titles = [bundle.title for bundle in sorted_unit_bundles]
    source_file_ids = list(
        dict.fromkeys(
            file_id
            for bundle in sorted_unit_bundles
            for file_id in bundle.source_file_ids
        )
    )
    chunk_uids = list(
        dict.fromkeys(
            chunk_uid
            for bundle in sorted_unit_bundles
            for chunk_uid in bundle.chunk_uids
        )
    )
    tags = list(
        dict.fromkeys(
            [
                chapter_title,
                *section_titles,
                *[
                    point.name
                    for bundle in sorted_unit_bundles
                    for point in bundle.knowledge_points[:2]
                ],
            ]
        )
    )[:12]

    lines = [
        f"# {chapter_title}",
        "",
        "## 本章导读",
        "",
        chapter_summary,
        "",
        "## 本章学习路线",
        "",
        *[f"- {line}" for line in _build_chapter_route(sorted_unit_bundles)],
        "",
        "## 本章知识地图",
        "",
    ]
    for bundle in sorted_unit_bundles:
        map_line = f"- {bundle.title}"
        if bundle.summary:
            map_line += f"：{bundle.summary}"
        lines.append(map_line)
    lines.extend(["", "## 分主题讲解", ""])
    for bundle in sorted_unit_bundles:
        lines.extend(_render_unit_section(bundle))

    markdown = "\n".join(lines).strip() + "\n"
    return CurriculumChapterBundle(
        chapter_index=chapter_index,
        title=chapter_title,
        summary=chapter_summary,
        section_titles=section_titles,
        source_file_ids=source_file_ids,
        chunk_uids=chunk_uids,
        tags=tags,
        markdown=markdown,
    )


def _merge_unit_bundles(
    direct_bundles: list[TeachingUnitBundle],
    soft_bundles: list[TeachingUnitBundle],
) -> list[TeachingUnitBundle]:
    merged: list[TeachingUnitBundle] = []
    seen_unit_ids: set[int] = set()
    for bundle in [*direct_bundles, *soft_bundles]:
        if bundle.unit_id in seen_unit_ids:
            continue
        seen_unit_ids.add(bundle.unit_id)
        merged.append(bundle)
    return merged


def _soft_assign_orphan_units(
    *,
    orphan_units: list[TeachingUnitBundle],
    root_nodes: list[ThemeTreeNode],
    children_by_parent_id: dict[int | None, list[ThemeTreeNode]],
) -> dict[int, list[TeachingUnitBundle]]:
    assignments: dict[int, list[TeachingUnitBundle]] = defaultdict(list)
    if not orphan_units or not root_nodes:
        return assignments

    root_search_spaces = {
        root.id or 0: _collect_tree_node_paths(root, children_by_parent_id)
        for root in root_nodes
    }
    for bundle in orphan_units:
        best_root_id: int | None = None
        best_path: list[str] = []
        best_score = -1.0
        for root in root_nodes:
            root_id = root.id or 0
            for path_titles, node in root_search_spaces.get(root_id, []):
                score = _score_unit_against_tree_path(bundle, path_titles, node)
                if score > best_score:
                    best_score = score
                    best_root_id = root_id
                    best_path = path_titles
        if best_root_id is None:
            continue
        assignments[best_root_id].append(
            bundle.model_copy(update={"curriculum_path": best_path})
        )
    return assignments


def _collect_tree_node_paths(
    root: ThemeTreeNode,
    children_by_parent_id: dict[int | None, list[ThemeTreeNode]],
) -> list[tuple[list[str], ThemeTreeNode]]:
    collected: list[tuple[list[str], ThemeTreeNode]] = []

    def _walk(current_node: ThemeTreeNode, current_path: list[str]) -> None:
        collected.append((list(current_path), current_node))
        for child in children_by_parent_id.get(current_node.id, []):
            _walk(child, [*current_path, child.title])

    _walk(root, [root.title])
    return collected


def _score_unit_against_tree_path(
    bundle: TeachingUnitBundle,
    path_titles: list[str],
    node: ThemeTreeNode,
) -> float:
    unit_title_tokens = _tokenize_text(bundle.title)
    unit_context_tokens = _tokenize_text(
        " ".join([bundle.title, bundle.summary, *bundle.learning_objectives[:2]])
    )
    path_title_tokens = _tokenize_text(" ".join(path_titles))
    path_context_tokens = _tokenize_text(" ".join([*path_titles, node.summary]))
    if not unit_context_tokens or not path_context_tokens:
        return 0.0

    title_overlap = len(unit_title_tokens & path_title_tokens)
    context_overlap = len(unit_context_tokens & path_context_tokens)
    overlap_ratio = context_overlap / max(len(unit_context_tokens), 1)

    score = overlap_ratio + title_overlap * 0.45 + max(len(path_titles) - 1, 0) * 0.05
    if bundle.is_procedural == _path_looks_procedural(path_titles, node.summary):
        score += 0.8
    if bundle.is_procedural and not _path_looks_procedural(path_titles, node.summary):
        score -= 0.5
    return score


# TODO 这里太死板了，肯定不行，就算分小章节也不能这么分
def _render_unit_section(bundle: TeachingUnitBundle) -> list[str]:
    lines = [f"## {bundle.title}", ""]
    if bundle.curriculum_path:
        lines.append(f"> 所属主题：{' > '.join(bundle.curriculum_path)}")
        lines.append("")

    lines.extend(["### 这一单元在讲什么", ""])
    lines.append(bundle.summary or f"本单元围绕 {bundle.title} 组织可复习、可迁移的知识结构。")
    lines.append("")

    lines.extend(["### 学完之后你应该会什么", ""])
    objectives = bundle.learning_objectives or [f"能够围绕 {bundle.title} 建立稳定、可迁移的理解框架。"]
    lines.extend(f"- {objective}" for objective in objectives[:4])
    lines.append("")

    lines.extend(["### 建议学习顺序", ""])
    lines.extend(f"- {step}" for step in _build_unit_route(bundle))
    lines.append("")

    lines.extend(
        [
            "### 核心规则与要求" if bundle.is_procedural else "### 核心概念与方法",
            "",
        ]
    )
    core_points = _render_core_points(bundle)
    if core_points:
        lines.extend(f"- {point}" for point in core_points)
    else:
        lines.append(f"- 围绕 {bundle.title} 回到原资料中的关键片段，把概念、方法和表达规范串成一条线。")
    lines.append("")

    lines.extend(["### 和原资料的对应", ""])
    material_signals = _render_material_signals(bundle)
    lines.extend(f"- {signal}" for signal in material_signals)
    lines.append("")

    lines.extend(["### 题型联系与学习建议", ""])
    practice_guidance = _render_practice_guidance(bundle)
    lines.extend(f"- {item}" for item in practice_guidance)
    lines.append("")
    return lines


def _build_chapter_summary(
    tree_node: ThemeTreeNode,
    unit_bundles: list[TeachingUnitBundle],
) -> str:
    if tree_node.summary.strip():
        return _clean_sentence(tree_node.summary, max_chars=140)
    unit_titles = [bundle.title for bundle in unit_bundles[:4]]
    if unit_titles:
        joined = "、".join(unit_titles)
        return f"本章把 {joined} 等分散材料重新整理成一条清晰的学习主线，帮助你先搭框架，再抓方法，最后完成题型迁移。"
    return f"本章系统整理 {tree_node.title} 相关知识。"


def _build_chapter_route(unit_bundles: list[TeachingUnitBundle]) -> list[str]:
    if not unit_bundles:
        return ["先梳理材料主线，再结合例题完成迁移。"]

    if all(bundle.is_procedural for bundle in unit_bundles):
        return [
            "先把考试流程、答题位置和工具要求讲清楚，避免在执行层面失分。",
            "再把容易忽略的规范动作逐条核对，确保知道哪些行为会直接导致无效作答。",
            "最后通过模拟作答把这些规则变成稳定习惯。",
        ]

    unit_titles = [bundle.title for bundle in unit_bundles]
    if len(unit_titles) == 1:
        return [
            f"先围绕 {unit_titles[0]} 搭起整体框架，再回到原资料里的典型场景检查自己能否真正讲清、做对、迁移。",
        ]
    if len(unit_titles) == 2:
        return [
            f"先用 {unit_titles[0]} 搭起本章的基础骨架。",
            f"再把 {unit_titles[1]} 接到同一条问题链上，形成概念、方法和题型的闭环。",
        ]
    middle_titles = "、".join(unit_titles[1:-1][:2])
    return [
        f"先从 {unit_titles[0]} 入手，把本章最基础的对象、定义或背景搭稳。",
        f"再顺着 {middle_titles or unit_titles[1]} 把方法和结构逐步展开，弄清它们各自解决什么问题。",
        f"最后回到 {unit_titles[-1]} 这类综合场景，检查自己能不能把前面的知识真正串起来用。",
    ]


def _build_unit_route(bundle: TeachingUnitBundle) -> list[str]:
    if bundle.is_procedural:
        return [
            "先把考试流程和作答边界讲清楚，知道哪些要求是必须遵守的硬规则。",
            "再逐条核对填涂、书写、答题区域和工具选择，避免低级失误。",
            "最后通过模拟作答把规范动作固定下来，而不是只停留在看懂规则。",
        ]

    concept_names = [
        point.name
        for point in bundle.knowledge_points
        if point.node_type in {"Topic", "Concept", "Definition"}
    ][:2]
    method_names = [
        point.name
        for point in bundle.knowledge_points
        if point.node_type == "Method"
    ][:2]
    example_name = ""
    if bundle.example_points:
        example_name = bundle.example_points[0].name
    elif bundle.example_packets:
        example_name = _packet_display_title(bundle.example_packets[0])

    route: list[str] = []
    if concept_names:
        route.append(f"先把 {'、'.join(concept_names)} 这些基础对象和定义讲清楚。")
    if method_names:
        route.append(f"再把 {'、'.join(method_names)} 这些处理路径练熟，明确它们分别在什么情境下触发。")
    if example_name:
        route.append(f"最后回到 {example_name} 这类材料或题型，检查自己能否把前面的知识真正用起来。")
    if not route:
        route.append(f"先梳理 {bundle.title} 的核心问题，再结合原资料中的例子完成归纳与迁移。")
    return route[:3]


def _render_core_points(bundle: TeachingUnitBundle) -> list[str]:
    if bundle.knowledge_points:
        return [
            f"{_knowledge_point_label(point, procedural=bundle.is_procedural)}{point.name}：{point.summary or _default_point_summary(point)}"
            for point in bundle.knowledge_points[:6]
        ]

    if bundle.learning_objectives:
        return [objective for objective in bundle.learning_objectives[:4]]

    return []


def _render_material_signals(bundle: TeachingUnitBundle) -> list[str]:
    packets = bundle.evidence_packets or bundle.example_packets
    if not packets:
        return ["这部分主要依据教学单元摘要整理，当前没有直接命中的原始片段。"]

    signals: list[str] = []
    for packet in packets[:4]:
        detail = _clean_sentence(packet.preview, max_chars=110)
        extras: list[str] = []
        if packet.formula_refs:
            extras.append(f"重点公式：{'、'.join(packet.formula_refs[:2])}")
        if packet.image_refs:
            extras.append(f"配图素材 {len(packet.image_refs)} 个")
        extra_text = f"（{'；'.join(extras)}）" if extras else ""
        signals.append(f"{_packet_display_title(packet)}：{detail}{extra_text}")
    return signals


def _render_practice_guidance(bundle: TeachingUnitBundle) -> list[str]:
    guidance: list[str] = []
    for point in bundle.example_points[:2]:
        example_name = _display_example_name(point.name)
        if bundle.is_procedural:
            guidance.append(
                f"把“{example_name}”这类规范要求单独列出来核对，确保自己知道应该怎么做，也知道做错会带来什么后果。"
            )
            continue
        guidance.append(
            f"可用“{example_name}”这一类题型检查自己是否已经把核心概念和方法串起来了。{point.summary or ''}".strip()
        )

    example_titles = {
        _packet_display_title(packet)
        for packet in bundle.example_packets
    }
    for title in list(example_titles)[:2]:
        if bundle.is_procedural:
            guidance.append(f"回看原资料中的“{title}”，重点核对流程、位置、工具和填写规范是否都能落实到位。")
            continue
        guidance.append(f"回看原资料中的“{title}”，重点核对题型触发条件、步骤展开和表达是否完整。")

    formula_refs = [
        formula
        for packet in [*bundle.evidence_packets, *bundle.example_packets]
        for formula in packet.formula_refs
    ]
    if formula_refs:
        guidance.append(f"本单元反复出现的表达式/公式有：{'、'.join(list(dict.fromkeys(formula_refs))[:3])}。")

    if not guidance:
        guidance.append(f"建议把 {bundle.title} 与本章其余单元联动复习，重点检查概念定义、方法触发条件和表达规范。")
    return guidance[:4]


def _parse_learning_objectives(revision: TeachingUnitRevision | None) -> list[str]:
    if revision is None or not revision.learning_objectives_json:
        return []
    try:
        payload = json.loads(revision.learning_objectives_json)
    except (TypeError, ValueError):
        return []
    return [
        _clean_sentence(str(item), max_chars=80)
        for item in payload
        if str(item).strip()
    ][:4]


def _membership_role_priority(role: str) -> int:
    if role == "core":
        return 0
    if role == "support":
        return 1
    if role == "example":
        return 2
    return 3


def _knowledge_point_label(point: KnowledgePoint, *, procedural: bool) -> str:
    if procedural:
        return "要求 · "
    if point.node_type == "Method":
        return "方法 · "
    if point.node_type == "Definition":
        return "定义 · "
    if point.node_type == "Topic":
        return "主线 · "
    return "概念 · "


def _default_point_summary(point: KnowledgePoint) -> str:
    if point.node_type == "Method":
        return f"这是处理 {point.name} 相关问题时反复会用到的关键路径。"
    if point.node_type == "Definition":
        return f"这是理解 {point.name} 时需要先站稳的定义基础。"
    return f"这是搭建 {point.name} 理解框架时绕不过去的基础抓手。"


def _dedupe_points(points: list[KnowledgePoint]) -> list[KnowledgePoint]:
    deduped: list[KnowledgePoint] = []
    seen_names: set[str] = set()
    for point in sorted(
        points,
        key=lambda item: (
            _POINT_TYPE_PRIORITY.get(item.node_type, 99),
            _membership_role_priority(item.role),
            item.name,
        ),
    ):
        normalized_name = point.name.strip().lower()
        if not normalized_name or normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        deduped.append(point)
    return deduped


def _should_skip_knowledge_point(point: KnowledgePoint) -> bool:
    normalized_name = point.name.strip().lower()
    normalized_summary = point.summary.strip().lower()
    if not normalized_name:
        return True
    if any(hint in normalized_name for hint in _GENERIC_POINT_HINTS):
        return True
    if any(hint in normalized_summary for hint in _GENERIC_POINT_HINTS):
        return True
    if point.node_type == "Topic" and any(hint in normalized_name for hint in ("试卷", "page ocr")):
        return True
    return False


def _is_example_point(point: KnowledgePoint) -> bool:
    return point.role == "example" or point.node_type == "Example"


def _packet_display_title(packet: SectionPacket) -> str:
    title = packet.title.strip()
    if title and title.lower() not in {"page ocr", "preamble"}:
        return title
    header_path = packet.header_path.strip()
    if header_path:
        return header_path
    return f"资料片段 {packet.chunk_index + 1}"


def _looks_like_example_packet(packet: SectionPacket) -> bool:
    if packet.question_block_count > 0:
        return True
    title = f"{packet.title} {packet.header_path}".lower()
    if any(hint in title for hint in ("题", "example", "例", "练习")):
        return True
    return bool(packet.image_refs)


def _clean_sentence(text: str, *, max_chars: int) -> str:
    normalized = _SPACE_PATTERN.sub(" ", text.replace("\n", " ")).strip()
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip("，,；;：: ") + "..."


def _is_procedural_text(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in _PROCEDURAL_HINTS)


def _path_looks_procedural(path_titles: list[str], summary: str) -> bool:
    return _is_procedural_text(" ".join([*path_titles, summary]))


def _tokenize_text(text: str) -> set[str]:
    normalized = _SPACE_PATTERN.sub("", text)
    tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z]{2,}", normalized)
        if len(token.strip()) >= 2
    }
    for segment in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        if len(segment) <= 8:
            tokens.add(segment)
        for size in (2, 3, 4):
            if len(segment) < size:
                continue
            for index in range(len(segment) - size + 1):
                tokens.add(segment[index:index + size])
    return tokens


def _display_example_name(name: str) -> str:
    cleaned = _QUESTION_PREFIX_PATTERN.sub("", name.strip())
    return _clean_sentence(cleaned, max_chars=50) or _clean_sentence(name.strip(), max_chars=50)
