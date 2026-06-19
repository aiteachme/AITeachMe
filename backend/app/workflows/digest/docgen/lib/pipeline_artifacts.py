"""Small explicit artifacts for the DocGen pipeline.

These helpers name the major stage outputs without adding another orchestration
layer.  They are intentionally rule-only: the expensive reasoning already
happens in intent, file summary, title lock, brief, and chapter generation calls.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from app.models.knowledge_taxonomy import (
    knowledge_unit_type_label,
    normalize_generated_knowledge_unit_type,
    normalize_knowledge_unit_type,
    normalize_relation_type,
    relation_type_label,
    validate_relation_direction,
)
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    ChapterReviewReport,
    ChapterSourceSlice,
    DocGenContext,
    DocumentBackbone,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    ReviewAction,
    ReviewedChapterDraft,
    SourceAffinityByChapter,
    clean_string_list,
)
from app.workflows.digest.docgen.lib.pipeline_context import merge_unique_profile_texts


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


_KG_MARKDOWN_STYLE_RE = re.compile(r"(\*\*|__|==|`+|\\\(|\\\)|\\\[|\\\]|\$\$?)")


def _evidence_chapter_indices(item: HighConfidenceEvidenceUnit) -> list[int]:
    return sorted(
        index
        for index, score in dict(item.chapter_affinity or {}).items()
        if int(index or 0) > 0 and float(score or 0.0) > 0
    )


def _evidence_payloads(
    evidence_units: Sequence[HighConfidenceEvidenceUnit],
    *,
    limit: int = 16,
) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for item in sorted(evidence_units, key=lambda raw: raw.confidence, reverse=True):
        text = str(item.text or "").strip()
        if not text:
            continue
        payloads.append(
            {
                "evidence_id": item.evidence_id,
                "text": text,
                "source_ref": item.source_ref,
                "source_title": item.source_title,
                "source_span": item.source_span,
                "evidence_type": item.evidence_type,
                "chapter_indices": _evidence_chapter_indices(item),
                "confidence": item.confidence,
            }
        )
        if len(payloads) >= limit:
            break
    return payloads


def _source_slice_payload(source_slice: ChapterSourceSlice) -> dict[str, Any]:
    return {
        "file_id": source_slice.file_id,
        "filename": source_slice.filename,
        "section_ref": source_slice.section_ref,
        "section_title": source_slice.section_title,
        "header_path": source_slice.header_path,
        "relevance": source_slice.relevance,
        "usage": source_slice.usage,
        "summary": source_slice.summary,
        "excerpt": source_slice.excerpt,
    }


def _append_preliminary_node(
    nodes: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    *,
    name: object,
    unit_type: str,
    chapter_index: int = 0,
    summary: object = "",
    source: str,
) -> None:
    initial_type = normalize_knowledge_unit_type(unit_type)
    text = _clean_preliminary_node_name(name, max_chars=72 if initial_type == "topic" else 42)
    if not text:
        return
    summary_text = str(summary or text).strip()
    normalized_type = normalize_generated_knowledge_unit_type(unit_type, name=text, summary=summary_text)
    key = (normalized_type, "".join(text.split()).casefold())
    if key in seen:
        return
    seen.add(key)
    nodes.append(
        {
            "name": text,
            "knowledge_unit_type": normalized_type,
            "knowledge_unit_type_label": knowledge_unit_type_label(normalized_type),
            "chapter_index": max(0, _safe_int(chapter_index)),
            "summary": summary_text,
            "source": source,
        }
    )


def _append_preliminary_edge(
    edges: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    *,
    source_name: object,
    target_name: object,
    edge_type: str,
    description: object = "",
    chapter_index: int = 0,
    source: str,
) -> None:
    source_text = _clean_preliminary_node_name(source_name)
    target_text = _clean_preliminary_node_name(target_name, max_chars=72)
    if not source_text or not target_text or source_text == target_text:
        return
    normalized_type = normalize_relation_type(edge_type)
    key = (
        "".join(source_text.split()).casefold(),
        "".join(target_text.split()).casefold(),
        normalized_type,
    )
    if not key[0] or not key[1] or key in seen:
        return
    seen.add(key)
    edges.append(
        {
            "source_name": source_text,
            "target_name": target_text,
            "edge_type": normalized_type,
            "edge_type_label": relation_type_label(normalized_type),
            "description": str(description or "").strip(),
            "chapter_index": max(0, _safe_int(chapter_index)),
            "source": source,
        }
    )


def _role_unit_type(role: str) -> str:
    normalized = str(role or "").strip().lower()
    return {
        "definition": "concept",
        "formula": "formula_model",
        "formula_model": "formula_model",
        "method": "procedure",
        "procedure": "procedure",
        "example": "application_case",
        "application": "application_case",
        "application_case": "application_case",
        "pitfall": "misconception",
        "misconception": "misconception",
        "exercise": "skill",
        "practice": "skill",
    }.get(normalized, normalize_knowledge_unit_type(normalized))


def _clean_preliminary_node_name(value: object, *, max_chars: int = 42) -> str:
    text = str(value or "").strip()
    text = _KG_MARKDOWN_STYLE_RE.sub("", text)
    text = re.sub(r"\{#ku_[^}]+\}", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ：:，,。；;、|-")
    if not text:
        return ""
    if len(text) > max_chars:
        for delimiter in ("；", ";", "。", "，", ","):
            head = text.split(delimiter, 1)[0].strip(" ：:，,。；;、|-")
            if 3 <= len(head) <= max_chars:
                text = head
                break
    if len(text) > max_chars:
        return ""
    return text


def _preliminary_target(value: object, *, unit_type: str) -> tuple[str, str] | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    cleaned = _clean_preliminary_node_name(raw)
    return (cleaned, unit_type) if cleaned else None


def _append_preliminary_items(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    seen_nodes: set[tuple[str, str]],
    seen_edges: set[tuple[str, str, str]],
    *,
    values: Sequence[object],
    unit_type: str,
    chapter_index: int,
    chapter_title: str,
    source: str,
) -> None:
    for value in values:
        item = _preliminary_target(value, unit_type=unit_type)
        if item is None:
            continue
        item_name, item_type = item
        if item_name:
            _append_preliminary_node(
                nodes,
                seen_nodes,
                name=item_name,
                unit_type=item_type,
                chapter_index=chapter_index,
                summary=item_name,
                source=source,
            )
            _append_preliminary_edge(
                edges,
                seen_edges,
                source_name=item_name,
                target_name=chapter_title,
                edge_type="part_of",
                description=f"{item_name} 属于《{chapter_title}》的学习内容。",
                chapter_index=chapter_index,
                source=source,
            )


def _plan_target_values(value: object, *, limit: int = 12) -> list[str]:
    targets: list[str] = []
    for item in list(value or []) if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []:
        if isinstance(item, Mapping):
            target = str(item.get("target") or item.get("knowledge_unit") or item.get("topic") or "").strip()
        else:
            target = str(item or "").strip()
        if target:
            targets.append(target)
        if len(targets) >= limit:
            break
    return clean_string_list(targets, limit=limit)


def build_preliminary_kg(
    *,
    chapters_enhanced: Sequence[Mapping[str, Any]],
    dispatch_table: Mapping[str, Any] | None = None,
    guideline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact rule-only KG seed from frozen DocGen planning artifacts."""

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[tuple[str, str]] = set()
    seen_edges: set[tuple[str, str, str]] = set()
    topic_by_index: dict[int, str] = {}
    dispatch_by_index = {
        _safe_int(item.get("chapter_index")): dict(item)
        for item in list((dispatch_table or {}).get("items") or [])
        if isinstance(item, Mapping) and _safe_int(item.get("chapter_index")) > 0
    }

    for fallback_index, chapter in enumerate(chapters_enhanced, start=1):
        chapter_index = _safe_int(chapter.get("chapter_index"))
        chapter_index = chapter_index or fallback_index
        title = str(chapter.get("title") or f"第 {chapter_index} 章").strip()
        topic_by_index[chapter_index] = title
        dispatch_item = dispatch_by_index.get(chapter_index, {})
        _append_preliminary_node(
            nodes,
            seen_nodes,
            name=title,
            unit_type="topic",
            chapter_index=chapter_index,
            summary=chapter.get("objective") or dispatch_item.get("title") or title,
            source="docgen_chapter_contract",
        )
        role_targets_raw = chapter.get("content_role_targets")
        role_targets = dict(role_targets_raw) if isinstance(role_targets_raw, Mapping) else {}
        for role, values in role_targets.items():
            _append_preliminary_items(
                nodes,
                edges,
                seen_nodes,
                seen_edges,
                values=clean_string_list(values, limit=12),
                unit_type=_role_unit_type(role),
                chapter_index=chapter_index,
                chapter_title=title,
                source="docgen_chapter_contract",
            )
        for key, unit_type in (
            ("concept_targets", "concept"),
            ("definition_targets", "concept"),
            ("formula_targets", "formula_model"),
            ("example_targets", "application_case"),
            ("pitfall_targets", "misconception"),
        ):
            chapter_values = clean_string_list(chapter.get(key), limit=12)
            dispatch_values = clean_string_list(dispatch_item.get(key), limit=12)
            _append_preliminary_items(
                nodes,
                edges,
                seen_nodes,
                seen_edges,
                values=clean_string_list([*chapter_values, *dispatch_values], limit=12),
                unit_type=unit_type,
                chapter_index=chapter_index,
                chapter_title=title,
                source="docgen_chapter_contract",
            )
        for values, unit_type in (
            (_plan_target_values(chapter.get("example_coverage_plan"), limit=12), "application_case"),
            (_plan_target_values(chapter.get("chapter_end_practice_plan"), limit=12), "skill"),
        ):
            _append_preliminary_items(
                nodes,
                edges,
                seen_nodes,
                seen_edges,
                values=values,
                unit_type=unit_type,
                chapter_index=chapter_index,
                chapter_title=title,
                source="docgen_chapter_contract",
            )

    for item in list((guideline or {}).get("canonical_glossary") or []):
        if not isinstance(item, Mapping):
            continue
        term = str(item.get("term") or "").strip()
        if not term:
            continue
        target_chapters = [_safe_int(raw) for raw in list(item.get("target_chapters") or [])]
        target_chapters = [index for index in target_chapters if index > 0]
        _append_preliminary_node(
            nodes,
            seen_nodes,
            name=term,
            unit_type=item.get("knowledge_unit_type") or "concept",
            chapter_index=target_chapters[0] if target_chapters else 0,
            summary=item.get("definition") or term,
            source="docgen_guideline",
        )
        for chapter_index in target_chapters:
            topic = topic_by_index.get(chapter_index)
            if topic:
                _append_preliminary_edge(
                    edges,
                    seen_edges,
                    source_name=term,
                    target_name=topic,
                    edge_type="part_of",
                    description=f"{term} 是《{topic}》需要统一口径的知识点。",
                    chapter_index=chapter_index,
                    source="docgen_guideline",
                )

    for item in list((guideline or {}).get("dependency_edges") or []):
        if not isinstance(item, Mapping):
            continue
        _append_preliminary_edge(
            edges,
            seen_edges,
            source_name=item.get("from") or item.get("from_concept"),
            target_name=item.get("to") or item.get("to_concept"),
            edge_type="prerequisite_for" if item.get("relation") == "chapter_order" else str(item.get("relation") or ""),
            description=item.get("reason") or "",
            chapter_index=0,
            source="docgen_guideline",
        )

    return {
        "schema_version": 1,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "taxonomy": {
            "node_type_labels": {item["knowledge_unit_type"]: item["knowledge_unit_type_label"] for item in nodes},
            "edge_type_labels": {item["edge_type"]: item["edge_type_label"] for item in edges},
        },
    }

