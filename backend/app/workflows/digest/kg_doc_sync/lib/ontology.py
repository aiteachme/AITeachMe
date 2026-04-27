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
    purpose="表达学习材料中可复用的知识单元，以及它们之间的教学关系。",
    unit_types=(
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.CONCEPT.value,
            "可独立复用的原子概念，适合作为一个 Knowledge Unit 展示",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.DEFINITION.value,
            "明确的定义、含义解释或概念解释",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.THEOREM.value,
            "定理、性质、引理、命题或公理",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.FORMULA.value,
            "公式、方程、规则、恒等式或计算关系",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.EXAMPLE.value,
            "例题、示例或说明性案例",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.EXERCISE.value,
            "练习题、训练题或需要作答的实践项",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.METHOD.value,
            "方法、策略、技巧、步骤或算法",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.PROOF_STEP.value,
            "证明步骤、推导步骤或关键论证环节",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.REMARK.value,
            "注意事项、边界条件、常见错误或补充说明",
        ),
    ),
    relation_types=(
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.PREREQUISITE.value,
            "source 是学习 target 前需要先掌握的前置知识",
            source_type_preferences=_RELATION_ENDPOINT_PRIMARY_TYPES,
            target_type_preferences=_RELATION_ENDPOINT_PRIMARY_TYPES,
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.DERIVATION.value,
            "source 定义、推导、支撑 target，或从属于 target",
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
            "source 会被用于理解、解决或应用 target",
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
            "source 是 target 的例题、练习或说明性案例",
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
            "source 与 target 相似，容易互相迁移或类比",
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.CONTRAST.value,
            "source 与 target 构成对比、区分或易混关系",
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
        source_types = ", ".join(f"`{value}`" for value in spec.source_type_preferences) or "任意合法且未被拦截的类型"
        target_types = ", ".join(f"`{value}`" for value in spec.target_type_preferences) or "任意合法且未被拦截的类型"
        lines.append(f"- `{spec.value}`：source 优先使用 {source_types}；target 优先使用 {target_types}。")
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
