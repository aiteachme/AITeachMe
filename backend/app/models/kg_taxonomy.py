"""Standard KnowledgeUnit and KG relation taxonomy."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import KGRelationType, KnowledgeUnitType, KnowledgeUnitTypeSource

STANDARD_KNOWLEDGE_UNIT_TYPES = {item.value for item in KnowledgeUnitType}
STANDARD_RELATION_TYPES = {item.value for item in KGRelationType}
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
PARENT_KNOWLEDGE_UNIT_TYPES = PRIMARY_KNOWLEDGE_UNIT_TYPES | {
    KnowledgeUnitType.DEFINITION.value,
}

_UNIT_TYPE_ALIASES: dict[str, str] = {
    "topic": KnowledgeUnitType.CONCEPT.value,
    "concept": KnowledgeUnitType.CONCEPT.value,
    "definition": KnowledgeUnitType.DEFINITION.value,
    "theorem": KnowledgeUnitType.THEOREM.value,
    "lemma": KnowledgeUnitType.THEOREM.value,
    "proposition": KnowledgeUnitType.THEOREM.value,
    "formula": KnowledgeUnitType.FORMULA.value,
    "equation": KnowledgeUnitType.FORMULA.value,
    "example": KnowledgeUnitType.EXAMPLE.value,
    "exercise": KnowledgeUnitType.EXERCISE.value,
    "question": KnowledgeUnitType.EXERCISE.value,
    "problem": KnowledgeUnitType.EXERCISE.value,
    "method": KnowledgeUnitType.METHOD.value,
    "proof_step": KnowledgeUnitType.PROOF_STEP.value,
    "proofstep": KnowledgeUnitType.PROOF_STEP.value,
    "proof": KnowledgeUnitType.PROOF_STEP.value,
    "remark": KnowledgeUnitType.REMARK.value,
    "note": KnowledgeUnitType.REMARK.value,
}

_RELATION_TYPE_ALIASES: dict[str, str] = {
    "prerequisite": KGRelationType.PREREQUISITE.value,
    "prerequisite_of": KGRelationType.PREREQUISITE.value,
    "requires": KGRelationType.PREREQUISITE.value,
    "derivation": KGRelationType.DERIVATION.value,
    "derivation_of": KGRelationType.DERIVATION.value,
    "defined_by": KGRelationType.DERIVATION.value,
    "part_of": KGRelationType.DERIVATION.value,
    "application": KGRelationType.APPLICATION.value,
    "applies_to": KGRelationType.APPLICATION.value,
    "belongs_to_topic": KGRelationType.APPLICATION.value,
    "example_of": KGRelationType.EXAMPLE_OF.value,
    "illustrated_by": KGRelationType.EXAMPLE_OF.value,
    "similar": KGRelationType.SIMILAR.value,
    "contrast": KGRelationType.CONTRAST.value,
}

_SWAPPED_LEGACY_RELATIONS = {"defined_by", "illustrated_by"}


@dataclass(frozen=True, slots=True)
class NormalizedRelation:
    edge_type: str
    swap_endpoints: bool = False


def normalize_knowledge_unit_type(raw_type: str | None, *, default: str = KnowledgeUnitType.CONCEPT.value) -> str:
    normalized = str(raw_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _UNIT_TYPE_ALIASES.get(normalized, default)


def normalize_type_source(raw_source: str | None, *, default: str = KnowledgeUnitTypeSource.LLM.value) -> str:
    normalized = str(raw_source or "").strip().lower()
    return normalized if normalized in STANDARD_TYPE_SOURCES else default


def normalize_relation_type(raw_type: str | None) -> NormalizedRelation:
    normalized = str(raw_type or "").strip().lower().replace("-", "_").replace(" ", "_")
    edge_type = _RELATION_TYPE_ALIASES.get(normalized, KGRelationType.APPLICATION.value)
    return NormalizedRelation(edge_type=edge_type, swap_endpoints=normalized in _SWAPPED_LEGACY_RELATIONS)


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
    relation = normalize_relation_type(edge_type).edge_type

    if relation == KGRelationType.PREREQUISITE.value:
        return source != KnowledgeUnitType.EXAMPLE.value and target != KnowledgeUnitType.EXAMPLE.value
    if relation == KGRelationType.EXAMPLE_OF.value:
        return source in {KnowledgeUnitType.EXAMPLE.value, KnowledgeUnitType.EXERCISE.value}
    if relation in {KGRelationType.SIMILAR.value, KGRelationType.CONTRAST.value}:
        return source != KnowledgeUnitType.EXAMPLE.value and target != KnowledgeUnitType.EXAMPLE.value
    return True