_DOCGEN_KG_DOWNSTREAM_UNIT_TYPES = {
    "concept",
    "principle",
    "formula_model",
    "procedure",
    "skill",
    "misconception",
    "application_case",
}
_DOCGEN_KG_DIAGNOSTIC_UNIT_TYPES = {
    "skill",
    "misconception",
    "application_case",
}
_DOCGEN_KG_STRUCTURE_EDGE_TYPES = {
    "part_of",
    "prerequisite_for",
    "derives_to",
    "applies_to",
    "uses_method",
    "assesses",
    "explains",
    "remediates",
    "confuses_with",
    "extends_to",
}
_DOCGEN_KG_EXAM_EDGE_TYPES = {
    "assesses",
    "applies_to",
    "uses_method",
    "remediates",
    "confuses_with",
}
_DOCGEN_DRAFT_NODE_TYPE_PRIORITY = {
    "resource": 0,
    "concept": 10,
    "principle": 20,
    "formula_model": 30,
    "procedure": 40,
    "application_case": 50,
    "misconception": 60,
    "skill": 70,
    "topic": 80,
}


def _prefer_docgen_draft_node_type(existing: str, incoming: str) -> str:
    existing_type = normalize_knowledge_unit_type(existing)
    incoming_type = normalize_knowledge_unit_type(incoming)
    if _DOCGEN_DRAFT_NODE_TYPE_PRIORITY.get(incoming_type, 0) > _DOCGEN_DRAFT_NODE_TYPE_PRIORITY.get(existing_type, 0):
        return incoming_type
    return existing_type


