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
    normalize_knowledge_unit_type,
    normalize_relation_type,
    relation_type_label,
)
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    ChapterSourceSlice,
    DocGenContext,
    DocumentBackbone,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    SourceAffinityByChapter,
    clean_string_list,
)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


_KG_ROLE_LABEL_RE = re.compile(
    r"^\s*(?P<label>学习目标|目标|核心概念|知识点|典型例题|例题|易错点|易错提醒|课后练习|练习)\s*[:：]\s*"
)
_KG_ITEM_SPLIT_RE = re.compile(r"[、,，;；]\s*")
_KG_ACTION_PREFIX_RE = re.compile(
    r"^\s*(?:熟练)?(?:掌握|理解|重建|建立|学会|会用|能够|能|提升|复习|巩固|完成|明确|识别|判断|训练)\s*"
)
_KG_ACTION_ONLY_RE = re.compile(r"^(?:提升|复习|巩固|完成|明确|训练|形成|减少|避免|帮助|便于)")
_KG_NOISE_NODE_RE = re.compile(r"^(?:学习目标|目标|核心概念|知识点|典型例题|例题|易错点|易错提醒|课后练习|练习)$")
_KG_ROLE_LABEL_TYPES = {
    "核心概念": "concept",
    "知识点": "concept",
    "典型例题": "application_case",
    "例题": "application_case",
    "易错点": "misconception",
    "易错提醒": "misconception",
    "课后练习": "skill",
    "练习": "skill",
}


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
    normalized_type = normalize_knowledge_unit_type(unit_type)
    text = _clean_preliminary_node_name(name, max_chars=72 if normalized_type == "topic" else 42)
    if not text:
        return
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
            "summary": str(summary or text).strip(),
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
    text = _KG_ROLE_LABEL_RE.sub("", text, count=1)
    text = re.sub(r"\s+", " ", text).strip(" ：:，,。；;、|-")
    text = re.sub(r"^(?:本章|本节|这一章|这部分)\s*", "", text).strip(" ：:，,。；;、|-")
    if not text or _KG_NOISE_NODE_RE.fullmatch(text) or _KG_ACTION_ONLY_RE.match(text):
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


def _preliminary_items(value: object, *, unit_type: str) -> list[tuple[str, str]]:
    raw = str(value or "").strip()
    if not raw:
        return []
    label_type = ""
    match = _KG_ROLE_LABEL_RE.match(raw)
    if match is not None:
        label = match.group("label")
        raw = raw[match.end():].strip()
        label_type = _KG_ROLE_LABEL_TYPES.get(label, "")
    effective_type = label_type or unit_type
    normalized: list[tuple[str, str]] = []
    for part in _KG_ITEM_SPLIT_RE.split(raw):
        if _KG_ACTION_ONLY_RE.match(part.strip()):
            continue
        cleaned = _clean_preliminary_node_name(_KG_ACTION_PREFIX_RE.sub("", part, count=1))
        if cleaned:
            normalized.append((cleaned, effective_type))
    if normalized:
        return normalized[:8]
    cleaned = _clean_preliminary_node_name(_KG_ACTION_PREFIX_RE.sub("", raw, count=1))
    return [(cleaned, effective_type)] if cleaned else []


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
        for item_name, item_type in _preliminary_items(value, unit_type=unit_type):
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
            ("required_elements", "concept"),
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


def build_user_profile_enhanced(
    *,
    docgen_context: DocGenContext,
) -> dict[str, Any]:
    """Expose profile context as an optional prompt supplement."""

    context = dict(docgen_context.learner_profile_context or {})
    profile_text = str(context.get("profile_text") or docgen_context.learner_profile_text or "").strip()
    return {
        "schema_version": 1,
        "has_profile": bool(profile_text),
        "profile_text": profile_text,
        "prompt_addendum": profile_text,
        "user_profile": dict(context.get("user_profile") or {}),
        "course_profile": dict(context.get("course_profile") or {}),
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


def build_dispatch_table(
    *,
    chapter_tasks: Sequence[ChapterGenerationTask],
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
                "chapter_index": task.chapter_index,
                "title": task.enhanced_title or task.confirmed_title,
                "source_file_ids": list(task.priority_file_ids),
                "source_section_refs": list(task.priority_section_refs),
                "source_slices": [_source_slice_payload(source_slice) for source_slice in task.source_slices[:16]],
                "evidence_ids": evidence_map.get(task.chapter_index, []),
                "preferred_sources": list(task.preferred_sources),
                "retrieval_queries": list(task.retrieval_queries),
                "claim_targets": list(task.claim_targets),
                "confusion_targets": list(task.confusion_targets),
                "max_research_rounds": task.budget_policy.max_research_rounds,
            }
            for task in chapter_tasks
        ],
    }


__all__ = [
    "build_chapters_enhanced",
    "build_dispatch_table",
    "build_guideline",
    "build_intent_enhanced",
    "build_preliminary_kg",
    "build_summary_enhanced",
    "build_user_profile_enhanced",
]
