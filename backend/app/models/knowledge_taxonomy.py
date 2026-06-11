"""Knowledge graph type helpers for persisted graph models."""

from __future__ import annotations

from app.models.enums import KnowledgeRelationType, KnowledgeUnitType, KnowledgeUnitTypeSource

STANDARD_KNOWLEDGE_UNIT_TYPES = {item.value for item in KnowledgeUnitType}
STANDARD_RELATION_TYPES = {item.value for item in KnowledgeRelationType}
STANDARD_TYPE_SOURCES = {item.value for item in KnowledgeUnitTypeSource}

KNOWLEDGE_UNIT_TYPE_LABELS: dict[str, str] = {
    KnowledgeUnitType.TOPIC.value: "主题模块",
    KnowledgeUnitType.CONCEPT.value: "概念术语",
    KnowledgeUnitType.PRINCIPLE.value: "原理性质",
    KnowledgeUnitType.FORMULA_MODEL.value: "公式模型",
    KnowledgeUnitType.PROCEDURE.value: "方法步骤",
    KnowledgeUnitType.SKILL.value: "解题技能",
    KnowledgeUnitType.MISCONCEPTION.value: "易错辨析",
    KnowledgeUnitType.APPLICATION_CASE.value: "应用案例",
    KnowledgeUnitType.RESOURCE.value: "学习资源",
}

KNOWLEDGE_RELATION_TYPE_LABELS: dict[str, str] = {
    KnowledgeRelationType.PART_OF.value: "归属",
    KnowledgeRelationType.PREREQUISITE_FOR.value: "前置",
    KnowledgeRelationType.DERIVES_TO.value: "推导",
    KnowledgeRelationType.APPLIES_TO.value: "应用",
    KnowledgeRelationType.USES_METHOD.value: "用方法",
    KnowledgeRelationType.ASSESSES.value: "考察",
    KnowledgeRelationType.EXPLAINS.value: "解释",
    KnowledgeRelationType.REMEDIATES.value: "补救",
    KnowledgeRelationType.CONFUSES_WITH.value: "易混",
    KnowledgeRelationType.SIMILAR_TO.value: "相似",
    KnowledgeRelationType.EXTENDS_TO.value: "拓展",
}

LEGACY_KNOWLEDGE_UNIT_TYPE_MAP: dict[str, str] = {
    "core_knowledge": KnowledgeUnitType.CONCEPT.value,
    "method_demo": KnowledgeUnitType.PROCEDURE.value,
    "explanation_support": KnowledgeUnitType.RESOURCE.value,
    "principle_reasoning": KnowledgeUnitType.PRINCIPLE.value,
    "practice_assessment": KnowledgeUnitType.SKILL.value,
    "knowledge_organization": KnowledgeUnitType.TOPIC.value,
    "application_extension": KnowledgeUnitType.APPLICATION_CASE.value,
    "definition": KnowledgeUnitType.CONCEPT.value,
    "theorem": KnowledgeUnitType.PRINCIPLE.value,
    "formula": KnowledgeUnitType.FORMULA_MODEL.value,
    "method": KnowledgeUnitType.PROCEDURE.value,
    "example": KnowledgeUnitType.APPLICATION_CASE.value,
    "exercise": KnowledgeUnitType.SKILL.value,
    "proof_step": KnowledgeUnitType.PRINCIPLE.value,
    "remark": KnowledgeUnitType.RESOURCE.value,
}
LEGACY_RELATION_TYPE_MAP: dict[str, str] = {
    "prerequisite": KnowledgeRelationType.PREREQUISITE_FOR.value,
    "contains": KnowledgeRelationType.PART_OF.value,
    "reasoning": KnowledgeRelationType.DERIVES_TO.value,
    "application": KnowledgeRelationType.APPLIES_TO.value,
    "explanation": KnowledgeRelationType.EXPLAINS.value,
    "training": KnowledgeRelationType.ASSESSES.value,
    "similar": KnowledgeRelationType.SIMILAR_TO.value,
    "contrast": KnowledgeRelationType.CONFUSES_WITH.value,
    "derivation": KnowledgeRelationType.DERIVES_TO.value,
    "example_of": KnowledgeRelationType.APPLIES_TO.value,
    "support": KnowledgeRelationType.EXPLAINS.value,
    "related": KnowledgeRelationType.APPLIES_TO.value,
    "concept": KnowledgeRelationType.PART_OF.value,
    "definition": KnowledgeRelationType.PART_OF.value,
    "theorem": KnowledgeRelationType.DERIVES_TO.value,
    "formula": KnowledgeRelationType.DERIVES_TO.value,
    "method": KnowledgeRelationType.USES_METHOD.value,
    "example": KnowledgeRelationType.APPLIES_TO.value,
    "exercise": KnowledgeRelationType.ASSESSES.value,
    "proof_step": KnowledgeRelationType.DERIVES_TO.value,
    "remark": KnowledgeRelationType.EXPLAINS.value,
    "core_knowledge": KnowledgeRelationType.PART_OF.value,
    "method_demo": KnowledgeRelationType.USES_METHOD.value,
    "explanation_support": KnowledgeRelationType.EXPLAINS.value,
    "principle_reasoning": KnowledgeRelationType.DERIVES_TO.value,
    "practice_assessment": KnowledgeRelationType.ASSESSES.value,
    "knowledge_organization": KnowledgeRelationType.PART_OF.value,
    "application_extension": KnowledgeRelationType.APPLIES_TO.value,
}

