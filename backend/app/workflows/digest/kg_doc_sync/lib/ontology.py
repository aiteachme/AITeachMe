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
    label_zh: str
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
    label_zh: str
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
    KnowledgeUnitType.CONCEPT.value,
    KnowledgeUnitType.PRINCIPLE.value,
    KnowledgeUnitType.FORMULA_MODEL.value,
    KnowledgeUnitType.PROCEDURE.value,
    KnowledgeUnitType.SKILL.value,
    KnowledgeUnitType.MISCONCEPTION.value,
    KnowledgeUnitType.APPLICATION_CASE.value,
)
_SUPPORT_ENDPOINT_TYPES = (
    KnowledgeUnitType.TOPIC.value,
)


LEARNING_GRAPH_ONTOLOGY = LearningGraphOntology(
    name="kg_doc_sync_learning_graph_v3",
    purpose="表达学习内容中的主题、知识、技能、易错点与教学路径关系。",
    unit_types=(
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.TOPIC.value,
            "主题模块",
            "主题模块：课程、章节、单元或知识簇，用于组织结构，不直接代表一个需要测量掌握度的知识点。",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.CONCEPT.value,
            "概念术语",
            "概念术语：稳定的名词、对象、定义项或基础事实，回答学习者必须先知道什么；不要放练习安排、题量计划、测试任务或一次性学习目标。",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.PRINCIPLE.value,
            "原理性质",
            "原理性质：定理、规律、机制、成立条件、证明结论、因果关系，回答为什么成立。",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.FORMULA_MODEL.value,
            "公式模型",
            "公式模型：公式、方程、图像模型、符号模型、计算关系和适用边界。",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.PROCEDURE.value,
            "方法步骤",
            "方法步骤：解题流程、操作步骤、证明套路、实验流程、分析框架，回答怎么做。",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.SKILL.value,
            "解题技能",
            "解题技能：可训练、可诊断的能力点或题型目标，例如建模、化简、判别、作图、迁移、检查与证明。",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.MISCONCEPTION.value,
            "易错辨析",
            "易错辨析：常见误区、混淆项、错误方法、边界条件和纠错提示。",
        ),
        KnowledgeUnitTypeSpec(
            KnowledgeUnitType.APPLICATION_CASE.value,
            "应用案例",
            "应用案例：例题、实验、真实场景、综合任务、迁移问题，用于连接知识和使用情境；有题量/训练意味时优先用 `skill`。",
        ),
    ),
    relation_types=(
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.PART_OF.value,
            "归属",
            "归属：source 是 target 的组成部分、子主题或被纳入的知识点。",
            source_type_preferences=_PRIMARY_ENDPOINT_TYPES,
            target_type_preferences=(KnowledgeUnitType.TOPIC.value, *_PRIMARY_ENDPOINT_TYPES),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.PREREQUISITE_FOR.value,
            "前置",
            "前置：掌握 source 是学习 target 的必要或强建议先修条件。",
            source_type_preferences=_PRIMARY_ENDPOINT_TYPES,
            target_type_preferences=_PRIMARY_ENDPOINT_TYPES,
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.DERIVES_TO.value,
            "推导",
            "推导：source 能推导、证明、解释或生成 target。",
            source_type_preferences=(KnowledgeUnitType.CONCEPT.value, KnowledgeUnitType.PRINCIPLE.value, KnowledgeUnitType.FORMULA_MODEL.value),
            target_type_preferences=(KnowledgeUnitType.PRINCIPLE.value, KnowledgeUnitType.FORMULA_MODEL.value, KnowledgeUnitType.PROCEDURE.value, KnowledgeUnitType.SKILL.value),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.APPLIES_TO.value,
            "应用",
            "应用：source 可用于解决、解释或迁移到 target。",
            source_type_preferences=(KnowledgeUnitType.CONCEPT.value, KnowledgeUnitType.PRINCIPLE.value, KnowledgeUnitType.FORMULA_MODEL.value, KnowledgeUnitType.PROCEDURE.value),
            target_type_preferences=(KnowledgeUnitType.PROCEDURE.value, KnowledgeUnitType.SKILL.value, KnowledgeUnitType.APPLICATION_CASE.value),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.USES_METHOD.value,
            "用方法",
            "用方法：source 需要使用 target 这一方法、步骤或技能才能完成。",
            source_type_preferences=(KnowledgeUnitType.SKILL.value, KnowledgeUnitType.APPLICATION_CASE.value, KnowledgeUnitType.FORMULA_MODEL.value),
            target_type_preferences=(KnowledgeUnitType.PROCEDURE.value, KnowledgeUnitType.SKILL.value),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.ASSESSES.value,
            "考察",
            "考察：source 这类技能、题型或任务用于检验 target 的掌握情况。",
            source_type_preferences=(KnowledgeUnitType.SKILL.value, KnowledgeUnitType.APPLICATION_CASE.value, KnowledgeUnitType.PROCEDURE.value),
            target_type_preferences=(KnowledgeUnitType.CONCEPT.value, KnowledgeUnitType.PRINCIPLE.value, KnowledgeUnitType.FORMULA_MODEL.value, KnowledgeUnitType.PROCEDURE.value, KnowledgeUnitType.SKILL.value, KnowledgeUnitType.MISCONCEPTION.value),
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.EXPLAINS.value,
            "解释",
            "解释：source 对 target 做直观说明、背景补充、证据支撑或换一种说法。",
            source_type_preferences=(KnowledgeUnitType.APPLICATION_CASE.value, KnowledgeUnitType.PROCEDURE.value, KnowledgeUnitType.PRINCIPLE.value),
            target_type_preferences=_PRIMARY_ENDPOINT_TYPES,
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.REMEDIATES.value,
            "补救",
            "补救：source 用于修正 target 的误区、薄弱点或错误方法。",
            source_type_preferences=(KnowledgeUnitType.MISCONCEPTION.value, KnowledgeUnitType.PROCEDURE.value, KnowledgeUnitType.SKILL.value),
            target_type_preferences=_PRIMARY_ENDPOINT_TYPES,
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.CONFUSES_WITH.value,
            "易混",
            "易混：source 和 target 容易混淆，或需要通过差异比较学习。",
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.SIMILAR_TO.value,
            "相似",
            "相似：source 和 target 有相近结构、方法或原理，可类比理解。",
        ),
        KnowledgeRelationTypeSpec(
            KnowledgeRelationType.EXTENDS_TO.value,
            "拓展",
            "拓展：source 可进一步迁移、延伸或综合到 target。",
            source_type_preferences=_PRIMARY_ENDPOINT_TYPES,
            target_type_preferences=(KnowledgeUnitType.APPLICATION_CASE.value, KnowledgeUnitType.SKILL.value, KnowledgeUnitType.CONCEPT.value),
        ),
    ),
)


def format_ontology_unit_type_bullets() -> str:
    return "\n".join(f"- `{spec.value}`（{spec.label_zh}）: {spec.description}" for spec in LEARNING_GRAPH_ONTOLOGY.unit_types)


def format_ontology_relation_type_bullets() -> str:
    return "\n".join(f"- `{spec.value}`（{spec.label_zh}）: {spec.description}" for spec in LEARNING_GRAPH_ONTOLOGY.relation_types)


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
    if normalized in {KnowledgeUnitType.PRINCIPLE.value, KnowledgeUnitType.FORMULA_MODEL.value}:
        return KnowledgeRelationType.DERIVES_TO.value
    if normalized == KnowledgeUnitType.SKILL.value:
        return KnowledgeRelationType.ASSESSES.value
    if normalized == KnowledgeUnitType.MISCONCEPTION.value:
        return KnowledgeRelationType.REMEDIATES.value
    if normalized == KnowledgeUnitType.RESOURCE.value:
        return KnowledgeRelationType.EXPLAINS.value
    return KnowledgeRelationType.PART_OF.value


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
