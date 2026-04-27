"""Knowledge graph type helpers for persisted graph models."""

from __future__ import annotations

from app.models.enums import KnowledgeRelationType, KnowledgeUnitType, KnowledgeUnitTypeSource

STANDARD_KNOWLEDGE_UNIT_TYPES = {item.value for item in KnowledgeUnitType}
STANDARD_RELATION_TYPES = {item.value for item in KnowledgeRelationType}
STANDARD_TYPE_SOURCES = {item.value for item in KnowledgeUnitTypeSource}

PRIMARY_KNOWLEDGE_UNIT_TYPES = {
    KnowledgeUnitType.CONCEPT.value,
    KnowledgeUnitType.THEOREM.value,
    KnowledgeUnitType.FORMULA.value,
    KnowledgeUnitType.EXERCISE.value,
    KnowledgeUnitType.METHOD.value,
    KnowledgeUnitType.PROOF_STEP.value,
    KnowledgeUnitType.REMARK.value,
}
SECONDARY_KNOWLEDGE_UNIT_TYPES = {
    KnowledgeUnitType.DEFINITION.value,
    KnowledgeUnitType.EXAMPLE.value,
}
PARENT_KNOWLEDGE_UNIT_TYPES = PRIMARY_KNOWLEDGE_UNIT_TYPES | {KnowledgeUnitType.DEFINITION.value}

_BLOCKED_ENDPOINT_TYPES_BY_RELATION = {
    KnowledgeRelationType.PREREQUISITE.value: {KnowledgeUnitType.EXAMPLE.value},
    KnowledgeRelationType.SIMILAR.value: {KnowledgeUnitType.EXAMPLE.value},
    KnowledgeRelationType.CONTRAST.value: {KnowledgeUnitType.EXAMPLE.value},
}
_ALLOWED_SOURCE_TYPES_BY_RELATION = {
    KnowledgeRelationType.EXAMPLE_OF.value: {
        KnowledgeUnitType.EXAMPLE.value,
        KnowledgeUnitType.EXERCISE.value,
    },
}


def normalize_knowledge_unit_type(raw_type: str | None, *, default: str = KnowledgeUnitType.CONCEPT.value) -> str:
    normalized = str(raw_type or "").strip()
    return normalized if normalized in STANDARD_KNOWLEDGE_UNIT_TYPES else default


def normalize_type_source(raw_source: str | None, *, default: str = KnowledgeUnitTypeSource.LLM.value) -> str:
    normalized = str(raw_source or "").strip().lower()
    return normalized if normalized in STANDARD_TYPE_SOURCES else default


def normalize_relation_type(raw_type: str | None) -> str:
    normalized = str(raw_type or "").strip()
    return normalized if normalized in STANDARD_RELATION_TYPES else KnowledgeRelationType.APPLICATION.value


def is_standard_knowledge_unit_type(unit_type: str | None) -> bool:
    return str(unit_type or "") in STANDARD_KNOWLEDGE_UNIT_TYPES


def is_standard_relation_type(edge_type: str | None) -> bool:
    return str(edge_type or "") in STANDARD_RELATION_TYPES


def validate_relation_direction(
    *,
    edge_type: str,
    source_type: str | None,
    target_type: str | None,
) -> bool:
    source = normalize_knowledge_unit_type(source_type)
    target = normalize_knowledge_unit_type(target_type)
    relation = normalize_relation_type(edge_type)
    allowed_source_types = _ALLOWED_SOURCE_TYPES_BY_RELATION.get(relation)
    if allowed_source_types is not None and source not in allowed_source_types:
        return False
    blocked_endpoint_types = _BLOCKED_ENDPOINT_TYPES_BY_RELATION.get(relation, set())
    return source not in blocked_endpoint_types and target not in blocked_endpoint_types


__all__ = [
    "PARENT_KNOWLEDGE_UNIT_TYPES",
    "PRIMARY_KNOWLEDGE_UNIT_TYPES",
    "SECONDARY_KNOWLEDGE_UNIT_TYPES",
    "STANDARD_KNOWLEDGE_UNIT_TYPES",
    "STANDARD_RELATION_TYPES",
    "STANDARD_TYPE_SOURCES",
    "is_standard_knowledge_unit_type",
    "is_standard_relation_type",
    "normalize_knowledge_unit_type",
    "normalize_relation_type",
    "normalize_type_source",
    "validate_relation_direction",
]
