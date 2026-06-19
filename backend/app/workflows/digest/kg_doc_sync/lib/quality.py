"""Deterministic quality audit for extracted knowledge graph payloads."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.models.enums import KnowledgeUnitType
from app.models.knowledge_taxonomy import (
    is_standard_knowledge_unit_type,
    is_standard_relation_type,
    validate_relation_direction,
)
from app.workflows.digest.kg_doc_sync.lib.models import KnowledgeSyncExtractionPayload
from app.workflows.support.exam_pool_policy import (
    exam_ready_units_per_chapter_floor,
    exam_readiness_candidate_target,
)


_DOWNSTREAM_UNIT_TYPES = {
    KnowledgeUnitType.CONCEPT.value,
    KnowledgeUnitType.PRINCIPLE.value,
    KnowledgeUnitType.FORMULA_MODEL.value,
    KnowledgeUnitType.PROCEDURE.value,
    KnowledgeUnitType.SKILL.value,
    KnowledgeUnitType.MISCONCEPTION.value,
}
_DIAGNOSTIC_UNIT_TYPES = {
    KnowledgeUnitType.SKILL.value,
    KnowledgeUnitType.MISCONCEPTION.value,
    KnowledgeUnitType.APPLICATION_CASE.value,
}
_EXAM_READY_UNIT_TYPES = _DOWNSTREAM_UNIT_TYPES | {
    KnowledgeUnitType.APPLICATION_CASE.value,
}
_STRUCTURE_EDGE_TYPES = {
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
_EXAM_EDGE_TYPES = {
    "assesses",
    "applies_to",
    "uses_method",
    "remediates",
    "confuses_with",
}


def _mapping_list(value: object) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)]


def _expected_chapter_indices(structured_context: dict[str, Any]) -> set[int]:
    indices: set[int] = set()
    candidates = [
        structured_context.get("chapters"),
        dict(structured_context.get("docgen_manifest") or {}).get("chapters_enhanced"),
        dict(structured_context.get("docgen_manifest") or {}).get("chapter_tasks"),
        dict(structured_context.get("document_summary_json") or {}).get("chapters"),
    ]
    for items in candidates:
        for item in _mapping_list(items):
            index = int(item.get("chapter_index", 0) or 0)
            if index > 0:
                indices.add(index)
    return indices


def _chapter_count_for_exam_readiness(
    *,
    expected_chapters: set[int],
    covered_chapters: set[int],
) -> int:
    return max(len(expected_chapters), len(covered_chapters), 0)


def audit_knowledge_sync_payload(
    payload: KnowledgeSyncExtractionPayload,
    *,
    structured_context: dict[str, Any] | None = None,
) -> KnowledgeSyncExtractionPayload:
    """Attach graph quality metrics before DB persistence.

    The audit is intentionally deterministic: it checks taxonomy validity,
    edge endpoint integrity, relation direction and chapter coverage without
    inventing or deleting graph items.
    """

    units = list(payload.units)
    edges = list(payload.extracted_edges)
    unit_by_anchor = {unit.anchor: unit for unit in units if unit.anchor}
    expected_chapters = _expected_chapter_indices(dict(structured_context or {}))
    covered_chapters = {int(unit.chapter_index or 0) for unit in units if int(unit.chapter_index or 0) > 0}
    edge_endpoint_issue_count = 0
    relation_direction_issue_count = 0
    nonstandard_edge_type_count = 0
    valid_relation_edge_count = 0
    structure_edge_count = 0
    exam_edge_count = 0
    for edge in edges:
        source = unit_by_anchor.get(edge.source_anchor)
        target = unit_by_anchor.get(edge.target_anchor)
        if source is None or target is None:
            edge_endpoint_issue_count += 1
            continue
        if not is_standard_relation_type(edge.edge_type):
            nonstandard_edge_type_count += 1
            continue
        if not validate_relation_direction(
            edge_type=edge.edge_type,
            source_type=source.knowledge_unit_type,
            target_type=target.knowledge_unit_type,
        ):
            relation_direction_issue_count += 1
            continue
        valid_relation_edge_count += 1
        if edge.edge_type in _STRUCTURE_EDGE_TYPES:
            structure_edge_count += 1
        if edge.edge_type in _EXAM_EDGE_TYPES:
            exam_edge_count += 1

    nonstandard_unit_type_count = sum(
        1 for unit in units if not is_standard_knowledge_unit_type(unit.knowledge_unit_type)
    )
    downstream_unit_count = sum(
        1 for unit in units if unit.knowledge_unit_type in _DOWNSTREAM_UNIT_TYPES
    )
    exam_ready_unit_count = sum(
        1 for unit in units if unit.knowledge_unit_type in _EXAM_READY_UNIT_TYPES
    )
    diagnostic_unit_count = sum(
        1 for unit in units if unit.knowledge_unit_type in _DIAGNOSTIC_UNIT_TYPES
    )
    examine_profile_ready = (
        downstream_unit_count > 0
        and (len(units) <= 1 or structure_edge_count > 0)
    )
    missing_chapter_count = len(expected_chapters - covered_chapters) if expected_chapters else 0
    chapter_coverage_pct = (
        round((len(expected_chapters & covered_chapters) * 100 / len(expected_chapters)), 2)
        if expected_chapters
        else 100.0
    )
    exam_readiness_chapter_count = _chapter_count_for_exam_readiness(
        expected_chapters=expected_chapters,
        covered_chapters=covered_chapters,
    )
    exam_ready_target_count = exam_readiness_candidate_target(exam_readiness_chapter_count)
    exam_ready_gap_count = max(0, exam_ready_target_count - exam_ready_unit_count)
    exam_ready_chapter_floor = exam_ready_units_per_chapter_floor(exam_readiness_chapter_count)
    chapter_exam_ready_counts: dict[int, int] = {
        chapter_index: 0 for chapter_index in (expected_chapters or covered_chapters)
    }
    for unit in units:
        if unit.knowledge_unit_type not in _EXAM_READY_UNIT_TYPES:
            continue
        chapter_index = int(unit.chapter_index or 0)
        if chapter_index <= 0:
            continue
        chapter_exam_ready_counts[chapter_index] = chapter_exam_ready_counts.get(chapter_index, 0) + 1
    exam_ready_low_chapter_count = (
        sum(1 for count in chapter_exam_ready_counts.values() if count < exam_ready_chapter_floor)
        if exam_ready_chapter_floor
        else 0
    )
    quality_warning_count = sum(
        1
        for value in [
            nonstandard_unit_type_count,
            nonstandard_edge_type_count,
            edge_endpoint_issue_count,
            relation_direction_issue_count,
            missing_chapter_count,
            0 if exam_ready_unit_count else 1 if units else 0,
        ]
        if value
    )
    diagnostics = dict(payload.diagnostics_totals or {})
    diagnostics.update(
        {
            "graph_audit_unit_count": len(units),
            "graph_audit_edge_count": len(edges),
            "graph_audit_downstream_unit_count": downstream_unit_count,
            "graph_audit_exam_ready_unit_count": exam_ready_unit_count,
            "graph_audit_exam_ready_target_count": exam_ready_target_count,
            "graph_audit_exam_ready_gap_count": exam_ready_gap_count,
            "graph_audit_exam_ready_chapter_floor": exam_ready_chapter_floor,
            "graph_audit_exam_ready_low_chapter_count": exam_ready_low_chapter_count,
            "graph_audit_profile_ready_unit_count": downstream_unit_count,
            "graph_audit_diagnostic_unit_count": diagnostic_unit_count,
            "graph_audit_valid_relation_edge_count": valid_relation_edge_count,
            "graph_audit_structure_edge_count": structure_edge_count,
            "graph_audit_exam_edge_count": exam_edge_count,
            "graph_audit_examine_profile_ready": 1 if examine_profile_ready else 0,
            "graph_audit_expected_chapter_count": len(expected_chapters),
            "graph_audit_covered_chapter_count": len(expected_chapters & covered_chapters) if expected_chapters else len(covered_chapters),
            "graph_audit_missing_chapter_count": missing_chapter_count,
            "graph_audit_chapter_coverage_pct": chapter_coverage_pct,
            "graph_audit_nonstandard_unit_type_count": nonstandard_unit_type_count,
            "graph_audit_nonstandard_edge_type_count": nonstandard_edge_type_count,
            "graph_audit_edge_endpoint_issue_count": edge_endpoint_issue_count,
            "graph_audit_relation_direction_issue_count": relation_direction_issue_count,
            "graph_audit_warning_count": quality_warning_count,
        }
    )
    return replace(payload, diagnostics_totals=diagnostics)


__all__ = ["audit_knowledge_sync_payload"]
