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


_DOWNSTREAM_UNIT_TYPES = {
    KnowledgeUnitType.CONCEPT.value,
    KnowledgeUnitType.PRINCIPLE.value,
    KnowledgeUnitType.FORMULA_MODEL.value,
    KnowledgeUnitType.PROCEDURE.value,
    KnowledgeUnitType.SKILL.value,
    KnowledgeUnitType.MISCONCEPTION.value,
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

    nonstandard_unit_type_count = sum(
        1 for unit in units if not is_standard_knowledge_unit_type(unit.knowledge_unit_type)
    )
    downstream_unit_count = sum(
        1 for unit in units if unit.knowledge_unit_type in _DOWNSTREAM_UNIT_TYPES
    )
    missing_chapter_count = len(expected_chapters - covered_chapters) if expected_chapters else 0
    chapter_coverage_pct = (
        round((len(expected_chapters & covered_chapters) * 100 / len(expected_chapters)), 2)
        if expected_chapters
        else 100.0
    )
    quality_warning_count = sum(
        1
        for value in [
            nonstandard_unit_type_count,
            nonstandard_edge_type_count,
            edge_endpoint_issue_count,
            relation_direction_issue_count,
            missing_chapter_count,
            0 if downstream_unit_count else 1 if units else 0,
        ]
        if value
    )
    diagnostics = dict(payload.diagnostics_totals or {})
    diagnostics.update(
        {
            "graph_audit_unit_count": len(units),
            "graph_audit_edge_count": len(edges),
            "graph_audit_downstream_unit_count": downstream_unit_count,
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
