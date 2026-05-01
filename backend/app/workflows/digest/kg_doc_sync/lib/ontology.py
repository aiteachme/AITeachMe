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


_PRIMARY_ENDPOINT_TYPES = (
    KnowledgeUnitType.CORE_KNOWLEDGE.value,
    KnowledgeUnitType.METHOD_DEMO.value,
    KnowledgeUnitType.PRINCIPLE_REASONING.value,
    KnowledgeUnitType.KNOWLEDGE_ORGANIZATION.value,
    KnowledgeUnitType.APPLICATION_EXTENSION.value,
)
_SUPPORT_ENDPOINT_TYPES = (
    KnowledgeUnitType.EXPLANATION_SUPPORT.value,
    KnowledgeUnitType.PRACTICE_ASSESSMENT.value,
)


LEARNING_GRAPH_ONTOLOGY = LearningGraphOntology(
    name="kg_doc_sync_learning_graph_v2",
    purpose="表达广义学习材料中的知识内容角色，以及它们之间的教学关系。",
    unit_types=(
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.CORE_KNOWLEDGE.value,
            "核心知识：概念、定义、定理、性质、公式、结论、规则、事实、原则、标准、术语，回答必须知道什么",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.METHOD_DEMO.value,
            "方法示范：例题、方法、步骤、流程、解题思路、操作范例、演示过程，回答怎么做",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.EXPLANATION_SUPPORT.value,
            "解释辅助：背景、直观解释、例子、备注、类比、易错点、概念辨析、常见误区，帮助理解",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.PRINCIPLE_REASONING.value,
            "原理推理：证明、推导、命题、机制解释、因果分析、验证过程、适用条件，回答为什么成立或有效",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.PRACTICE_ASSESSMENT.value,
            "练习评估：练习、解析、自测题、纠错任务、评分标准、操作检查、错题分析、复盘任务",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.KNOWLEDGE_ORGANIZATION.value,
            "知识组织：学习目标、重点难点、学习路径、知识框架、模块划分、先修知识、总结",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.APPLICATION_EXTENSION.value,
            "应用拓展：案例、实验、应用场景、项目任务、真实问题、综合任务、迁移训练、开放任务",
        ),
    ),
    relation_types=(
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.PREREQUISITE.value,
            "前置：source 是理解、学习或掌握 target 的先修内容",
            source_type_preferences=_PRIMARY_ENDPOINT_TYPES,
            target_type_preferences=_PRIMARY_ENDPOINT_TYPES,
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.CONTAINS.value,
            "包含：source 在结构上包含 target，或者 target 属于 source",
            source_type_preferences=(KnowledgeUnitType.KNOWLEDGE_ORGANIZATION.value, *(_PRIMARY_ENDPOINT_TYPES)),
            target_type_preferences=(*_PRIMARY_ENDPOINT_TYPES, *_SUPPORT_ENDPOINT_TYPES),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.REASONING.value,
            "推理：source 可以推出 target，或者 target 基于 source 的证明、推导、机制或因果解释得到",
            source_type_preferences=(
                KnowledgeUnitType.CORE_KNOWLEDGE.value,
                KnowledgeUnitType.PRINCIPLE_REASONING.value,
                KnowledgeUnitType.METHOD_DEMO.value,
            ),
            target_type_preferences=(
                KnowledgeUnitType.CORE_KNOWLEDGE.value,
                KnowledgeUnitType.METHOD_DEMO.value,
                KnowledgeUnitType.APPLICATION_EXTENSION.value,
            ),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.APPLICATION.value,
            "应用：source 被用于解决 target，或者 source 在 target 场景中使用",
            source_type_preferences=(
                KnowledgeUnitType.CORE_KNOWLEDGE.value,
                KnowledgeUnitType.METHOD_DEMO.value,
                KnowledgeUnitType.PRINCIPLE_REASONING.value,
            ),
            target_type_preferences=(
                KnowledgeUnitType.METHOD_DEMO.value,
                KnowledgeUnitType.PRACTICE_ASSESSMENT.value,
                KnowledgeUnitType.APPLICATION_EXTENSION.value,
            ),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.EXPLANATION.value,
            "说明：target 对 source 做解释、补充、备注、直观化、例子化或易错提醒",
            source_type_preferences=_PRIMARY_ENDPOINT_TYPES,
            target_type_preferences=(KnowledgeUnitType.EXPLANATION_SUPPORT.value,),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.TRAINING.value,
            "训练：target 用来训练、考察、巩固或评估 source",
            source_type_preferences=(
                KnowledgeUnitType.CORE_KNOWLEDGE.value,
                KnowledgeUnitType.METHOD_DEMO.value,
                KnowledgeUnitType.PRINCIPLE_REASONING.value,
                KnowledgeUnitType.APPLICATION_EXTENSION.value,
            ),
            target_type_preferences=(KnowledgeUnitType.PRACTICE_ASSESSMENT.value,),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.CONTRAST.value,
            "对比：source 和 target 需要区分差异、容易混淆或适合通过差异比较来学习",
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.SIMILAR.value,
            "相似：source 和 target 有相近结构、方法、原理，或者可以类比理解",
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
        source_types = ", ".join(f"`{value}`" for value in spec.source_type_preferences) or "任意合法类型"
        target_types = ", ".join(f"`{value}`" for value in spec.target_type_preferences) or "任意合法类型"
        lines.append(f"- `{spec.value}`：source 优先使用 {source_types}；target 优先使用 {target_types}。")
    return "\n".join(lines)


def relation_endpoint_type_preferences(
    edge_type: str,
    endpoint: RelationEndpoint,
) -> tuple[str, ...]:
    return LEARNING_GRAPH_ONTOLOGY.relation_type_spec(edge_type).endpoint_preferences(endpoint)


def default_relation_for_unit_type(unit_type: str) -> str:
    normalized = normalize_knowledge_unit_type(unit_type)
    if normalized == KnowledgeUnitType.METHOD_DEMO.value:
        return KnowledgeRelationType.APPLICATION.value
    if normalized == KnowledgeUnitType.PRINCIPLE_REASONING.value:
        return KnowledgeRelationType.REASONING.value
    if normalized == KnowledgeUnitType.PRACTICE_ASSESSMENT.value:
        return KnowledgeRelationType.TRAINING.value
    if normalized == KnowledgeUnitType.EXPLANATION_SUPPORT.value:
        return KnowledgeRelationType.EXPLANATION.value
    if normalized == KnowledgeUnitType.APPLICATION_EXTENSION.value:
        return KnowledgeRelationType.APPLICATION.value
    return KnowledgeRelationType.CONTAINS.value


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
