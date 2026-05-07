"""Knowledge graph type helpers for persisted graph models."""

from __future__ import annotations

from app.models.enums import KnowledgeRelationType, KnowledgeUnitType, KnowledgeUnitTypeSource

STANDARD_KNOWLEDGE_UNIT_TYPES = {item.value for item in KnowledgeUnitType}
STANDARD_RELATION_TYPES = {item.value for item in KnowledgeRelationType}
STANDARD_TYPE_SOURCES = {item.value for item in KnowledgeUnitTypeSource}

LEGACY_KNOWLEDGE_UNIT_TYPE_MAP: dict[str, str] = {
    "concept": KnowledgeUnitType.CORE_KNOWLEDGE.value,
    "definition": KnowledgeUnitType.CORE_KNOWLEDGE.value,
    "theorem": KnowledgeUnitType.CORE_KNOWLEDGE.value,
    "formula": KnowledgeUnitType.CORE_KNOWLEDGE.value,
    "method": KnowledgeUnitType.METHOD_DEMO.value,
    "example": KnowledgeUnitType.METHOD_DEMO.value,
    "exercise": KnowledgeUnitType.PRACTICE_ASSESSMENT.value,
    "proof_step": KnowledgeUnitType.PRINCIPLE_REASONING.value,
    "remark": KnowledgeUnitType.EXPLANATION_SUPPORT.value,
}
LEGACY_RELATION_TYPE_MAP: dict[str, str] = {
    "derivation": KnowledgeRelationType.REASONING.value,
    "example_of": KnowledgeRelationType.TRAINING.value,
    "support": KnowledgeRelationType.EXPLANATION.value,
    "related": KnowledgeRelationType.APPLICATION.value,
    "concept": KnowledgeRelationType.CONTAINS.value,
    "definition": KnowledgeRelationType.CONTAINS.value,
    "theorem": KnowledgeRelationType.CONTAINS.value,
    "formula": KnowledgeRelationType.CONTAINS.value,
    "method": KnowledgeRelationType.APPLICATION.value,
    "example": KnowledgeRelationType.APPLICATION.value,
    "exercise": KnowledgeRelationType.TRAINING.value,
    "proof_step": KnowledgeRelationType.REASONING.value,
    "remark": KnowledgeRelationType.EXPLANATION.value,
    "core_knowledge": KnowledgeRelationType.CONTAINS.value,
    "method_demo": KnowledgeRelationType.APPLICATION.value,
    "explanation_support": KnowledgeRelationType.EXPLANATION.value,
    "principle_reasoning": KnowledgeRelationType.REASONING.value,
    "practice_assessment": KnowledgeRelationType.TRAINING.value,
    "knowledge_organization": KnowledgeRelationType.CONTAINS.value,
    "application_extension": KnowledgeRelationType.APPLICATION.value,
}

PRIMARY_KNOWLEDGE_UNIT_TYPES = {
    KnowledgeUnitType.CORE_KNOWLEDGE.value,
    KnowledgeUnitType.METHOD_DEMO.value,
    KnowledgeUnitType.PRINCIPLE_REASONING.value,
    KnowledgeUnitType.KNOWLEDGE_ORGANIZATION.value,
    KnowledgeUnitType.APPLICATION_EXTENSION.value,
}
SECONDARY_KNOWLEDGE_UNIT_TYPES = {
    KnowledgeUnitType.EXPLANATION_SUPPORT.value,
    KnowledgeUnitType.PRACTICE_ASSESSMENT.value,
}
PARENT_KNOWLEDGE_UNIT_TYPES = PRIMARY_KNOWLEDGE_UNIT_TYPES

_ALLOWED_SOURCE_TYPES_BY_RELATION = {
    KnowledgeRelationType.PREREQUISITE.value: {
        KnowledgeUnitType.CORE_KNOWLEDGE.value,
        KnowledgeUnitType.METHOD_DEMO.value,
        KnowledgeUnitType.PRINCIPLE_REASONING.value,
        KnowledgeUnitType.KNOWLEDGE_ORGANIZATION.value,
    },
    KnowledgeRelationType.REASONING.value: {
        KnowledgeUnitType.CORE_KNOWLEDGE.value,
        KnowledgeUnitType.METHOD_DEMO.value,
        KnowledgeUnitType.PRINCIPLE_REASONING.value,
        KnowledgeUnitType.EXPLANATION_SUPPORT.value,
    },
    KnowledgeRelationType.APPLICATION.value: {
        KnowledgeUnitType.CORE_KNOWLEDGE.value,
        KnowledgeUnitType.METHOD_DEMO.value,
        KnowledgeUnitType.PRINCIPLE_REASONING.value,
        KnowledgeUnitType.APPLICATION_EXTENSION.value,
    },
    KnowledgeRelationType.EXPLANATION.value: PRIMARY_KNOWLEDGE_UNIT_TYPES,
    KnowledgeRelationType.TRAINING.value: {
        KnowledgeUnitType.CORE_KNOWLEDGE.value,
        KnowledgeUnitType.METHOD_DEMO.value,
        KnowledgeUnitType.PRINCIPLE_REASONING.value,
        KnowledgeUnitType.APPLICATION_EXTENSION.value,
    },
}
_ALLOWED_TARGET_TYPES_BY_RELATION = {
    KnowledgeRelationType.EXPLANATION.value: {KnowledgeUnitType.EXPLANATION_SUPPORT.value},
    KnowledgeRelationType.TRAINING.value: {KnowledgeUnitType.PRACTICE_ASSESSMENT.value},
    KnowledgeRelationType.APPLICATION.value: {
        KnowledgeUnitType.APPLICATION_EXTENSION.value,
        KnowledgeUnitType.PRACTICE_ASSESSMENT.value,
        KnowledgeUnitType.METHOD_DEMO.value,
        KnowledgeUnitType.CORE_KNOWLEDGE.value,
    },
}


def normalize_knowledge_unit_type(
    raw_type: str | None,
    *,
    default: str = KnowledgeUnitType.CORE_KNOWLEDGE.value,
) -> str:
    normalized = str(raw_type or "").strip().lower()
    if normalized in STANDARD_KNOWLEDGE_UNIT_TYPES:
        return normalized
    return LEGACY_KNOWLEDGE_UNIT_TYPE_MAP.get(normalized, default)


def normalize_type_source(raw_source: str | None, *, default: str = KnowledgeUnitTypeSource.LLM.value) -> str:
    normalized = str(raw_source or "").strip().lower()
    return normalized if normalized in STANDARD_TYPE_SOURCES else default


def normalize_relation_type(raw_type: str | None) -> str:
    normalized = str(raw_type or "").strip().lower()
    if normalized in STANDARD_RELATION_TYPES:
        return normalized
    return LEGACY_RELATION_TYPE_MAP.get(normalized, KnowledgeRelationType.APPLICATION.value)


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
    allowed_target_types = _ALLOWED_TARGET_TYPES_BY_RELATION.get(relation)
    if allowed_target_types is not None and target not in allowed_target_types:
        return False
    return source in STANDARD_KNOWLEDGE_UNIT_TYPES and target in STANDARD_KNOWLEDGE_UNIT_TYPES


__all__ = [
    "LEGACY_KNOWLEDGE_UNIT_TYPE_MAP",
    "LEGACY_RELATION_TYPE_MAP",
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