PRIMARY_KNOWLEDGE_UNIT_TYPES = {
    KnowledgeUnitType.CONCEPT.value,
    KnowledgeUnitType.PRINCIPLE.value,
    KnowledgeUnitType.FORMULA_MODEL.value,
    KnowledgeUnitType.PROCEDURE.value,
    KnowledgeUnitType.SKILL.value,
    KnowledgeUnitType.MISCONCEPTION.value,
    KnowledgeUnitType.APPLICATION_CASE.value,
}
SECONDARY_KNOWLEDGE_UNIT_TYPES = {
    KnowledgeUnitType.TOPIC.value,
    KnowledgeUnitType.RESOURCE.value,
}
PARENT_KNOWLEDGE_UNIT_TYPES = {
    KnowledgeUnitType.TOPIC.value,
    KnowledgeUnitType.CONCEPT.value,
    KnowledgeUnitType.PRINCIPLE.value,
    KnowledgeUnitType.FORMULA_MODEL.value,
    KnowledgeUnitType.PROCEDURE.value,
}

_ALLOWED_SOURCE_TYPES_BY_RELATION = {
    KnowledgeRelationType.PART_OF.value: STANDARD_KNOWLEDGE_UNIT_TYPES,
    KnowledgeRelationType.PREREQUISITE_FOR.value: PRIMARY_KNOWLEDGE_UNIT_TYPES,
    KnowledgeRelationType.DERIVES_TO.value: {
        KnowledgeUnitType.CONCEPT.value,
        KnowledgeUnitType.PRINCIPLE.value,
        KnowledgeUnitType.FORMULA_MODEL.value,
        KnowledgeUnitType.PROCEDURE.value,
    },
    KnowledgeRelationType.APPLIES_TO.value: {
        KnowledgeUnitType.CONCEPT.value,
        KnowledgeUnitType.PRINCIPLE.value,
        KnowledgeUnitType.FORMULA_MODEL.value,
        KnowledgeUnitType.PROCEDURE.value,
        KnowledgeUnitType.SKILL.value,
    },
    KnowledgeRelationType.USES_METHOD.value: {
        KnowledgeUnitType.CONCEPT.value,
        KnowledgeUnitType.PRINCIPLE.value,
        KnowledgeUnitType.FORMULA_MODEL.value,
        KnowledgeUnitType.SKILL.value,
        KnowledgeUnitType.APPLICATION_CASE.value,
    },
    KnowledgeRelationType.ASSESSES.value: {
        KnowledgeUnitType.PROCEDURE.value,
        KnowledgeUnitType.SKILL.value,
        KnowledgeUnitType.APPLICATION_CASE.value,
    },
    KnowledgeRelationType.EXPLAINS.value: {
        KnowledgeUnitType.RESOURCE.value,
        KnowledgeUnitType.APPLICATION_CASE.value,
        KnowledgeUnitType.PROCEDURE.value,
    },
    KnowledgeRelationType.REMEDIATES.value: {KnowledgeUnitType.MISCONCEPTION.value, KnowledgeUnitType.SKILL.value},
    KnowledgeRelationType.EXTENDS_TO.value: PRIMARY_KNOWLEDGE_UNIT_TYPES,
}
_ALLOWED_TARGET_TYPES_BY_RELATION = {
    KnowledgeRelationType.PART_OF.value: STANDARD_KNOWLEDGE_UNIT_TYPES,
    KnowledgeRelationType.PREREQUISITE_FOR.value: PRIMARY_KNOWLEDGE_UNIT_TYPES,
    KnowledgeRelationType.DERIVES_TO.value: {
        KnowledgeUnitType.PRINCIPLE.value,
        KnowledgeUnitType.FORMULA_MODEL.value,
        KnowledgeUnitType.PROCEDURE.value,
        KnowledgeUnitType.SKILL.value,
        KnowledgeUnitType.APPLICATION_CASE.value,
    },
    KnowledgeRelationType.APPLIES_TO.value: {
        KnowledgeUnitType.PROCEDURE.value,
        KnowledgeUnitType.SKILL.value,
        KnowledgeUnitType.APPLICATION_CASE.value,
    },
    KnowledgeRelationType.USES_METHOD.value: {KnowledgeUnitType.PROCEDURE.value, KnowledgeUnitType.SKILL.value},
    KnowledgeRelationType.ASSESSES.value: {
        KnowledgeUnitType.CONCEPT.value,
        KnowledgeUnitType.PRINCIPLE.value,
        KnowledgeUnitType.FORMULA_MODEL.value,
        KnowledgeUnitType.PROCEDURE.value,
        KnowledgeUnitType.SKILL.value,
        KnowledgeUnitType.MISCONCEPTION.value,
    },
    KnowledgeRelationType.EXPLAINS.value: PRIMARY_KNOWLEDGE_UNIT_TYPES | {KnowledgeUnitType.RESOURCE.value},
    KnowledgeRelationType.REMEDIATES.value: PRIMARY_KNOWLEDGE_UNIT_TYPES,
    KnowledgeRelationType.EXTENDS_TO.value: {KnowledgeUnitType.APPLICATION_CASE.value, KnowledgeUnitType.SKILL.value, KnowledgeUnitType.CONCEPT.value},
}


