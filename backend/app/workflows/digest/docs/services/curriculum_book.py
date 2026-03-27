"""Build curriculum-aligned knowledge docs from the compressed schema."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, Field
from sqlmodel import select

from app.core.database import managed_session
from app.models.curriculum import TeachingUnit, ThemeTreeNode, UnitTreeMembership
from app.models.knowledge_graph import KnowledgeNode
from app.repositories import curriculum_repo, kg_repo
from app.workflows.digest.shared.models import SectionPacket, SharedInputs
from app.workflows.digest.unified.models import MaterializedSections

_SPACE_PATTERN = re.compile(r"\s+")
_QUESTION_PREFIX_PATTERN = re.compile(
    r"^(?:question\s*\d+\s*[:：]?\s*|第\s*\d+\s*题\s*[:：]?\s*)",
    re.IGNORECASE,
)


class KnowledgePoint(BaseModel):
    name: str
    summary: str = ""
    role: str = "support"
    node_type: str = "Concept"


class TeachingUnitBundle(BaseModel):
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


class CurriculumChapterBundle(BaseModel):
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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

        memberships_by_unit_id = {
            unit_id: curriculum_repo.list_memberships_by_unit(session, unit_id)
            for unit_id in unit_by_id
        }
        knowledge_node_ids = list(
            {
                membership.knowledge_node_id
                for unit_memberships in memberships_by_unit_id.values()
                for membership in unit_memberships
            }
        )
        knowledge_nodes = (
            list(
                session.exec(
                    select(KnowledgeNode).where(KnowledgeNode.id.in_(knowledge_node_ids))
                ).all()
            )
            if knowledge_node_ids
            else []
        )
        node_by_id = {
            node.id: node
            for node in knowledge_nodes
            if node.id is not None
        }
        chunk_uids_by_node_id: dict[int, list[str]] = defaultdict(list)
        for node_id in knowledge_node_ids:
            for evidence in kg_repo.list_evidence_by_entity(
                session,
                "node",
                node_id,
                is_active=True,
            ):
                chunk_uid = chunk_id_to_chunk_uid.get(evidence.chunk_id)
                if chunk_uid:
                    chunk_uids_by_node_id[node_id].append(chunk_uid)

        children_by_parent_id: dict[int | None, list[ThemeTreeNode]] = defaultdict(list)
        for node in tree_nodes:
            children_by_parent_id[node.parent_tree_node_id].append(node)
        for siblings in children_by_parent_id.values():
            siblings.sort(key=lambda item: (item.order_index, item.title))

        primary_memberships_by_tree_node_id: dict[int, list[UnitTreeMembership]] = defaultdict(list)
        for membership in memberships:
            primary_memberships_by_tree_node_id[membership.tree_node_id].append(membership)

        unit_bundles_by_id = {
            unit_id: _build_teaching_unit_bundle(
                unit=unit_by_id[unit_id],
                memberships=memberships_by_unit_id.get(unit_id, []),
                node_by_id=node_by_id,
                chunk_uids_by_node_id=chunk_uids_by_node_id,
                packets_by_uid=packets_by_uid,
            )
            for unit_id in unit_by_id
        }

        root_nodes = [
            node
            for node in children_by_parent_id.get(None, [])
            if node.node_type != "uncategorized"
        ] or children_by_parent_id.get(None, [])

        chapters: list[CurriculumChapterBundle] = []
        for root in root_nodes:
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
    memberships: list[Any],
    node_by_id: dict[int, KnowledgeNode],
    chunk_uids_by_node_id: dict[int, list[str]],
    packets_by_uid: dict[str, SectionPacket],
) -> TeachingUnitBundle:
    knowledge_points: list[KnowledgePoint] = []
    example_points: list[KnowledgePoint] = []
    chunk_uids: list[str] = []

    for membership in sorted(memberships, key=lambda item: (item.role, -item.score)):
        node = node_by_id.get(membership.knowledge_node_id)
        if node is None or node.id is None:
            continue
        point = KnowledgePoint(
            name=node.canonical_name,
            summary=_clean_sentence(node.summary, max_chars=120),
            role=membership.role,
            node_type=node.node_type,
        )
        if point.node_type == "Example" or point.role == "example":
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

    return TeachingUnitBundle(
        unit_id=unit.id or 0,
        title=unit.title.strip() or unit.canonical_name,
        summary=_clean_sentence(unit.summary, max_chars=180),
        learning_objectives=_parse_learning_objectives(unit),
        source_file_ids=list(dict.fromkeys(packet.source_file_id for packet in packets)),
        chunk_uids=deduped_chunk_uids,
        knowledge_points=_dedupe_points(knowledge_points)[:6],
        example_points=_dedupe_points(example_points)[:4],
        evidence_packets=packets[:4],
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
        for membership in primary_memberships_by_tree_node_id.get(current_node.id or 0, []):
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
    sorted_units = sorted(unit_bundles, key=lambda bundle: (bundle.curriculum_path, bundle.title))
    source_file_ids = list(
        dict.fromkeys(
            file_id
            for bundle in sorted_units
            for file_id in bundle.source_file_ids
        )
    )
    chunk_uids = list(
        dict.fromkeys(
            chunk_uid
            for bundle in sorted_units
            for chunk_uid in bundle.chunk_uids
        )
    )
    markdown = _render_chapter_markdown(tree_node.title, sorted_units)
    return CurriculumChapterBundle(
        chapter_index=chapter_index,
        title=tree_node.title,
        summary=_build_chapter_summary(tree_node.title, sorted_units),
        curriculum_path=[tree_node.title],
        section_titles=[bundle.title for bundle in sorted_units],
        source_file_ids=source_file_ids,
        chunk_uids=chunk_uids,
        tags=[tree_node.title, *[bundle.title for bundle in sorted_units[:6]]],
        markdown=markdown,
    )


def _render_chapter_markdown(chapter_title: str, bundles: list[TeachingUnitBundle]) -> str:
    lines = [
        f"# {chapter_title}",
        "",
        "## Overview",
        "",
        _build_chapter_summary(chapter_title, bundles),
        "",
    ]
    for bundle in bundles:
        lines.extend(
            [
                f"## {bundle.title}",
                "",
                bundle.summary or f"This section organizes the core ideas behind {bundle.title}.",
                "",
            ]
        )
        if bundle.learning_objectives:
            lines.extend(["### Learning Objectives", ""])
            lines.extend(f"- {objective}" for objective in bundle.learning_objectives[:4])
            lines.append("")
        if bundle.knowledge_points:
            lines.extend(["### Core Points", ""])
            lines.extend(
                f"- {point.name}: {point.summary or 'Key knowledge point for this section.'}"
                for point in bundle.knowledge_points[:6]
            )
            lines.append("")
        if bundle.example_points:
            lines.extend(["### Examples", ""])
            lines.extend(
                f"- {_display_example_name(point.name)}: "
                f"{point.summary or 'Review this example in the source material.'}"
                for point in bundle.example_points[:4]
            )
            lines.append("")
        if bundle.evidence_packets:
            lines.extend(["### Source Passages", ""])
            lines.extend(
                f"- {_packet_display_title(packet)}: {_clean_sentence(packet.preview, max_chars=110)}"
                for packet in bundle.evidence_packets[:4]
            )
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def _build_chapter_summary(title: str, bundles: list[TeachingUnitBundle]) -> str:
    bundle_titles = [bundle.title for bundle in bundles[:4]]
    if bundle_titles:
        return f"This chapter reorganizes {title} around {' / '.join(bundle_titles)}."
    return f"This chapter summarizes the curriculum branch {title}."


def _parse_learning_objectives(unit: TeachingUnit) -> list[str]:
    try:
        payload = json.loads(unit.learning_objectives_json or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    return [
        _clean_sentence(str(item), max_chars=80)
        for item in payload
        if str(item).strip()
    ][:4]


def _dedupe_points(points: list[KnowledgePoint]) -> list[KnowledgePoint]:
    deduped: list[KnowledgePoint] = []
    seen_names: set[str] = set()
    for point in points:
        normalized_name = point.name.strip().lower()
        if not normalized_name or normalized_name in seen_names:
            continue
        seen_names.add(normalized_name)
        deduped.append(point)
    return deduped


def _packet_display_title(packet: SectionPacket) -> str:
    if packet.title.strip() and packet.title.strip().lower() not in {"page ocr", "preamble"}:
        return packet.title.strip()
    if packet.header_path.strip():
        return packet.header_path.strip()
    return f"Source snippet {packet.chunk_index + 1}"


def _display_example_name(name: str) -> str:
    cleaned = _QUESTION_PREFIX_PATTERN.sub("", name.strip())
    return _clean_sentence(cleaned, max_chars=50) or _clean_sentence(name.strip(), max_chars=50)


def _clean_sentence(text: str, *, max_chars: int) -> str:
    normalized = _SPACE_PATTERN.sub(" ", text.replace("\n", " ")).strip()
    if not normalized:
        return ""
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip(",. ;:") + "..."