def _dedupe_docgen_draft_nodes_by_name(nodes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    for item in nodes:
        if not isinstance(item, Mapping):
            continue
        node = dict(item)
        name_key = _draft_name_key(node.get("name"))
        if not name_key:
            continue
        existing = by_name.get(name_key)
        if existing is None:
            by_name[name_key] = node
            deduped.append(node)
            continue

        preferred_type = _prefer_docgen_draft_node_type(
            str(existing.get("knowledge_unit_type") or ""),
            str(node.get("knowledge_unit_type") or ""),
        )
        existing["knowledge_unit_type"] = preferred_type
        existing["knowledge_unit_type_label"] = knowledge_unit_type_label(preferred_type)

        existing_summary = str(existing.get("summary") or "").strip()
        node_summary = str(node.get("summary") or "").strip()
        if node_summary and (not existing_summary or existing_summary == str(existing.get("name") or "").strip()):
            existing["summary"] = node_summary
        if not _safe_int(existing.get("chapter_index")) and _safe_int(node.get("chapter_index")):
            existing["chapter_index"] = _safe_int(node.get("chapter_index"))
        if not str(existing.get("anchor") or "").strip() and str(node.get("anchor") or "").strip():
            existing["anchor"] = str(node.get("anchor") or "").strip()
        if not str(existing.get("quote_text") or "").strip() and str(node.get("quote_text") or "").strip():
            existing["quote_text"] = str(node.get("quote_text") or "").strip()
        existing["source_file_ids"] = clean_string_list(
            [
                *list(existing.get("source_file_ids") or []),
                *list(node.get("source_file_ids") or []),
            ],
            limit=12,
        )
    return deduped


def _append_draft_node(
    nodes: list[dict[str, Any]],
    seen: set[tuple[str, str]],
    *,
    name: object,
    unit_type: str,
    chapter_index: int = 0,
    summary: object = "",
    source: str,
    anchor: object = "",
    source_file_ids: Sequence[object] | None = None,
    quote_text: object = "",
) -> None:
    initial_type = normalize_knowledge_unit_type(unit_type)
    text = _clean_preliminary_node_name(name, max_chars=72 if initial_type == "topic" else 56)
    if not text:
        return
    summary_text = str(summary or text).strip()
    normalized_type = normalize_generated_knowledge_unit_type(unit_type, name=text, summary=summary_text)
    key = (normalized_type, "".join(text.split()).casefold())
    if key in seen:
        return
    seen.add(key)
    nodes.append(
        {
            "name": text,
            "knowledge_unit_type": normalized_type,
            "knowledge_unit_type_label": knowledge_unit_type_label(normalized_type),
            "chapter_index": max(0, _safe_int(chapter_index)),
            "summary": summary_text,
            "source": source,
            "anchor": str(anchor or "").strip(),
            "source_file_ids": clean_string_list(source_file_ids or [], limit=12),
            "quote_text": str(quote_text or "").strip(),
        }
    )


def _append_draft_edge(
    edges: list[dict[str, Any]],
    seen: set[tuple[str, str, str]],
    *,
    source_name: object,
    target_name: object,
    edge_type: str,
    description: object = "",
    chapter_index: int = 0,
    source: str,
    quote_text: object = "",
) -> None:
    source_text = _clean_preliminary_node_name(source_name, max_chars=56)
    target_text = _clean_preliminary_node_name(target_name, max_chars=72)
    if not source_text or not target_text or source_text == target_text:
        return
    normalized_type = normalize_relation_type(edge_type)
    key = (
        "".join(source_text.split()).casefold(),
        "".join(target_text.split()).casefold(),
        normalized_type,
    )
    if not key[0] or not key[1] or key in seen:
        return
    seen.add(key)
    edges.append(
        {
            "source_name": source_text,
            "target_name": target_text,
            "edge_type": normalized_type,
            "edge_type_label": relation_type_label(normalized_type),
            "description": str(description or "").strip(),
            "chapter_index": max(0, _safe_int(chapter_index)),
            "source": source,
            "quote_text": str(quote_text or "").strip(),
        }
    )


def _chapter_title(chapter: Mapping[str, Any], fallback_index: int) -> str:
    return str(chapter.get("title") or chapter.get("enhanced_title") or f"第 {fallback_index} 章").strip()


def _draft_name_key(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def _draft_has_node_name(nodes: Sequence[Mapping[str, Any]], name: object) -> bool:
    name_key = _draft_name_key(name)
    return bool(name_key) and any(_draft_name_key(node.get("name")) == name_key for node in nodes)


def _draft_node_type_by_name(nodes: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in nodes:
        name_key = _draft_name_key(node.get("name"))
        if name_key:
            result[name_key] = normalize_knowledge_unit_type(str(node.get("knowledge_unit_type") or ""))
    return result


def _expected_chapter_indices(chapters: Sequence[Mapping[str, Any]] | None) -> list[int]:
    indices: list[int] = []
    seen: set[int] = set()
    for fallback_index, chapter in enumerate(list(chapters or []), start=1):
        if not isinstance(chapter, Mapping):
            continue
        index = _safe_int(chapter.get("chapter_index")) or fallback_index
        if index <= 0 or index in seen:
            continue
        seen.add(index)
        indices.append(index)
    return sorted(indices)


def _audit_docgen_kg_draft(
    *,
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    expected_chapter_indices: Sequence[int],
    covered_chapter_indices: Sequence[int],
    repair_warning_count: int,
) -> dict[str, Any]:
    expected = {int(index) for index in expected_chapter_indices if int(index or 0) > 0}
    covered = {int(index) for index in covered_chapter_indices if int(index or 0) > 0}
    missing = sorted(expected - covered) if expected else []
    name_types: dict[str, list[str]] = {}
    for node in nodes:
        name_key = _draft_name_key(node.get("name"))
        if not name_key:
            continue
        name_types.setdefault(name_key, []).append(
            normalize_knowledge_unit_type(str(node.get("knowledge_unit_type") or ""))
        )
    known_names = set(name_types)
    connected_names: set[str] = set()
    edge_endpoint_issue_count = 0
    edge_endpoint_ambiguity_count = 0
    relation_direction_issue_count = 0
    valid_relation_edge_count = 0
    valid_structure_edge_count = 0
    valid_exam_edge_count = 0
    for edge in edges:
        source_key = _draft_name_key(edge.get("source_name"))
        target_key = _draft_name_key(edge.get("target_name"))
        if not source_key or not target_key or source_key not in known_names or target_key not in known_names:
            edge_endpoint_issue_count += 1
            continue
        source_types = name_types.get(source_key, [])
        target_types = name_types.get(target_key, [])
        if len(source_types) != 1 or len(target_types) != 1:
            edge_endpoint_ambiguity_count += 1
            continue
        edge_type = normalize_relation_type(str(edge.get("edge_type") or ""))
        if not validate_relation_direction(
            edge_type=edge_type,
            source_type=source_types[0],
            target_type=target_types[0],
        ):
            relation_direction_issue_count += 1
            continue
        connected_names.add(source_key)
        connected_names.add(target_key)
        valid_relation_edge_count += 1
        if edge_type in _DOCGEN_KG_STRUCTURE_EDGE_TYPES:
            valid_structure_edge_count += 1
        if edge_type in _DOCGEN_KG_EXAM_EDGE_TYPES:
            valid_exam_edge_count += 1

    downstream_unit_count = sum(
        1
        for node in nodes
        if normalize_knowledge_unit_type(str(node.get("knowledge_unit_type") or "")) in _DOCGEN_KG_DOWNSTREAM_UNIT_TYPES
    )
    diagnostic_unit_count = sum(
        1
        for node in nodes
        if normalize_knowledge_unit_type(str(node.get("knowledge_unit_type") or "")) in _DOCGEN_KG_DIAGNOSTIC_UNIT_TYPES
    )
    structure_edge_count = valid_structure_edge_count
    exam_edge_count = valid_exam_edge_count
    topic_count = sum(
        1
        for node in nodes
        if normalize_knowledge_unit_type(str(node.get("knowledge_unit_type") or "")) == "topic"
    )
    isolated_unit_count = sum(
        1
        for node in nodes
        if _draft_name_key(node.get("name")) not in connected_names
    )
    missing_chapter_ratio = (len(missing) / len(expected)) if expected else 0.0
    endpoint_issue_ratio = (edge_endpoint_issue_count / max(1, len(edges))) if edges else 0.0
    endpoint_ambiguity_ratio = (edge_endpoint_ambiguity_count / max(1, len(edges))) if edges else 0.0
    direction_issue_ratio = (relation_direction_issue_count / max(1, len(edges))) if edges else 0.0
    isolated_ratio = (isolated_unit_count / max(1, len(nodes))) if nodes else 0.0
    quality_score = 1.0
    quality_score -= min(0.45, missing_chapter_ratio * 0.45)
    quality_score -= min(0.25, endpoint_issue_ratio * 0.25)
    quality_score -= min(0.2, endpoint_ambiguity_ratio * 0.2)
    quality_score -= min(0.2, direction_issue_ratio * 0.2)
    quality_score -= 0.2 if nodes and downstream_unit_count == 0 else 0.0
    quality_score -= 0.08 if len(nodes) > 1 and structure_edge_count == 0 else 0.0
    quality_score -= 0.1 if len(nodes) > 1 and valid_relation_edge_count == 0 else 0.0
    quality_score -= min(0.1, isolated_ratio * 0.1)
    quality_score -= min(0.15, max(0, repair_warning_count) * 0.03)
    quality_score = round(max(0.0, min(1.0, quality_score)), 4)

    warnings: list[str] = []
    if missing:
        warnings.append("missing_chapter_coverage")
    if edge_endpoint_issue_count:
        warnings.append("edge_endpoint_issue")
    if edge_endpoint_ambiguity_count:
        warnings.append("edge_endpoint_ambiguity")
    if relation_direction_issue_count:
        warnings.append("relation_direction_issue")
    if nodes and downstream_unit_count == 0:
        warnings.append("no_downstream_learning_unit")
    if len(nodes) > 1 and structure_edge_count == 0:
        warnings.append("no_structural_learning_edge")
    if len(nodes) > 1 and valid_relation_edge_count == 0:
        warnings.append("no_relation_edge")
    if repair_warning_count:
        warnings.append("review_repair_warning")
    has_relation_shape = len(nodes) <= 1 or valid_relation_edge_count > 0
    has_examine_profile_shape = (
        downstream_unit_count > 0
        and (len(nodes) <= 1 or structure_edge_count > 0)
    )
    quality_ready = (
        bool(nodes)
        and not missing
        and edge_endpoint_issue_count == 0
        and edge_endpoint_ambiguity_count == 0
        and relation_direction_issue_count == 0
        and repair_warning_count == 0
        and has_examine_profile_shape
        and has_relation_shape
    )
    return {
        "schema_version": 1,
        "quality_status": "ready" if quality_ready else "needs_catchup",
        "quality_ready": quality_ready,
        "quality_score": quality_score,
        "warning_count": len(warnings),
        "warnings": warnings,
        "expected_chapter_count": len(expected),
        "covered_chapter_count": len(expected & covered) if expected else len(covered),
        "missing_chapter_count": len(missing),
        "missing_chapter_indices": missing,
        "downstream_unit_count": downstream_unit_count,
        "exam_ready_unit_count": downstream_unit_count,
        "profile_ready_unit_count": downstream_unit_count,
        "diagnostic_unit_count": diagnostic_unit_count,
        "topic_count": topic_count,
        "structure_edge_count": structure_edge_count,
        "exam_edge_count": exam_edge_count,
        "examine_profile_ready": has_examine_profile_shape,
        "edge_endpoint_issue_count": edge_endpoint_issue_count,
        "edge_endpoint_ambiguity_count": edge_endpoint_ambiguity_count,
        "relation_direction_issue_count": relation_direction_issue_count,
        "valid_relation_edge_count": valid_relation_edge_count,
        "isolated_unit_count": isolated_unit_count,
        "isolated_unit_ratio": round(isolated_ratio, 4),
    }


def _append_markdown_heading_nodes(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    seen_nodes: set[tuple[str, str]],
    seen_edges: set[tuple[str, str, str]],
    *,
    chapter: Mapping[str, Any],
    fallback_index: int,
    topic_source: str = "docgen_reviewed_chapter",
    heading_source: str = "docgen_reviewed_heading",
) -> None:
    del edges, seen_edges, heading_source
    chapter_index = _safe_int(chapter.get("chapter_index")) or fallback_index
    title = _chapter_title(chapter, fallback_index)
    if not _draft_has_node_name(nodes, title):
        _append_draft_node(
            nodes,
            seen_nodes,
            name=title,
            unit_type="topic",
            chapter_index=chapter_index,
            summary=chapter.get("summary") or chapter.get("summary_draft") or title,
            source=topic_source,
        )


def build_chapter_kg_refinement_item(
    *,
    reviewed: ReviewedChapterDraft,
    report: ChapterReviewReport | None = None,
    actions: Sequence[ReviewAction] | None = None,
) -> dict[str, Any]:
    """Build one chapter-level KG refinement record during content review."""

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[tuple[str, str]] = set()
    seen_edges: set[tuple[str, str, str]] = set()
    chapter_payload = reviewed.model_dump(mode="json")
    _append_markdown_heading_nodes(
        nodes,
        edges,
        seen_nodes,
        seen_edges,
        chapter=chapter_payload,
        fallback_index=reviewed.chapter_index,
        topic_source="docgen_review_refinement",
        heading_source="docgen_review_refinement",
    )
    action_payloads = [
        item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        for item in list(actions or [])
    ]
    warning_actions = [
        item
        for item in action_payloads
        if str(item.get("severity") or "").strip() in {"warning", "error"}
        and str(item.get("status") or "recorded").strip() not in {"applied", "downgraded"}
    ]
    report_payload = report.model_dump(mode="json") if report is not None else {}
    return {
        "schema_version": 1,
        "chapter_index": reviewed.chapter_index,
        "title": reviewed.title,
        "source": "docgen_review_refinement",
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "review_report_ref": reviewed.review_report_ref,
        "coverage_score": float(report_payload.get("coverage_score") or 0.0),
        "evidence_support_score": float(report_payload.get("evidence_support_score") or 0.0),
        "quality_score": float(report_payload.get("quality_score") or 0.0),
        "passed": bool(report_payload.get("passed", True)),
        "needs_repair": bool(warning_actions),
        "warnings": clean_string_list([*list(reviewed.warnings or []), *list(report_payload.get("warnings") or [])], limit=18),
        "review_action_ids": clean_string_list([item.get("action_id") for item in action_payloads], limit=24),
    }


def build_docgen_kg_draft(
    *,
    preliminary_kg: Mapping[str, Any] | None = None,
    kg_refinement_items: Sequence[Mapping[str, Any]] | None = None,
    reviewed_chapters: Sequence[Mapping[str, Any]] | None = None,
    prefetched_records: Sequence[object] | None = None,
    prefetch_metrics: Mapping[str, Any] | None = None,
    stage: str = "prepare_knowledge_graph",
) -> dict[str, Any]:
    """Build a visible DocGen KG draft before final graph persistence."""

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    seen_nodes: set[tuple[str, str]] = set()
    seen_edges: set[tuple[str, str, str]] = set()

    preliminary = dict(preliminary_kg or {})
    for item in list(preliminary.get("nodes") or []):
        if not isinstance(item, Mapping):
            continue
        _append_draft_node(
            nodes,
            seen_nodes,
            name=item.get("name"),
            unit_type=str(item.get("knowledge_unit_type") or item.get("type") or "concept"),
            chapter_index=_safe_int(item.get("chapter_index")),
            summary=item.get("summary") or item.get("name"),
            source=str(item.get("source") or "docgen_preliminary_kg"),
        )
    for item in list(preliminary.get("edges") or []):
        if not isinstance(item, Mapping):
            continue
        _append_draft_edge(
            edges,
            seen_edges,
            source_name=item.get("source_name"),
            target_name=item.get("target_name"),
            edge_type=str(item.get("edge_type") or "related_to"),
            description=item.get("description") or "",
            chapter_index=_safe_int(item.get("chapter_index")),
            source=str(item.get("source") or "docgen_preliminary_kg"),
        )

    effective_refinements = _effective_kg_refinement_items(kg_refinement_items or [])
    refinement_count = 0
    repair_warning_count = 0
    for refinement in effective_refinements:
        if not isinstance(refinement, Mapping):
            continue
        refinement_count += 1
        if bool(refinement.get("needs_repair")):
            repair_warning_count += 1
        for item in list(refinement.get("nodes") or []):
            if not isinstance(item, Mapping):
                continue
            _append_draft_node(
                nodes,
                seen_nodes,
                name=item.get("name"),
                unit_type=str(item.get("knowledge_unit_type") or item.get("type") or "concept"),
                chapter_index=_safe_int(item.get("chapter_index")) or _safe_int(refinement.get("chapter_index")),
                summary=item.get("summary") or item.get("name"),
                source=str(item.get("source") or refinement.get("source") or "docgen_review_refinement"),
                anchor=item.get("anchor") or "",
                source_file_ids=list(item.get("source_file_ids") or []),
                quote_text=item.get("quote_text") or "",
            )
        for item in list(refinement.get("edges") or []):
            if not isinstance(item, Mapping):
                continue
            _append_draft_edge(
                edges,
                seen_edges,
                source_name=item.get("source_name"),
                target_name=item.get("target_name"),
                edge_type=str(item.get("edge_type") or "related_to"),
                description=item.get("description") or "",
                chapter_index=_safe_int(item.get("chapter_index")) or _safe_int(refinement.get("chapter_index")),
                source=str(item.get("source") or refinement.get("source") or "docgen_review_refinement"),
                quote_text=item.get("quote_text") or "",
            )

    for fallback_index, chapter in enumerate(list(reviewed_chapters or []), start=1):
        if isinstance(chapter, Mapping):
            _append_markdown_heading_nodes(
                nodes,
                edges,
                seen_nodes,
                seen_edges,
                chapter=chapter,
                fallback_index=fallback_index,
            )

    payload_record_count = 0
    for record in list(prefetched_records or []):
        payload = getattr(record, "payload", None)
        if payload is None:
            continue
        payload_record_count += 1
        source_chapter_index = _safe_int(getattr(record, "source_chapter_index", 0))
        for unit in list(getattr(payload, "units", []) or []):
            _append_draft_node(
                nodes,
                seen_nodes,
                name=getattr(unit, "name", ""),
                unit_type=str(getattr(unit, "knowledge_unit_type", "concept") or "concept"),
                chapter_index=_safe_int(getattr(unit, "chapter_index", 0)) or source_chapter_index,
                summary=getattr(unit, "summary", "") or getattr(unit, "quote_text", ""),
                source="kg_prefetch_llm",
                anchor=getattr(unit, "anchor", ""),
                source_file_ids=list(getattr(unit, "source_file_ids", []) or []),
                quote_text=getattr(unit, "quote_text", ""),
            )
        for edge in list(getattr(payload, "pending_edges", []) or []):
            _append_draft_edge(
                edges,
                seen_edges,
                source_name=getattr(edge, "source_name", ""),
                target_name=getattr(edge, "target_name", ""),
                edge_type=str(getattr(edge, "edge_type", "related_to") or "related_to"),
                description=getattr(edge, "description", ""),
                chapter_index=_safe_int(getattr(edge, "chapter_index", 0)) or source_chapter_index,
                source="kg_prefetch_llm",
                quote_text=getattr(edge, "quote_text", ""),
            )

    nodes = _dedupe_docgen_draft_nodes_by_name(nodes)
    metrics = dict(prefetch_metrics or {})
    expected_chapter_indices = _expected_chapter_indices(
        [chapter for chapter in list(reviewed_chapters or []) if isinstance(chapter, Mapping)]
    )
    chapter_count = len(expected_chapter_indices)
    covered_chapter_indices = sorted(
        {
            int(item.get("chapter_index") or 0)
            for item in nodes
            if int(item.get("chapter_index") or 0) > 0
        }
    )
    expected_chapter_set = set(expected_chapter_indices)
    covered_chapter_count = (
        len(expected_chapter_set & set(covered_chapter_indices))
        if expected_chapter_set
        else len(covered_chapter_indices)
    )
    chapter_coverage_ratio = (
        round(min(1.0, covered_chapter_count / chapter_count), 4)
        if chapter_count > 0
        else 0.0
    )
    prefetch_ready = bool(int(metrics.get("prefetch_ready", 0) or 0))
    quality_audit = _audit_docgen_kg_draft(
        nodes=nodes,
        edges=edges,
        expected_chapter_indices=expected_chapter_indices,
        covered_chapter_indices=covered_chapter_indices,
        repair_warning_count=repair_warning_count,
    )
    fast_visible_ready = _docgen_kg_fast_visible_ready(
        nodes=nodes,
        edges=edges,
        quality_audit=quality_audit,
        repair_warning_count=repair_warning_count,
    )
    return {
        "schema_version": 1,
        "stage": stage,
        "status": str(metrics.get("prefetch_status") or "draft").strip() or "draft",
        "ready": prefetch_ready,
        "quality_ready": bool(quality_audit.get("quality_ready")),
        "quality_status": str(quality_audit.get("quality_status") or "needs_catchup"),
        "quality_score": float(quality_audit.get("quality_score") or 0.0),
        "fast_visible_ready": fast_visible_ready,
        "needs_post_publish_catchup": not (prefetch_ready and fast_visible_ready),
        "chapter_count": chapter_count,
        "expected_chapter_indices": expected_chapter_indices,
        "covered_chapter_count": covered_chapter_count,
        "covered_chapter_indices": covered_chapter_indices,
        "chapter_coverage_ratio": chapter_coverage_ratio,
        "review_refinement_count": refinement_count,
        "review_refinement_needs_repair_count": repair_warning_count,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "prefetch_section_count": int(metrics.get("prefetch_section_count", 0) or 0),
        "prefetch_payload_section_count": payload_record_count,
        "nodes": nodes,
        "edges": edges,
        "quality_audit": quality_audit,
        "taxonomy": {
            "node_type_labels": {item["knowledge_unit_type"]: item["knowledge_unit_type_label"] for item in nodes},
            "edge_type_labels": {item["edge_type"]: item["edge_type_label"] for item in edges},
        },
    }


def _docgen_kg_fast_visible_ready(
    *,
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    quality_audit: Mapping[str, Any],
    repair_warning_count: int,
) -> bool:
    """A lighter gate for queryable preview graphs before final KG catch-up."""

    if not nodes:
        return False
    if int(quality_audit.get("missing_chapter_count", 0) or 0) > 0:
        return False
    hard_issue_keys = (
        "edge_endpoint_issue_count",
        "edge_endpoint_ambiguity_count",
        "relation_direction_issue_count",
    )
    if any(int(quality_audit.get(key, 0) or 0) > 0 for key in hard_issue_keys):
        return False
    if int(quality_audit.get("downstream_unit_count", 0) or 0) <= 0:
        return False
    if len(nodes) > 1:
        if int(quality_audit.get("valid_relation_edge_count", 0) or 0) <= 0:
            return False
        if int(quality_audit.get("structure_edge_count", 0) or 0) <= 0:
            return False
    node_type_by_name = _draft_node_type_by_name(nodes)
    return any(
        validate_relation_direction(
            edge_type=str(edge.get("edge_type") or ""),
            source_type=node_type_by_name.get(_draft_name_key(edge.get("source_name")), ""),
            target_type=node_type_by_name.get(_draft_name_key(edge.get("target_name")), ""),
        )
        for edge in edges
    ) or len(nodes) == 1


def _effective_kg_refinement_items(refinements: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Keep the latest per-chapter refinement so repair output supersedes review output."""

    latest_by_chapter: dict[int, Mapping[str, Any]] = {}
    global_items: list[Mapping[str, Any]] = []
    for refinement in list(refinements or []):
        if not isinstance(refinement, Mapping):
            continue
        chapter_index = _safe_int(refinement.get("chapter_index"))
        if chapter_index > 0:
            latest_by_chapter[chapter_index] = refinement
        else:
            global_items.append(refinement)
    return [
        *global_items,
        *[
            latest_by_chapter[index]
            for index in sorted(latest_by_chapter)
        ],
    ]


def build_user_profile_enhanced(
    *,
    docgen_context: DocGenContext,
) -> dict[str, Any]:
    """Expose profile context as an optional prompt supplement."""

    context = dict(docgen_context.learner_profile_context or {})
    user_profile = dict(context.get("user_profile") or {})
    course_profile = dict(context.get("course_profile") or {})
    user_profile_text = str(context.get("user_profile_text") or user_profile.get("profile_text") or "").strip()
    course_profile_text = str(context.get("course_profile_text") or course_profile.get("profile_text") or "").strip()
    persisted_profile_text = merge_unique_profile_texts(
        str(context.get("profile_text") or "").strip(),
        user_profile_text,
        course_profile_text,
    )
    prompt_addendum = merge_unique_profile_texts(
        docgen_context.learner_profile_text,
        persisted_profile_text,
    )
    profile_text = prompt_addendum or persisted_profile_text
    return {
        "schema_version": 1,
        "has_profile": bool(profile_text),
        "has_user_profile": bool(user_profile_text or user_profile),
        "has_course_profile": bool(course_profile_text or course_profile),
        "profile_text": profile_text,
        "prompt_addendum": prompt_addendum,
        "user_profile_text": user_profile_text,
        "course_profile_text": course_profile_text,
        "persisted_profile_text": persisted_profile_text,
        "runtime_learner_profile_text": str(docgen_context.learner_profile_text or "").strip(),
        "user_profile": user_profile,
        "course_profile": course_profile,
    }


def build_intent_enhanced(
    *,
    intent_core: Mapping[str, Any],
    docgen_context: DocGenContext,
    chapters: Sequence[Mapping[str, Any]],
    material_profile: Mapping[str, Any] | None = None,
    source_affinity_by_chapter: Sequence[SourceAffinityByChapter] | None = None,
    high_confidence_evidence_units: Sequence[HighConfidenceEvidenceUnit] | None = None,
) -> dict[str, Any]:
    """Expose the resolved learning intent as a stable trace artifact."""

    material = dict(material_profile or {})
    evidence = list(high_confidence_evidence_units or [])
    affinity_by_index = {
        int(item.chapter_index): item
        for item in list(source_affinity_by_chapter or [])
        if int(item.chapter_index or 0) > 0
    }
    return {
        "learning_goal_text": str(intent_core.get("learning_goal_text") or docgen_context.user_prompt or "").strip(),
        "audience_profile_text": str(intent_core.get("audience_profile_text") or "").strip(),
        "content_strategy_text": str(intent_core.get("content_strategy_text") or "").strip(),
        "teaching_intent": str(intent_core.get("teaching_intent") or "").strip(),
        "learner_profile_text": docgen_context.learner_profile_text,
        "chapter_count": len(chapters),
        "source_count": _safe_int(material.get("source_count") or material.get("file_count")),
        "local_section_count": _safe_int(material.get("section_count") or docgen_context.section_count),
        "evidence_sample": _evidence_payloads(evidence, limit=8),
        "chapter_focus": [
            {
                "chapter_index": int(chapter.get("chapter_index", index) or index),
                "title": str(chapter.get("title") or chapter.get("resolved_title") or "").strip(),
                "section_refs": list(affinity_by_index.get(int(chapter.get("chapter_index", index) or index), SourceAffinityByChapter()).section_refs),
                "evidence_count": sum(
                    1
                    for item in evidence
                    if int(chapter.get("chapter_index", index) or index) in _evidence_chapter_indices(item)
                ),
            }
            for index, chapter in enumerate(chapters, start=1)
        ],
        "avoid_list": clean_string_list(intent_core.get("avoid_list"), limit=12),
        "fallback_used": bool(intent_core.get("fallback_used", False)),
    }


def build_summary_enhanced(
    *,
    file_summaries: Sequence[FileMaterialSummary],
    source_affinity_by_chapter: Sequence[SourceAffinityByChapter],
    high_confidence_evidence_units: Sequence[HighConfidenceEvidenceUnit],
) -> dict[str, Any]:
    """Aggregate material understanding into a compact document-level summary."""

    return {
        "source_count": len(file_summaries),
        "source_titles": clean_string_list([item.filename for item in file_summaries], limit=24),
        "source_summaries": [
            {
                "file_id": item.file_id,
                "filename": item.filename,
                "summary": item.summary,
                "source_quality": item.source_quality,
                "summary_mode": item.summary_mode,
            }
            for item in file_summaries[:24]
        ],
        "concepts": clean_string_list([text for item in file_summaries for text in item.concepts], limit=48),
        "definitions": clean_string_list([text for item in file_summaries for text in item.definitions], limit=32),
        "formulas": clean_string_list([text for item in file_summaries for text in item.formulas], limit=32),
        "examples": clean_string_list([text for item in file_summaries for text in item.examples], limit=32),
        "question_types": clean_string_list([text for item in file_summaries for text in item.question_types], limit=24),
        "high_confidence_evidence_count": len(high_confidence_evidence_units),
        "high_confidence_evidence": _evidence_payloads(high_confidence_evidence_units, limit=24),
        "chapter_source_affinity": [
            {
                "chapter_index": item.chapter_index,
                "file_ids": list(item.file_ids),
                "section_refs": list(item.section_refs),
                "source_slices": [_source_slice_payload(source_slice) for source_slice in item.source_slices[:12]],
            }
            for item in source_affinity_by_chapter
        ],
        "chapter_evidence_map": [
            {
                "chapter_index": item.chapter_index,
                "evidence_ids": [
                    evidence.evidence_id
                    for evidence in high_confidence_evidence_units
                    if item.chapter_index in _evidence_chapter_indices(evidence)
                ][:24],
            }
            for item in source_affinity_by_chapter
        ],
    }


def build_chapters_enhanced(
    *,
    task_seeds: Sequence[ChapterGenerationTaskSeed] | None = None,
    tasks: Sequence[ChapterGenerationTask] | None = None,
    briefs: Sequence[ChapterExecutionBrief] | None = None,
    summary_enhanced: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return the currently frozen chapter contracts in a single readable shape."""

    brief_by_index = {int(item.chapter_index): item for item in list(briefs or [])}
    evidence_map = {
        int(item.get("chapter_index", 0) or 0): clean_string_list(item.get("evidence_ids"), limit=24)
        for item in list((summary_enhanced or {}).get("chapter_evidence_map") or [])
        if isinstance(item, dict)
    }
    source_items = list(tasks or task_seeds or [])
    chapters: list[dict[str, Any]] = []
    for item in sorted(source_items, key=lambda raw: int(getattr(raw, "chapter_index", 0) or 0)):
        chapter_index = int(getattr(item, "chapter_index", 0) or 0)
        brief = brief_by_index.get(chapter_index)
        required = clean_string_list(getattr(item, "required_elements", []), limit=16)
        queries = clean_string_list(getattr(item, "retrieval_queries", []), limit=12)
        outline = clean_string_list(getattr(brief, "teaching_outline", []) if brief is not None else [], limit=8)
        chapters.append(
            {
                "chapter_index": chapter_index,
                "title": str(getattr(item, "enhanced_title", "") or getattr(item, "confirmed_title", "")).strip(),
                "objective": str(getattr(item, "objective", "") or getattr(item, "chapter_goal", "")).strip(),
                "required_elements": required,
                "keywords": clean_string_list([*required, *queries], limit=24),
                "retrieval_queries": queries,
                "source_file_ids": clean_string_list(getattr(item, "priority_file_ids", []), limit=16),
                "source_section_refs": clean_string_list(getattr(item, "priority_section_refs", []), limit=24),
                "source_slices": [_source_slice_payload(source_slice) for source_slice in list(getattr(item, "source_slices", []))[:16]],
                "evidence_ids": evidence_map.get(chapter_index, []),
                "teaching_outline": outline,
            }
        )
    return chapters


def build_guideline(
    *,
    document_backbone: DocumentBackbone,
    writing_rules: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Expose the global writing and consistency rules derived from the backbone."""

    return {
        "writing_rules": clean_string_list(writing_rules or [], limit=16),
        "canonical_glossary": [
            {
                "term": item.term,
                "definition": item.definition,
                "target_chapters": list(item.target_chapters),
            }
            for item in document_backbone.canonical_glossary
        ],
        "dependency_edges": [
            {
                "from": item.from_concept,
                "to": item.to_concept,
                "relation": item.relation,
                "reason": item.reason,
            }
            for item in document_backbone.concept_dependency_graph
        ],
        "notation_rules": [
            {
                "symbol": item.symbol,
                "meaning": item.meaning,
                "target_chapters": list(item.target_chapters),
            }
            for item in document_backbone.notation_registry
        ],
        "confusion_checks": [
            {
                "topic": item.topic,
                "contrast": item.contrast,
                "target_chapters": list(item.target_chapters),
            }
            for item in document_backbone.confusion_map
        ],
        "claim_count": len(document_backbone.canonical_claim_pool),
        "source_trust_summary": dict(document_backbone.source_trust_summary or {}),
    }


def _task_attr(task: Any, key: str, default: Any = None) -> Any:
    if isinstance(task, Mapping):
        return task.get(key, default)
    return getattr(task, key, default)


def _task_title(task: Any) -> str:
    enhanced = str(_task_attr(task, "enhanced_title", "") or "").strip()
    confirmed = str(_task_attr(task, "confirmed_title", "") or "").strip()
    return enhanced or confirmed


def _task_max_research_rounds(task: Any) -> int:
    budget_policy = _task_attr(task, "budget_policy", None)
    if isinstance(budget_policy, Mapping):
        value = budget_policy.get("max_research_rounds")
    else:
        value = getattr(budget_policy, "max_research_rounds", None)
    try:
        return max(1, int(value or 2))
    except (TypeError, ValueError):
        return 2


def build_dispatch_table(
    *,
    chapter_tasks: Sequence[Any],
    guideline: Mapping[str, Any] | None = None,
    summary_enhanced: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Summarize the final fan-out contract for chapter generation."""

    evidence_map = {
        int(item.get("chapter_index", 0) or 0): clean_string_list(item.get("evidence_ids"), limit=24)
        for item in list((summary_enhanced or {}).get("chapter_evidence_map") or [])
        if isinstance(item, dict)
    }
    glossary_terms = clean_string_list(
        [item.get("term") for item in list((guideline or {}).get("canonical_glossary") or []) if isinstance(item, dict)],
        limit=64,
    )
    return {
        "chapter_count": len(chapter_tasks),
        "global_claim_count": int((guideline or {}).get("claim_count") or 0),
        "global_glossary_terms": glossary_terms,
        "items": [
            {
                "chapter_index": _safe_int(_task_attr(task, "chapter_index")),
                "title": _task_title(task),
                "source_file_ids": clean_string_list(_task_attr(task, "priority_file_ids", []), limit=32),
                "source_section_refs": clean_string_list(_task_attr(task, "priority_section_refs", []), limit=48),
                "source_slices": [
                    _source_slice_payload(source_slice)
                    for source_slice in list(_task_attr(task, "source_slices", []) or [])[:16]
                ],
                "evidence_ids": evidence_map.get(_safe_int(_task_attr(task, "chapter_index")), []),
                "preferred_sources": clean_string_list(_task_attr(task, "preferred_sources", []), limit=32),
                "retrieval_queries": clean_string_list(_task_attr(task, "retrieval_queries", []), limit=24),
                "claim_targets": clean_string_list(_task_attr(task, "claim_targets", []), limit=24),
                "confusion_targets": clean_string_list(_task_attr(task, "confusion_targets", []), limit=24),
                "max_research_rounds": _task_max_research_rounds(task),
            }
            for task in chapter_tasks
        ],
    }


__all__ = [
    "build_chapters_enhanced",
    "build_chapter_kg_refinement_item",
    "build_dispatch_table",
    "build_docgen_kg_draft",
    "build_guideline",
    "build_intent_enhanced",
    "build_preliminary_kg",
    "build_summary_enhanced",
    "build_user_profile_enhanced",
]