def normalize_knowledge_unit_type(
    raw_type: str | None,
    *,
    default: str = KnowledgeUnitType.CONCEPT.value,
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
    return LEGACY_RELATION_TYPE_MAP.get(normalized, KnowledgeRelationType.APPLIES_TO.value)


def knowledge_unit_type_label(raw_type: str | None) -> str:
    normalized = normalize_knowledge_unit_type(raw_type)
    return KNOWLEDGE_UNIT_TYPE_LABELS.get(normalized, normalized)


def relation_type_label(raw_type: str | None) -> str:
    normalized = normalize_relation_type(raw_type)
    return KNOWLEDGE_RELATION_TYPE_LABELS.get(normalized, normalized)


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
    "KNOWLEDGE_RELATION_TYPE_LABELS",
    "KNOWLEDGE_UNIT_TYPE_LABELS",
    "PARENT_KNOWLEDGE_UNIT_TYPES",
    "PRIMARY_KNOWLEDGE_UNIT_TYPES",
    "SECONDARY_KNOWLEDGE_UNIT_TYPES",
    "STANDARD_KNOWLEDGE_UNIT_TYPES",
    "STANDARD_RELATION_TYPES",
    "STANDARD_TYPE_SOURCES",
    "is_standard_knowledge_unit_type",
    "is_standard_relation_type",
    "knowledge_unit_type_label",
    "normalize_knowledge_unit_type",
    "normalize_relation_type",
    "normalize_type_source",
    "relation_type_label",
    "validate_relation_direction",
]
