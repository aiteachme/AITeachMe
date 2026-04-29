"""Low-cost relation stitching for KG docs-sync extraction payloads.

This module runs after section-level LLM extraction and before persistence.
It does not call LLMs or query the database; it only adds conservative edges
between already extracted units when the source evidence is local and cheap.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import replace
import hashlib

from app.models.knowledge_taxonomy import normalize_knowledge_unit_type, validate_relation_direction
from app.utils.knowledge_helpers import normalize_name
from app.workflows.digest.common.markdown_knowledge_anchors import MarkdownKnowledgeUnit
from app.workflows.digest.kg_doc_sync.lib.models import (
    KnowledgeSyncExtractionPayload,
    MarkdownExtractedEdge,
)

_PRIMARY_UNIT_TYPES = {"concept", "method", "theorem", "formula"}
_SECONDARY_TO_PARENT_RELATION = {
    "definition": "derivation",
    "formula": "derivation",
    "theorem": "derivation",
    "proof_step": "derivation",
    "example": "example_of",
    "exercise": "example_of",
    "remark": "application",
    "method": "application",
}
_MAX_SECTION_STITCH_EDGES_PER_SECTION = 6
_MAX_MENTION_STITCH_EDGES = 160
_MAX_MENTION_EDGES_PER_UNIT = 2
_MAX_MENTION_SCAN_UNITS = 800


def _section_key(unit: MarkdownKnowledgeUnit) -> tuple[int, int, int, str]:
    body = str(unit.body_markdown or "")
    body_hash = hashlib.sha1(body[:6000].encode("utf-8")).hexdigest()[:12] if body else ""
    return (
        int(unit.knowledge_document_id or 0),
        int(unit.chapter_index or 0),
        int(unit.line_no or 0),
        body_hash,
    )


def _edge_key(edge: MarkdownExtractedEdge) -> tuple[str, str, str]:
    return edge.source_anchor, edge.target_anchor, edge.edge_type


def _edge_degree_by_anchor(edges: list[MarkdownExtractedEdge]) -> dict[str, int]:
    degree: dict[str, int] = defaultdict(int)
    for edge in edges:
        degree[edge.source_anchor] += 1
        degree[edge.target_anchor] += 1
    return degree


def _unit_type(unit: MarkdownKnowledgeUnit) -> str:
    return normalize_knowledge_unit_type(unit.knowledge_unit_type)


def _choose_section_parent(units: list[MarkdownKnowledgeUnit]) -> MarkdownKnowledgeUnit | None:
    for preferred_type in ("concept", "method", "theorem", "formula"):
        for unit in units:
            if _unit_type(unit) == preferred_type:
                return unit
    return units[0] if units else None


def _relation_to_section_parent(unit: MarkdownKnowledgeUnit, parent: MarkdownKnowledgeUnit) -> str | None:
    unit_type = _unit_type(unit)
    parent_type = _unit_type(parent)
    relation = _SECONDARY_TO_PARENT_RELATION.get(unit_type)
    if relation is None:
        return None
    if relation == "application" and unit_type == "method" and parent_type != "concept":
        relation = "derivation"
    return relation


def _new_edge(
    *,
    source: MarkdownKnowledgeUnit,
    target: MarkdownKnowledgeUnit,
    edge_type: str,
    description: str,
    source_kind: str,
) -> MarkdownExtractedEdge | None:
    if source.anchor == target.anchor:
        return None
    if not validate_relation_direction(
        edge_type=edge_type,
        source_type=source.knowledge_unit_type,
        target_type=target.knowledge_unit_type,
    ):
        return None
    return MarkdownExtractedEdge(
        source_anchor=source.anchor,
        target_anchor=target.anchor,
        edge_type=edge_type,
        description=description,
        source_kind=source_kind,
        knowledge_document_id=source.knowledge_document_id or target.knowledge_document_id,
        chapter_index=int(source.chapter_index or target.chapter_index or 0),
        source_file_ids=list(source.source_file_ids or target.source_file_ids),
        quote_text=source.quote_text or description,
    )


def _append_edge(
    edges: list[MarkdownExtractedEdge],
    edge: MarkdownExtractedEdge | None,
    *,
    seen: set[tuple[str, str, str]],
    degree: dict[str, int],
) -> bool:
    if edge is None:
        return False
    key = _edge_key(edge)
    if key in seen:
        return False
    seen.add(key)
    edges.append(edge)
    degree[edge.source_anchor] += 1
    degree[edge.target_anchor] += 1
    return True


def _add_section_local_edges(
    *,
    units: list[MarkdownKnowledgeUnit],
    edges: list[MarkdownExtractedEdge],
    seen: set[tuple[str, str, str]],
    degree: dict[str, int],
) -> int:
    groups: dict[tuple[int, int, int, str], list[MarkdownKnowledgeUnit]] = defaultdict(list)
    for unit in units:
        groups[_section_key(unit)].append(unit)

    added = 0
    for group_units in groups.values():
        if len(group_units) < 2:
            continue
        parent = _choose_section_parent(group_units)
        if parent is None:
            continue
        section_added = 0
        for unit in group_units:
            if unit.anchor == parent.anchor:
                continue
            if degree.get(unit.anchor, 0) > 0 and degree.get(parent.anchor, 0) > 0:
                continue
            relation = _relation_to_section_parent(unit, parent)
            if relation is None:
                continue
            edge = _new_edge(
                source=unit,
                target=parent,
                edge_type=relation,
                description=f"{unit.name} 在同一小节中服务于 {parent.name} 的理解。",
                source_kind="section_local_stitch",
            )
            if _append_edge(edges, edge, seen=seen, degree=degree):
                added += 1
                section_added += 1
            if section_added >= _MAX_SECTION_STITCH_EDGES_PER_SECTION:
                break
    return added


def _infer_reference_relation(text: str, source_type: str) -> str:
    normalized = normalize_name(text)
    if any(token in normalized for token in ("前提", "基础", "先学", "先掌握", "依赖")):
        return "prerequisite"
    if any(token in normalized for token in ("区别", "对比", "比较", "不同于", "相反")):
        return "contrast"
    if any(token in normalized for token in ("类似", "相似", "同理")):
        return "similar"
    if normalize_knowledge_unit_type(source_type) in {"example", "exercise"}:
        return "example_of"
    if any(token in normalized for token in ("利用", "应用", "借助", "结合", "使用")):
        return "application"
    return "derivation"


def _unique_name_index(units: list[MarkdownKnowledgeUnit]) -> dict[str, MarkdownKnowledgeUnit]:
    by_name: dict[str, list[MarkdownKnowledgeUnit]] = defaultdict(list)
    for unit in units:
        normalized = normalize_name(unit.name)
        if len(normalized) >= 2:
            by_name[normalized].append(unit)
    return {name: matches[0] for name, matches in by_name.items() if len(matches) == 1}


def _add_mention_edges(
    *,
    units: list[MarkdownKnowledgeUnit],
    edges: list[MarkdownExtractedEdge],
    seen: set[tuple[str, str, str]],
    degree: dict[str, int],
) -> int:
    if len(units) > _MAX_MENTION_SCAN_UNITS:
        return 0
    unique_names = _unique_name_index(units)
    if not unique_names:
        return 0

    added = 0
    name_items = sorted(unique_names.items(), key=lambda item: len(item[0]), reverse=True)
    for unit in units:
        if degree.get(unit.anchor, 0) > 0:
            continue
        text = normalize_name(" ".join([unit.summary or "", unit.body_markdown or ""]))
        if not text:
            continue
        per_unit_added = 0
        for normalized_name, target in name_items:
            if target.anchor == unit.anchor or normalized_name not in text:
                continue
            relation = _infer_reference_relation(text, unit.knowledge_unit_type)
            if relation == "prerequisite":
                source, target_unit = target, unit
            else:
                source, target_unit = unit, target
            edge = _new_edge(
                source=source,
                target=target_unit,
                edge_type=relation,
                description=f"{unit.name} 的说明中明确引用了 {target.name}。",
                source_kind="mention_stitch",
            )
            if _append_edge(edges, edge, seen=seen, degree=degree):
                added += 1
                per_unit_added += 1
            if per_unit_added >= _MAX_MENTION_EDGES_PER_UNIT or added >= _MAX_MENTION_STITCH_EDGES:
                break
        if added >= _MAX_MENTION_STITCH_EDGES:
            break
    return added


def _graph_health_metrics(
    *,
    units: list[MarkdownKnowledgeUnit],
    edges: list[MarkdownExtractedEdge],
) -> dict[str, int | float]:
    unit_anchors = {unit.anchor for unit in units}
    degree: dict[str, int] = {anchor: 0 for anchor in unit_anchors}
    adjacency: dict[str, set[str]] = {anchor: set() for anchor in unit_anchors}
    active_edge_count = 0
    for edge in edges:
        if edge.source_anchor not in unit_anchors or edge.target_anchor not in unit_anchors:
            continue
        degree[edge.source_anchor] += 1
        degree[edge.target_anchor] += 1
        adjacency[edge.source_anchor].add(edge.target_anchor)
        adjacency[edge.target_anchor].add(edge.source_anchor)
        active_edge_count += 1

    isolated_count = sum(1 for value in degree.values() if value == 0)
    seen: set[str] = set()
    component_count = 0
    largest_component = 0
    for anchor in unit_anchors:
        if anchor in seen:
            continue
        component_count += 1
        queue = deque([anchor])
        seen.add(anchor)
        size = 0
        while queue:
            current = queue.popleft()
            size += 1
            for neighbor in adjacency[current]:
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        largest_component = max(largest_component, size)

    total_units = len(unit_anchors)
    return {
        "graph_active_unit_count": total_units,
        "graph_active_edge_count": active_edge_count,
        "graph_isolated_unit_count": isolated_count,
        "graph_component_count": component_count,
        "graph_largest_component_unit_count": largest_component,
        "graph_avg_degree": round((sum(degree.values()) / total_units), 4) if total_units else 0.0,
        "graph_isolated_unit_pct": round((isolated_count * 100 / total_units), 2) if total_units else 0.0,
    }


def stitch_knowledge_graph_relations(
    payload: KnowledgeSyncExtractionPayload,
) -> KnowledgeSyncExtractionPayload:
    """Add conservative no-LLM edges to reduce orphan graph units."""

    units = list(payload.units)
    edges = list(payload.extracted_edges)
    seen = {_edge_key(edge) for edge in edges}
    degree = _edge_degree_by_anchor(edges)

    section_edge_count = _add_section_local_edges(
        units=units,
        edges=edges,
        seen=seen,
        degree=degree,
    )
    mention_edge_count = _add_mention_edges(
        units=units,
        edges=edges,
        seen=seen,
        degree=degree,
    )
    health_metrics = _graph_health_metrics(units=units, edges=edges)
    stitched_edge_count = section_edge_count + mention_edge_count

    diagnostics = dict(payload.diagnostics_totals or {})
    diagnostics["stitched_edge_count"] = stitched_edge_count
    diagnostics["section_local_stitch_edge_count"] = section_edge_count
    diagnostics["mention_stitch_edge_count"] = mention_edge_count
    diagnostics.update(health_metrics)

    return replace(
        payload,
        extracted_edges=edges,
        diagnostics_totals=diagnostics,
    )


__all__ = ["stitch_knowledge_graph_relations"]
