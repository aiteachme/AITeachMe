"""Teaching-unit derivation built on the compressed schema."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import structlog
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, or_, select

from app.infra.llm import acompletion_structured
from app.infra.prompt_loader import populate_prompt
from app.models.curriculum import TeachingUnit, TeachingUnitMembership, TeachingUnitRevision
from app.models.knowledge_graph import KnowledgeEdge, KnowledgeNode
from app.repositories import curriculum_repo
from app.schemas.llm import ChatMessage, SYSTEM, USER
from app.utils.kg_helpers import compute_member_signature, normalize_name
from app.workflows.digest.kg.services.impact_analyzer import ImpactSet
from app.workflows.digest.prompts import (
    SYSTEM_PROMPT_KG_UNIT_NAMING,
    USER_PROMPT_KG_UNIT_NAMING,
)

logger = structlog.get_logger(__name__)

_CORE_NODE_TYPES = {"Topic", "Concept", "Method"}
_MAX_UNIT_MEMBER_COUNT = 8


@dataclass(slots=True)
class NodeInfo:
    node_id: int
    node_type: str
    canonical_name: str
    summary: str


@dataclass(slots=True)
class UnitCandidate:
    core_node_ids: list[int] = field(default_factory=list)
    support_node_ids: list[int] = field(default_factory=list)
    example_node_ids: list[int] = field(default_factory=list)

    @property
    def all_node_ids(self) -> list[int]:
        return [*self.core_node_ids, *self.support_node_ids, *self.example_node_ids]


@dataclass(slots=True)
class TeachingUnitDeriveResult:
    units: list[TeachingUnit] = field(default_factory=list)
    created_unit_ids: list[int] = field(default_factory=list)
    updated_unit_ids: list[int] = field(default_factory=list)


class UnitNamingResponse(BaseModel):
    title: str = PydanticField(description="教学单元名称")
    summary: str = PydanticField(description="教学单元摘要")
    learning_objectives: list[str] = PydanticField(description="学习目标列表")


def extract_local_subgraph(
    session: Session,
    subject: str,
    impact_set: ImpactSet,
) -> tuple[list[KnowledgeNode], list[KnowledgeEdge]]:
    """Load the impacted local graph used for unit derivation."""

    seed_ids = impact_set.changed_node_ids | impact_set.candidate_recompute_node_ids
    if not seed_ids:
        return [], []

    edges = list(
        session.exec(
            select(KnowledgeEdge).where(
                KnowledgeEdge.subject == subject,
                KnowledgeEdge.status == "active",
                or_(
                    KnowledgeEdge.source_node_id.in_(seed_ids),
                    KnowledgeEdge.target_node_id.in_(seed_ids),
                ),
            )
        ).all()
    )
    node_ids = {
        node_id
        for edge in edges
        for node_id in (edge.source_node_id, edge.target_node_id)
    } | set(seed_ids)
    nodes = list(
        session.exec(
            select(KnowledgeNode).where(
                KnowledgeNode.subject == subject,
                KnowledgeNode.status.in_(["active", "pending"]),
                KnowledgeNode.id.in_(node_ids),
            )
        ).all()
    )
    logger.info(
        "unit_local_subgraph_loaded",
        subject=subject,
        node_count=len(nodes),
        edge_count=len(edges),
    )
    return nodes, edges


def _build_node_infos(nodes: list[KnowledgeNode]) -> dict[int, NodeInfo]:
    return {
        node.id: NodeInfo(
            node_id=node.id,
            node_type=node.node_type,
            canonical_name=node.canonical_name,
            summary=node.summary,
        )
        for node in nodes
        if node.id is not None
    }


def _build_adjacency(edges: list[KnowledgeEdge]) -> dict[int, set[int]]:
    adjacency: dict[int, set[int]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source_node_id, set()).add(edge.target_node_id)
        adjacency.setdefault(edge.target_node_id, set()).add(edge.source_node_id)
    return adjacency


def _collect_components(node_ids: list[int], adjacency: dict[int, set[int]]) -> list[list[int]]:
    remaining = set(node_ids)
    components: list[list[int]] = []
    while remaining:
        start = remaining.pop()
        queue = [start]
        component = [start]
        while queue:
            node_id = queue.pop()
            for neighbor_id in adjacency.get(node_id, set()):
                if neighbor_id not in remaining:
                    continue
                remaining.remove(neighbor_id)
                queue.append(neighbor_id)
                component.append(neighbor_id)
        components.append(component)
    return components


def _slice_component(component: list[int], node_infos: dict[int, NodeInfo]) -> list[UnitCandidate]:
    ordered = sorted(
        component,
        key=lambda node_id: (
            0 if node_infos[node_id].node_type in _CORE_NODE_TYPES else 1,
            node_infos[node_id].canonical_name,
        ),
    )
    candidates: list[UnitCandidate] = []
    for index in range(0, len(ordered), _MAX_UNIT_MEMBER_COUNT):
        member_ids = ordered[index : index + _MAX_UNIT_MEMBER_COUNT]
        core_ids = [
            node_id for node_id in member_ids if node_infos[node_id].node_type in _CORE_NODE_TYPES
        ]
        if not core_ids and member_ids:
            core_ids = [member_ids[0]]
        example_ids = [
            node_id for node_id in member_ids if node_infos[node_id].node_type == "Example"
        ]
        support_ids = [
            node_id
            for node_id in member_ids
            if node_id not in set(core_ids) and node_id not in set(example_ids)
        ]
        candidates.append(
            UnitCandidate(
                core_node_ids=core_ids,
                support_node_ids=support_ids,
                example_node_ids=example_ids,
            )
        )
    return candidates


def _format_nodes(node_infos: dict[int, NodeInfo], node_ids: list[int]) -> str:
    lines = []
    for node_id in node_ids:
        info = node_infos[node_id]
        summary = info.summary or info.canonical_name
        lines.append(f"- {info.canonical_name} ({info.node_type}): {summary}")
    return "\n".join(lines) if lines else "(none)"


async def _name_unit_with_llm(
    node_infos: dict[int, NodeInfo],
    candidate: UnitCandidate,
) -> UnitNamingResponse:
    user_content = populate_prompt(
        USER_PROMPT_KG_UNIT_NAMING,
        core_nodes=_format_nodes(node_infos, candidate.core_node_ids),
        support_nodes=_format_nodes(node_infos, candidate.support_node_ids),
        example_nodes=_format_nodes(node_infos, candidate.example_node_ids),
    )
    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_KG_UNIT_NAMING},
        {"role": USER, "content": user_content},
    ]
    return await acompletion_structured(
        response_model=UnitNamingResponse,
        messages=messages,
    )


def _fallback_unit_name(
    node_infos: dict[int, NodeInfo],
    candidate: UnitCandidate,
) -> UnitNamingResponse:
    core_names = [node_infos[node_id].canonical_name for node_id in candidate.core_node_ids]
    support_names = [node_infos[node_id].canonical_name for node_id in candidate.support_node_ids]
    title = " / ".join(core_names[:3] or support_names[:2] or ["Untitled unit"])
    objective = f"围绕 {title} 建立可复习、可迁移的理解框架。"
    return UnitNamingResponse(
        title=title,
        summary=f"聚合 {title} 相关知识点，形成一个可讲解、可练习的教学单元。",
        learning_objectives=[objective],
    )


def _create_memberships(session: Session, unit: TeachingUnit, candidate: UnitCandidate) -> None:
    role_groups = [
        (candidate.core_node_ids, "core", 1.0),
        (candidate.support_node_ids, "support", 0.6),
        (candidate.example_node_ids, "example", 0.5),
    ]
    for node_ids, role, score in role_groups:
        for node_id in node_ids:
            curriculum_repo.create_unit_membership(
                session,
                TeachingUnitMembership(
                    unit_id=unit.id or 0,
                    knowledge_node_id=node_id,
                    role=role,
                    score=score,
                ),
            )


def _upsert_unit(
    session: Session,
    subject: str,
    candidate: UnitCandidate,
    naming: UnitNamingResponse,
) -> tuple[TeachingUnit, bool]:
    signature_node_ids = candidate.core_node_ids or candidate.all_node_ids
    member_signature = compute_member_signature(signature_node_ids)
    existing = curriculum_repo.find_unit_by_signature(session, subject, member_signature)

    revision = TeachingUnitRevision(
        unit_id=(existing.id if existing is not None else 0),
        revision_no=1 if existing is None else 2,
        title=naming.title,
        summary=naming.summary,
        learning_objectives_json=json.dumps(naming.learning_objectives, ensure_ascii=False),
        revision_reason="new_evidence",
        is_current=True,
    )

    if existing is not None:
        revision.unit_id = existing.id or 0
        curriculum_repo.create_unit_revision(session, revision)
        existing.canonical_name = naming.title
        existing.normalized_name = normalize_name(naming.title)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing, False

    unit = curriculum_repo.create_teaching_unit(
        session,
        TeachingUnit(
            subject=subject,
            canonical_name=naming.title,
            normalized_name=normalize_name(naming.title),
            member_signature=member_signature,
            status="pending",
            confidence=1.0,
        ),
    )
    revision.unit_id = unit.id or 0
    curriculum_repo.create_unit_revision(session, revision)
    session.refresh(unit)
    _create_memberships(session, unit, candidate)
    return unit, True


async def derive_teaching_units(
    session: Session,
    subject: str,
    impact_set: ImpactSet,
    curriculum_job_id: int,
) -> TeachingUnitDeriveResult:
    """Derive teaching units for the impacted local graph."""

    del curriculum_job_id

    nodes, edges = extract_local_subgraph(session, subject, impact_set)
    if not nodes:
        logger.info("no_nodes_for_unit_derivation", subject=subject)
        raise ValueError("no_graph_nodes_available_for_unit_derivation")

    node_infos = _build_node_infos(nodes)
    adjacency = _build_adjacency(edges)
    components = _collect_components(list(node_infos.keys()), adjacency)
    candidates = [
        candidate
        for component in components
        for candidate in _slice_component(component, node_infos)
        if candidate.all_node_ids
    ]

    result = TeachingUnitDeriveResult()
    for candidate in candidates:
        try:
            naming = await _name_unit_with_llm(node_infos, candidate)
        except Exception:
            logger.warning(
                "unit_naming_llm_failed",
                core_node_ids=candidate.core_node_ids,
                exc_info=True,
            )
            naming = _fallback_unit_name(node_infos, candidate)

        unit, is_created = _upsert_unit(session, subject, candidate, naming)
        result.units.append(unit)
        if unit.id is None:
            continue
        if is_created:
            result.created_unit_ids.append(unit.id)
        else:
            result.updated_unit_ids.append(unit.id)

    logger.info(
        "derive_teaching_units_complete",
        subject=subject,
        units_count=len(result.units),
        created_units=len(result.created_unit_ids),
        updated_units=len(result.updated_unit_ids),
    )
    return result


__all__ = [
    "TeachingUnitDeriveResult",
    "derive_teaching_units",
]
