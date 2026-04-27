"""Ontology wording for the knowledge-doc graph sync workflow.

The persisted graph type contract lives in ``app.models.knowledge_taxonomy``.
This module keeps the KG-doc-sync prompt-facing descriptions close to the
workflow implementation that consumes them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.models.enums import KnowledgeRelationType, KnowledgeUnitType
from app.models.knowledge_taxonomy import (
    PARENT_KNOWLEDGE_UNIT_TYPES,
    PRIMARY_KNOWLEDGE_UNIT_TYPES,
    SECONDARY_KNOWLEDGE_UNIT_TYPES,
    normalize_knowledge_unit_type,
    normalize_relation_type,
    validate_relation_direction,
)

KnowledgeUnitRole = Literal["primary", "secondary"]
RelationEndpoint = Literal["source", "target"]


@dataclass(frozen=True, slots=True)
class KnowledgeUnitTypeSpec:
    """One prompt-facing learning-graph node type."""

    value: str
    description: str

    @property
    def role(self) -> KnowledgeUnitRole:
        if self.value in PRIMARY_KNOWLEDGE_UNIT_TYPES:
            return "primary"
        if self.value in SECONDARY_KNOWLEDGE_UNIT_TYPES:
            return "secondary"
        raise ValueError(f"unknown knowledge unit type in ontology: {self.value}")

    @property
    def can_be_parent(self) -> bool:
        return self.value in PARENT_KNOWLEDGE_UNIT_TYPES


@dataclass(frozen=True, slots=True)
class KnowledgeRelationTypeSpec:
    """One prompt-facing learning-graph edge type."""

    value: str
    description: str
    source_type_preferences: tuple[str, ...] = ()
    target_type_preferences: tuple[str, ...] = ()

    def allows(self, *, source_type: str, target_type: str) -> bool:
        return validate_relation_direction(
            edge_type=self.value,
            source_type=source_type,
            target_type=target_type,
        )

    def endpoint_preferences(self, endpoint: RelationEndpoint) -> tuple[str, ...]:
        return self.source_type_preferences if endpoint == "source" else self.target_type_preferences


@dataclass(frozen=True, slots=True)
class LearningGraphOntology:
    """Prompt-facing schema contract used by KG-doc-sync extraction."""

    name: str
    purpose: str
    unit_types: tuple[KnowledgeUnitTypeSpec, ...]
    relation_types: tuple[KnowledgeRelationTypeSpec, ...]

    @property
    def unit_type_values(self) -> tuple[str, ...]:
        return tuple(spec.value for spec in self.unit_types)

    @property
    def relation_type_values(self) -> tuple[str, ...]:
        return tuple(spec.value for spec in self.relation_types)

    @property
    def primary_unit_type_values(self) -> tuple[str, ...]:
        return tuple(spec.value for spec in self.unit_types if spec.role == "primary")

    @property
    def secondary_unit_type_values(self) -> tuple[str, ...]:
        return tuple(spec.value for spec in self.unit_types if spec.role == "secondary")

    @property
    def parent_unit_type_values(self) -> tuple[str, ...]:
        return tuple(spec.value for spec in self.unit_types if spec.can_be_parent)

    def relation_type_spec(self, value: str) -> KnowledgeRelationTypeSpec:
        normalized = normalize_relation_type(value)
        for spec in self.relation_types:
            if spec.value == normalized:
                return spec
        raise ValueError(f"unknown relation type in ontology: {value}")


_RELATION_ENDPOINT_PRIMARY_TYPES = (
    KnowledgeUnitType.CONCEPT.value,
    KnowledgeUnitType.METHOD.value,
    KnowledgeUnitType.DEFINITION.value,
    KnowledgeUnitType.THEOREM.value,
    KnowledgeUnitType.FORMULA.value,
    KnowledgeUnitType.EXERCISE.value,
    KnowledgeUnitType.PROOF_STEP.value,
    KnowledgeUnitType.REMARK.value,
)
_RELATION_PARENT_TARGET_TYPES = (
    KnowledgeUnitType.CONCEPT.value,
    KnowledgeUnitType.METHOD.value,
    KnowledgeUnitType.THEOREM.value,
    KnowledgeUnitType.FORMULA.value,
    KnowledgeUnitType.PROOF_STEP.value,
)
_RELATION_EXAMPLE_SOURCE_TYPES = (
    KnowledgeUnitType.EXAMPLE.value,
    KnowledgeUnitType.EXERCISE.value,
)


LEARNING_GRAPH_ONTOLOGY = LearningGraphOntology(
    name="kg_doc_sync_learning_graph",
    purpose="Represent reusable study-material knowledge units and their pedagogical relationships.",
    unit_types=(
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.CONCEPT.value,
            "one atomic, reusable concept that can stand alone as a Knowledge Unit",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.DEFINITION.value,
            "explicit definition or interpretation",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.THEOREM.value,
            "theorem, property, lemma, proposition, axiom",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.FORMULA.value,
            "formula, equation, rule, identity",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.EXAMPLE.value,
            "worked example or illustrative case",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.EXERCISE.value,
            "question or practice item",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.METHOD.value,
            "method, strategy, technique, algorithm",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.PROOF_STEP.value,
            "proof or derivation step",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.REMARK.value,
            "caveat, note, common mistake, condition",
        ),
    ),
    relation_types=(
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.PREREQUISITE.value,
            "source is needed before target",
            source_type_preferences=_RELATION_ENDPOINT_PRIMARY_TYPES,
            target_type_preferences=_RELATION_ENDPOINT_PRIMARY_TYPES,
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.DERIVATION.value,
            "source defines, derives, supports, or belongs under target",
            source_type_preferences=(
                KnowledgeUnitType.DEFINITION.value,
                KnowledgeUnitType.THEOREM.value,
                KnowledgeUnitType.FORMULA.value,
                KnowledgeUnitType.PROOF_STEP.value,
                KnowledgeUnitType.CONCEPT.value,
                KnowledgeUnitType.METHOD.value,
            ),
            target_type_preferences=_RELATION_PARENT_TARGET_TYPES,
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.APPLICATION.value,
            "source is used in target",
            source_type_preferences=(
                KnowledgeUnitType.CONCEPT.value,
                KnowledgeUnitType.METHOD.value,
                KnowledgeUnitType.DEFINITION.value,
                KnowledgeUnitType.FORMULA.value,
                KnowledgeUnitType.THEOREM.value,
                KnowledgeUnitType.EXERCISE.value,
                KnowledgeUnitType.REMARK.value,
            ),
            target_type_preferences=(KnowledgeUnitType.CONCEPT.value,),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.EXAMPLE_OF.value,
            "source is an example or exercise of target",
            source_type_preferences=_RELATION_EXAMPLE_SOURCE_TYPES,
            target_type_preferences=(
                KnowledgeUnitType.CONCEPT.value,
                KnowledgeUnitType.METHOD.value,
                KnowledgeUnitType.THEOREM.value,
                KnowledgeUnitType.FORMULA.value,
            ),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.SIMILAR.value,
            "source is similar to target",
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.CONTRAST.value,
            "source contrasts with target",
        ),
    ),
)

def format_ontology_unit_type_bullets() -> str:
    return "\n".join(f"- `{spec.value}`: {spec.description}" for spec in LEARNING_GRAPH_ONTOLOGY.unit_types)


def format_ontology_relation_type_bullets() -> str:
    return "\n".join(f"- `{spec.value}`: {spec.description}" for spec in LEARNING_GRAPH_ONTOLOGY.relation_types)


def format_ontology_relation_direction_bullets() -> str:
    lines: list[str] = []
    for spec in LEARNING_GRAPH_ONTOLOGY.relation_types:
        source_types = ", ".join(f"`{value}`" for value in spec.source_type_preferences) or "any valid non-blocked type"
        target_types = ", ".join(f"`{value}`" for value in spec.target_type_preferences) or "any valid non-blocked type"
        lines.append(f"- `{spec.value}`: source prefers {source_types}; target prefers {target_types}.")
    return "\n".join(lines)


def relation_endpoint_type_preferences(
    edge_type: str,
    endpoint: RelationEndpoint,
) -> tuple[str, ...]:
    return LEARNING_GRAPH_ONTOLOGY.relation_type_spec(edge_type).endpoint_preferences(endpoint)


def default_relation_for_unit_type(unit_type: str) -> str:
    normalized = normalize_knowledge_unit_type(unit_type)
    if normalized in _RELATION_EXAMPLE_SOURCE_TYPES:
        return KnowledgeRelationType.EXAMPLE_OF.value
    if normalized == KnowledgeUnitType.REMARK.value:
        return KnowledgeRelationType.APPLICATION.value
    return KnowledgeRelationType.DERIVATION.value


__all__ = [
    "LEARNING_GRAPH_ONTOLOGY",
    "KnowledgeRelationTypeSpec",
    "KnowledgeUnitTypeSpec",
    "LearningGraphOntology",
    "default_relation_for_unit_type",
    "format_ontology_relation_direction_bullets",
    "format_ontology_relation_type_bullets",
    "format_ontology_unit_type_bullets",
    "relation_endpoint_type_preferences",
]
