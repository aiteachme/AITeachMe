"""Teaching-unit derivation built on the compressed schema."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from time import perf_counter

import structlog
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session, or_, select

from app.core.config import get_settings
from app.infra.llm import acompletion_structured
from app.infra.model_router import TaskType
from app.infra.prompt_loader import populate_prompt
from app.models.curriculum import TeachingUnit, TeachingUnitMembership, TeachingUnitRevision
from app.models.knowledge_graph import KnowledgeEdge, KnowledgeNode
from app.repositories import curriculum_repo
from app.schemas.llm import ChatMessage, SYSTEM, USER
from app.utils.kg_helpers import compute_member_signature, normalize_name
from app.workflows.digest.kg.services.impact_analyzer import ImpactSet
from app.workflows.digest.observability import add_slow_item
from app.workflows.digest.prompts import (
    SYSTEM_PROMPT_KG_UNIT_NAMING,
    USER_PROMPT_KG_UNIT_NAMING,
)

logger = structlog.get_logger(__name__)

_CORE_NODE_TYPES = {"Topic", "Concept", "Method"}
_MAX_UNIT_MEMBER_COUNT = 8
_LARGE_COMPONENT_THRESHOLD = 15


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
    subgraph_load_ms: int = 0
    candidate_build_ms: int = 0
    unit_naming_ms: int = 0
    unit_persist_ms: int = 0
    rule_named_unit_count: int = 0
    llm_named_unit_count: int = 0
    fallback_named_unit_count: int = 0
    unit_naming_parallelism: int = 1
    slowest_unit_namings: list[dict[str, object]] = field(default_factory=list)


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


def _build_topic_membership(edges: list[KnowledgeEdge]) -> dict[int, set[int]]:
    """Map each node to the set of Topic node IDs it belongs to via belongs_to_topic edges."""
    membership: dict[int, set[int]] = {}
    for edge in edges:
        if edge.edge_type == "belongs_to_topic":
            # source belongs_to_topic target (target is the Topic)
            membership.setdefault(edge.source_node_id, set()).add(edge.target_node_id)
        elif edge.edge_type == "part_of":
            membership.setdefault(edge.source_node_id, set()).add(edge.target_node_id)
    return membership


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


def _split_large_component(
    component: list[int],
    node_infos: dict[int, NodeInfo],
    edges: list[KnowledgeEdge],
) -> list[list[int]]:
    """Split a large connected component into sub-groups by Topic affinity.

    For each Topic node in the component, collect its directly connected
    non-Topic children (via belongs_to_topic / illustrated_by / defined_by /
    part_of edges).  Nodes not claimed by any Topic go into a remainder group.
    """
    component_set = set(component)
    topic_ids = [nid for nid in component if node_infos[nid].node_type == "Topic"]

    if not topic_ids:
        # No Topic nodes — fall back to simple slicing
        return [component]

    # Build direct children for each Topic
    topic_children: dict[int, list[int]] = {tid: [] for tid in topic_ids}
    claimed: set[int] = set(topic_ids)

    for edge in edges:
        src, tgt = edge.source_node_id, edge.target_node_id
        if src not in component_set or tgt not in component_set:
            continue
        if edge.edge_type in ("belongs_to_topic", "part_of"):
            # source belongs to target (target is Topic)
            if tgt in topic_children and src not in claimed:
                topic_children[tgt].append(src)
                claimed.add(src)
        elif edge.edge_type in ("illustrated_by", "defined_by"):
            # source (Concept/Method) -> target (Example/Definition)
            if src in topic_children and tgt not in claimed:
                topic_children[src].append(tgt)
                claimed.add(tgt)

    # Build sub-groups: each Topic + its children
    sub_groups: list[list[int]] = []
    for tid in topic_ids:
        children = topic_children[tid]
        if children:
            sub_groups.append([tid] + children)
        else:
            sub_groups.append([tid])

    # Remainder: nodes not claimed by any Topic
    remainder = [nid for nid in component if nid not in claimed]
    if remainder:
        sub_groups.append(remainder)

    return sub_groups


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


def _resolve_unit_naming_parallelism() -> int:
    settings = get_settings()
    return max(1, min(8, max(1, settings.llm_concurrency_limit // 2)))


def _rule_based_unit_name(
    node_infos: dict[int, NodeInfo],
    candidate: UnitCandidate,
) -> UnitNamingResponse | None:
    core_names = [node_infos[node_id].canonical_name for node_id in candidate.core_node_ids]
    support_names = [node_infos[node_id].canonical_name for node_id in candidate.support_node_ids[:2]]
    example_count = len(candidate.example_node_ids)
    if len(core_names) == 1 and len(candidate.all_node_ids) <= 4:
        title = core_names[0]
        summary_parts = [f"围绕 {title} 组织核心知识点"]
        if support_names:
            summary_parts.append(f"并补充 {', '.join(support_names)}")
        if example_count:
            summary_parts.append(f"附带 {example_count} 个例题/练习")
        summary = "，".join(summary_parts) + "。"
        return UnitNamingResponse(
            title=title,
            summary=summary,
            learning_objectives=[
                f"理解并能够讲清 {title} 的核心概念、方法与常见应用。",
            ],
        )
    if len(core_names) == 2 and not candidate.example_node_ids and len(candidate.support_node_ids) <= 2:
        title = " / ".join(core_names)
        return UnitNamingResponse(
            title=title,
            summary=f"整合 {title} 两个紧密相关的核心知识点，形成一个可连续讲解与复习的教学单元。",
            learning_objectives=[f"建立 {title} 之间的联系，并能在题目中综合使用。"],
        )
    return None


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
        task_type=TaskType.DOCGEN_LIGHT,
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


def _create_memberships(
    session: Session,
    unit: TeachingUnit,
    candidate: UnitCandidate,
    *,
    auto_commit: bool,
) -> None:
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
                auto_commit=auto_commit,
            )


def _upsert_unit(
    session: Session,
    subject: str,
    candidate: UnitCandidate,
    naming: UnitNamingResponse,
    *,
    auto_commit: bool,
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
        curriculum_repo.create_unit_revision(session, revision, auto_commit=auto_commit)
        existing.canonical_name = naming.title
        existing.normalized_name = normalize_name(naming.title)
        session.add(existing)
        if auto_commit:
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
        auto_commit=auto_commit,
    )
    revision.unit_id = unit.id or 0
    curriculum_repo.create_unit_revision(session, revision, auto_commit=auto_commit)
    if auto_commit:
        session.refresh(unit)
    _create_memberships(session, unit, candidate, auto_commit=auto_commit)
    return unit, True


async def derive_teaching_units(
    session: Session,
    subject: str,
    impact_set: ImpactSet,
    curriculum_job_id: int,
) -> TeachingUnitDeriveResult:
    """Derive teaching units for the impacted local graph."""

    del curriculum_job_id

    subgraph_started_at = perf_counter()
    nodes, edges = extract_local_subgraph(session, subject, impact_set)
    subgraph_load_ms = int((perf_counter() - subgraph_started_at) * 1000)
    if not nodes:
        logger.info("no_nodes_for_unit_derivation", subject=subject)
        raise ValueError("no_graph_nodes_available_for_unit_derivation")

    candidate_build_started_at = perf_counter()
    node_infos = _build_node_infos(nodes)
    adjacency = _build_adjacency(edges)
    components = _collect_components(list(node_infos.keys()), adjacency)

    # Split large connected components by Topic affinity so that the
    # resulting teaching units are not all lumped into one giant group.
    refined_components: list[list[int]] = []
    for component in components:
        if len(component) > _LARGE_COMPONENT_THRESHOLD:
            refined_components.extend(
                _split_large_component(component, node_infos, edges)
            )
        else:
            refined_components.append(component)

    candidates = [
        candidate
        for component in refined_components
        for candidate in _slice_component(component, node_infos)
        if candidate.all_node_ids
    ]
    candidate_build_ms = int((perf_counter() - candidate_build_started_at) * 1000)

    result = TeachingUnitDeriveResult(
        subgraph_load_ms=subgraph_load_ms,
        candidate_build_ms=candidate_build_ms,
    )
    semaphore = asyncio.Semaphore(_resolve_unit_naming_parallelism())
    result.unit_naming_parallelism = _resolve_unit_naming_parallelism()
    naming_started_at = perf_counter()

    async def _resolve_naming(candidate: UnitCandidate) -> tuple[UnitNamingResponse, str, int]:
        naming_item_started_at = perf_counter()
        rule_based = _rule_based_unit_name(node_infos, candidate)
        if rule_based is not None:
            return (
                rule_based,
                "rule",
                int((perf_counter() - naming_item_started_at) * 1000),
            )
        try:
            async with semaphore:
                naming = await _name_unit_with_llm(node_infos, candidate)
            return (
                naming,
                "llm",
                int((perf_counter() - naming_item_started_at) * 1000),
            )
        except Exception:
            logger.warning(
                "unit_naming_llm_failed",
                core_node_ids=candidate.core_node_ids,
                exc_info=True,
            )
            return (
                _fallback_unit_name(node_infos, candidate),
                "fallback",
                int((perf_counter() - naming_item_started_at) * 1000),
            )

    namings = await asyncio.gather(*(_resolve_naming(candidate) for candidate in candidates))
    result.unit_naming_ms = int((perf_counter() - naming_started_at) * 1000)

    persist_started_at = perf_counter()
    for index, (candidate, naming_payload) in enumerate(zip(candidates, namings, strict=False), start=1):
        naming, naming_source, naming_elapsed_ms = naming_payload
        if naming_source == "rule":
            result.rule_named_unit_count += 1
        elif naming_source == "llm":
            result.llm_named_unit_count += 1
        else:
            result.fallback_named_unit_count += 1
        result.slowest_unit_namings = add_slow_item(
            result.slowest_unit_namings,
            item_id=f"candidate_{index}",
            title=naming.title,
            elapsed_ms=naming_elapsed_ms,
            metadata={
                "source": naming_source,
                "core_node_count": len(candidate.core_node_ids),
                "support_node_count": len(candidate.support_node_ids),
                "example_node_count": len(candidate.example_node_ids),
            },
        )
        unit, is_created = _upsert_unit(
            session,
            subject,
            candidate,
            naming,
            auto_commit=False,
        )
        result.units.append(unit)
        if unit.id is None:
            continue
        if is_created:
            result.created_unit_ids.append(unit.id)
        else:
            result.updated_unit_ids.append(unit.id)
        if index % 20 == 0:
            session.commit()

    session.commit()
    result.unit_persist_ms = int((perf_counter() - persist_started_at) * 1000)

    logger.info(
        "derive_teaching_units_complete",
        subject=subject,
        units_count=len(result.units),
        created_units=len(result.created_unit_ids),
        updated_units=len(result.updated_unit_ids),
        subgraph_load_ms=result.subgraph_load_ms,
        candidate_build_ms=result.candidate_build_ms,
        unit_naming_ms=result.unit_naming_ms,
        unit_persist_ms=result.unit_persist_ms,
        rule_named_unit_count=result.rule_named_unit_count,
        llm_named_unit_count=result.llm_named_unit_count,
        fallback_named_unit_count=result.fallback_named_unit_count,
    )
    return result


__all__ = [
    "TeachingUnitDeriveResult",
    "derive_teaching_units",
]
