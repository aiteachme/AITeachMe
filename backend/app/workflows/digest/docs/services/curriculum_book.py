"""Build curriculum-aligned knowledge docs from the published curriculum tree."""

from __future__ import annotations

import json
from collections import defaultdict

from pydantic import BaseModel, Field
from sqlmodel import select

from app.core.database import managed_session
from app.models import (
    CurriculumTreeNode,
    CurriculumUnitLink,
    KnowledgeEvidence,
    KnowledgeNode,
    RetrievalChunk,
    TeachingUnit,
    TeachingUnitMembership,
)
from app.workflows.digest.shared.models import SectionPacket, SharedInputs
from app.workflows.digest.unified.models import MaterializedSections


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
    packets: list[SectionPacket] = Field(default_factory=list)


class CurriculumChapterBundle(BaseModel):
    """One final docs chapter synthesized from a curriculum branch."""

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
        tree_nodes = list(
            session.exec(
                select(CurriculumTreeNode)
                .where(CurriculumTreeNode.curriculum_version_id == theme_tree_version_id)
                .order_by(CurriculumTreeNode.order_index.asc(), CurriculumTreeNode.id.asc())  # type: ignore[union-attr]
            ).all()
        )
        links = list(
            session.exec(
                select(CurriculumUnitLink)
                .where(CurriculumUnitLink.curriculum_version_id == theme_tree_version_id)
                .order_by(CurriculumUnitLink.score.desc(), CurriculumUnitLink.id.asc())  # type: ignore[union-attr]
            ).all()
        )
        if not tree_nodes or not links:
            return [], []

        unit_ids = {item.teaching_unit_id for item in links}
        units = {
            int(unit.id): unit
            for unit in session.exec(
                select(TeachingUnit).where(TeachingUnit.id.in_(unit_ids))  # type: ignore[union-attr]
            ).all()
            if unit.id is not None
        }
        memberships = list(
            session.exec(
                select(TeachingUnitMembership).where(
                    TeachingUnitMembership.unit_id.in_(unit_ids)  # type: ignore[union-attr]
                )
            ).all()
        )
        node_ids = {item.knowledge_node_id for item in memberships}
        nodes = {
            int(node.id): node
            for node in session.exec(
                select(KnowledgeNode).where(KnowledgeNode.id.in_(node_ids))  # type: ignore[union-attr]
            ).all()
            if node.id is not None
        }
        evidence_rows = list(
            session.exec(
                select(KnowledgeEvidence).where(
                    KnowledgeEvidence.node_id.in_(node_ids),  # type: ignore[union-attr]
                )
            ).all()
        )
        retrieval_chunk_ids = {item.retrieval_chunk_id for item in evidence_rows}
        retrieval_chunks = {
            int(chunk.id): chunk
            for chunk in session.exec(
                select(RetrievalChunk).where(RetrievalChunk.id.in_(retrieval_chunk_ids))  # type: ignore[union-attr]
            ).all()
            if chunk.id is not None
        }

    memberships_by_unit_id: dict[int, list[TeachingUnitMembership]] = defaultdict(list)
    for membership in memberships:
        memberships_by_unit_id[int(membership.unit_id)].append(membership)

    chunk_uids_by_node_id: dict[int, list[str]] = defaultdict(list)
    for evidence in evidence_rows:
        if evidence.node_id is None:
            continue
        chunk = retrieval_chunks.get(int(evidence.retrieval_chunk_id))
        if chunk is None:
            continue
        chunk_uid = chunk_id_to_chunk_uid.get(int(chunk.id or 0), chunk.digest_chunk_uid)
        if chunk_uid:
            chunk_uids_by_node_id[int(evidence.node_id)].append(chunk_uid)

    children_by_parent_id: dict[int | None, list[CurriculumTreeNode]] = defaultdict(list)
    for node in tree_nodes:
        children_by_parent_id[node.parent_tree_node_id].append(node)
    for siblings in children_by_parent_id.values():
        siblings.sort(key=lambda item: (item.order_index, item.title))

    primary_links_by_tree_node_id: dict[int, list[CurriculumUnitLink]] = defaultdict(list)
    for link in links:
        if link.membership_role != "primary":
            continue
        primary_links_by_tree_node_id[int(link.tree_node_id)].append(link)

    unit_bundles_by_id = {
        unit_id: _build_teaching_unit_bundle(
            unit=unit,
            memberships=memberships_by_unit_id.get(unit_id, []),
            nodes=nodes,
            chunk_uids_by_node_id=chunk_uids_by_node_id,
            packets_by_uid=packets_by_uid,
        )
        for unit_id, unit in units.items()
    }

    roots = [node for node in children_by_parent_id.get(None, [])]
    chapters: list[CurriculumChapterBundle] = []
    used_unit_ids: set[int] = set()
    for root in roots:
        bundles = _collect_unit_bundles_for_tree_node(
            node=root,
            path=[root.title],
            children_by_parent_id=children_by_parent_id,
            primary_links_by_tree_node_id=primary_links_by_tree_node_id,
            unit_bundles_by_id=unit_bundles_by_id,
        )
        if not bundles:
            continue
        used_unit_ids.update(bundle.unit_id for bundle in bundles)
        chapters.append(
            _build_curriculum_chapter_bundle(
                chapter_index=len(chapters) + 1,
                tree_node=root,
                unit_bundles=bundles,
            )
        )

    orphan_bundles = [
        bundle
        for bundle in unit_bundles_by_id.values()
        if bundle.unit_id not in used_unit_ids
    ]
    for bundle in orphan_bundles:
        synthetic_root = CurriculumTreeNode(
            id=None,
            curriculum_version_id=theme_tree_version_id,
            parent_tree_node_id=None,
            title=bundle.title,
            normalized_title=bundle.title.lower(),
            node_type="theme",
            anchor_type="graph_discovered",
            confidence=0.5,
            is_system=False,
            order_index=len(chapters) + 1,
            summary=bundle.summary,
        )
        chapters.append(
            _build_curriculum_chapter_bundle(
                chapter_index=len(chapters) + 1,
                tree_node=synthetic_root,
                unit_bundles=[bundle],
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
    memberships: list[TeachingUnitMembership],
    nodes: dict[int, KnowledgeNode],
    chunk_uids_by_node_id: dict[int, list[str]],
    packets_by_uid: dict[str, SectionPacket],
) -> TeachingUnitBundle:
    knowledge_points: list[KnowledgePoint] = []
    chunk_uids: list[str] = []
    for membership in sorted(
        memberships,
        key=lambda item: (0 if item.role == "core" else 1, -item.score, item.id or 0),
    ):
        node = nodes.get(int(membership.knowledge_node_id))
        if node is None:
            continue
        knowledge_points.append(
            KnowledgePoint(
                name=node.canonical_name,
                summary=node.summary,
                role=membership.role,
                node_type=node.node_type,
            )
        )
        chunk_uids.extend(chunk_uids_by_node_id.get(int(node.id or 0), []))

    deduped_chunk_uids = [
        chunk_uid
        for chunk_uid in dict.fromkeys(chunk_uids)
        if chunk_uid in packets_by_uid
    ]
    packets = [packets_by_uid[chunk_uid] for chunk_uid in deduped_chunk_uids]
    learning_objectives = []
    try:
        payload = json.loads(unit.learning_objectives_json or "[]")
        if isinstance(payload, list):
            learning_objectives = [str(item) for item in payload if str(item).strip()]
    except json.JSONDecodeError:
        learning_objectives = []

    return TeachingUnitBundle(
        unit_id=int(unit.id or 0),
        title=unit.canonical_name,
        summary=unit.summary,
        learning_objectives=learning_objectives[:4],
        source_file_ids=list(dict.fromkeys(packet.source_file_id for packet in packets)),
        chunk_uids=deduped_chunk_uids,
        knowledge_points=_dedupe_points(knowledge_points)[:8],
        packets=packets[:6],
    )


def _collect_unit_bundles_for_tree_node(
    *,
    node: CurriculumTreeNode,
    path: list[str],
    children_by_parent_id: dict[int | None, list[CurriculumTreeNode]],
    primary_links_by_tree_node_id: dict[int, list[CurriculumUnitLink]],
    unit_bundles_by_id: dict[int, TeachingUnitBundle],
) -> list[TeachingUnitBundle]:
    collected: list[TeachingUnitBundle] = []
    seen_unit_ids: set[int] = set()

    def _walk(current_node: CurriculumTreeNode, current_path: list[str]) -> None:
        direct_links = primary_links_by_tree_node_id.get(int(current_node.id or 0), [])
        for link in direct_links:
            base_bundle = unit_bundles_by_id.get(int(link.teaching_unit_id))
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
    tree_node: CurriculumTreeNode,
    unit_bundles: list[TeachingUnitBundle],
) -> CurriculumChapterBundle:
    sorted_units = sorted(unit_bundles, key=lambda item: (item.curriculum_path, item.title))
    chapter_title = tree_node.title.strip() or f"第{chapter_index}章"
    chapter_summary = _build_chapter_summary(chapter_title, sorted_units)
    section_titles = [bundle.title for bundle in sorted_units]
    source_file_ids = list(
        dict.fromkeys(file_id for bundle in sorted_units for file_id in bundle.source_file_ids)
    )
    chunk_uids = list(
        dict.fromkeys(chunk_uid for bundle in sorted_units for chunk_uid in bundle.chunk_uids)
    )
    tags = list(
        dict.fromkeys(
            [
                chapter_title,
                *section_titles,
                *[
                    point.name
                    for bundle in sorted_units
                    for point in bundle.knowledge_points[:2]
                ],
            ]
        )
    )[:12]
    markdown = _render_chapter_markdown(
        chapter_title=chapter_title,
        chapter_summary=chapter_summary,
        bundles=sorted_units,
    )
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


def _build_chapter_summary(chapter_title: str, unit_bundles: list[TeachingUnitBundle]) -> str:
    leading_titles = "、".join(bundle.title for bundle in unit_bundles[:4])
    if leading_titles:
        return f"本章围绕 {leading_titles} 组织知识主线，帮助你把分散材料整理成可复习、可迁移的理解结构。"
    return f"本章系统整理 {chapter_title} 相关知识。"


def _render_chapter_markdown(
    *,
    chapter_title: str,
    chapter_summary: str,
    bundles: list[TeachingUnitBundle],
) -> str:
    lines = [
        f"# {chapter_title}",
        "",
        "## 本章导读",
        "",
        chapter_summary,
        "",
        "## 学习地图",
        "",
    ]
    for bundle in bundles:
        guide = f"- {bundle.title}"
        if bundle.summary:
            guide += f"：{bundle.summary[:120]}"
        lines.append(guide)

    lines.extend(["", "## 分主题讲解", ""])
    for bundle in bundles:
        lines.extend(_render_unit_section(bundle))
    return "\n".join(lines).strip() + "\n"


def _render_unit_section(bundle: TeachingUnitBundle) -> list[str]:
    lines = [f"## {bundle.title}", ""]
    if bundle.curriculum_path:
        lines.append(f"> 所属路径：{' > '.join(bundle.curriculum_path)}")
        lines.append("")
    lines.append(bundle.summary or f"本单元围绕 {bundle.title} 搭建稳定的知识框架。")
    lines.append("")

    if bundle.learning_objectives:
        lines.extend(["### 学习目标", ""])
        lines.extend(f"- {objective}" for objective in bundle.learning_objectives[:4])
        lines.append("")

    if bundle.knowledge_points:
        lines.extend(["### 核心知识点", ""])
        for point in bundle.knowledge_points[:8]:
            label = point.role if point.role != "core" else point.node_type
            summary = point.summary.strip() or f"围绕 {point.name} 建立可迁移的理解。"
            lines.append(f"- [{label}] {point.name}：{summary[:140]}")
        lines.append("")

    if bundle.packets:
        lines.extend(["### 对应材料线索", ""])
        for packet in bundle.packets[:4]:
            preview = packet.preview.strip() or packet.normalized_content[:120].replace("\n", " ")
            detail = f"- {packet.title}：{preview[:140]}"
            extras: list[str] = []
            if packet.formula_refs:
                extras.append(f"公式 {', '.join(packet.formula_refs[:2])}")
            if packet.image_refs:
                extras.append(f"图片 {len(packet.image_refs)} 张")
            if extras:
                detail += f"（{'；'.join(extras)}）"
            lines.append(detail)
        lines.append("")
    return lines


def _dedupe_points(points: list[KnowledgePoint]) -> list[KnowledgePoint]:
    deduped: list[KnowledgePoint] = []
    seen_names: set[str] = set()
    for point in points:
        normalized = point.name.strip().lower()
        if not normalized or normalized in seen_names:
            continue
        seen_names.add(normalized)
        deduped.append(point)
    return deduped
