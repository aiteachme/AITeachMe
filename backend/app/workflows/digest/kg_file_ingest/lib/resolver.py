"""Node and edge resolution helpers for the digest knowledge graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import structlog
from pydantic import BaseModel, Field as PydanticField
from sqlmodel import Session

from app.shared.infra.embedding import aembed_texts
from app.shared.infra.llm_support import acompletion_structured
from app.shared.infra.prompt_loader import populate_prompt
from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.repositories import knowledge_relation_repo, knowledge_unit_repo
from app.schemas.llm import ChatMessage, SYSTEM, USER
from app.utils.knowledge_helpers import normalize_name
from app.workflows.digest.kg_file_ingest.lib.candidate_identity import build_candidate_name_key
from app.workflows.digest.kg_file_ingest.lib.clusterer import ClusteredCandidate
from app.workflows.digest.kg_file_ingest.lib.extractor import CandidateEdge
from app.models.knowledge_taxonomy import (
    PARENT_KNOWLEDGE_UNIT_TYPES,
    PRIMARY_KNOWLEDGE_UNIT_TYPES,
    SECONDARY_KNOWLEDGE_UNIT_TYPES,
    normalize_knowledge_unit_type,
    normalize_relation_type,
    validate_relation_direction,
)
from app.workflows.digest.kg_file_ingest.prompts import (
    SYSTEM_PROMPT_KNOWLEDGE_ENTITY_MATCH,
    USER_PROMPT_KNOWLEDGE_ENTITY_MATCH,
)

logger = structlog.get_logger()

_EMBEDDING_SIMILARITY_THRESHOLD = 0.80
_SECONDARY_SIMILARITY_THRESHOLD = 0.85
_PRIMARY_NODE_TYPES = PRIMARY_KNOWLEDGE_UNIT_TYPES
_SECONDARY_NODE_TYPES = SECONDARY_KNOWLEDGE_UNIT_TYPES


@dataclass
class ResolveResult:
    """Resolution result for one clustered candidate."""

    decision: str
    matched_node_id: int | None = None
    is_content_update: bool = False
    new_aliases: list[str] = field(default_factory=list)


class EntityMatchResponse(BaseModel):
    """Structured LLM result for entity matching."""

    decision: Literal["EXACT", "ALIAS", "NO_MATCH"] = PydanticField(
        description="EXACT / ALIAS / NO_MATCH",
    )


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _has_content_update(candidate_summary: str, existing_summary: str) -> bool:
    """Heuristically detect whether the candidate summary adds new content."""

    if not candidate_summary.strip():
        return False
    if not existing_summary.strip():
        return True

    existing_chars = set(existing_summary)
    new_chars = sum(1 for char in candidate_summary if char not in existing_chars)
    return new_chars > len(candidate_summary) * 0.3


def _get_current_summary(session: Session, node: KnowledgeUnit) -> str:
    """Fetch the current revision summary for a node."""

    if node.id is None:
        return ""
    result = knowledge_unit_repo.get_knowledge_unit_with_current_revision(session, node.id)
    if result is None:
        return ""
    return result[1].summary


async def _llm_entity_match(
    candidate_name: str,
    candidate_type: str,
    candidate_summary: str,
    existing_name: str,
    existing_type: str,
    existing_summary: str,
) -> str:
    """Use the LLM to determine whether two nodes refer to the same entity."""

    user_content = populate_prompt(
        USER_PROMPT_KNOWLEDGE_ENTITY_MATCH,
        candidate_name=candidate_name,
        candidate_type=candidate_type,
        candidate_summary=candidate_summary,
        existing_name=existing_name,
        existing_type=existing_type,
        existing_summary=existing_summary,
    )
    messages: list[ChatMessage] = [
        {"role": SYSTEM, "content": SYSTEM_PROMPT_KNOWLEDGE_ENTITY_MATCH},
        {"role": USER, "content": user_content},
    ]

    try:
        result = await acompletion_structured(
            response_model=EntityMatchResponse,
            messages=messages,
        )
        return result.decision.lower()
    except Exception:
        logger.warning("llm_entity_match_failed", candidate=candidate_name, existing=existing_name)
        return "no_match"


async def _resolve_primary_entity(
    session: Session,
    candidate: ClusteredCandidate,
    subject: str,
    candidate_embedding: list[float],
    similarity_threshold: float,
) -> ResolveResult:
    """Resolve primary KnowledgeUnit candidates."""

    rep = candidate.representative
    normalized_name = normalize_name(rep.name)

    existing = knowledge_unit_repo.find_knowledge_unit_by_normalized_name(
        session,
        subject,
        normalized_name,
        normalize_knowledge_unit_type(rep.knowledge_unit_type),
    )
    if existing is not None:
        existing_summary = _get_current_summary(session, existing)
        return ResolveResult(
            decision="exact",
            matched_node_id=existing.id,
            is_content_update=_has_content_update(candidate.merged_summary, existing_summary),
        )

    normalized_type = normalize_knowledge_unit_type(rep.knowledge_unit_type)
    alias_nodes = knowledge_unit_repo.find_knowledge_units_by_alias(session, subject, normalized_name, normalized_type)
    if alias_nodes:
        matched = alias_nodes[0]
        existing_summary = _get_current_summary(session, matched)
        return ResolveResult(
            decision="alias",
            matched_node_id=matched.id,
            is_content_update=_has_content_update(candidate.merged_summary, existing_summary),
        )

    same_type_nodes = knowledge_unit_repo.list_knowledge_units_by_subject(
        session,
        subject,
        knowledge_unit_type=normalized_type,
        status="active",
        limit=200,
        offset=0,
    )[0]
    if not same_type_nodes or not candidate_embedding:
        return ResolveResult(decision="no_match")

    existing_texts = [
        f"{node.canonical_name}: {_get_current_summary(session, node)}"
        for node in same_type_nodes
    ]
    existing_embeddings = await aembed_texts(existing_texts, soft_fail=True)

    best_similarity = 0.0
    best_node: KnowledgeUnit | None = None
    for node, embedding in zip(same_type_nodes, existing_embeddings):
        similarity = _cosine_similarity(candidate_embedding, embedding)
        if similarity > best_similarity:
            best_similarity = similarity
            best_node = node

    if best_similarity < similarity_threshold or best_node is None:
        return ResolveResult(decision="no_match")

    existing_summary = _get_current_summary(session, best_node)
    decision = await _llm_entity_match(
        candidate_name=rep.name,
        candidate_type=rep.knowledge_unit_type,
        candidate_summary=candidate.merged_summary,
        existing_name=best_node.canonical_name,
        existing_type=best_node.knowledge_unit_type,
        existing_summary=existing_summary,
    )
    if decision not in {"exact", "alias"}:
        return ResolveResult(decision="no_match")

    return ResolveResult(
        decision=decision,
        matched_node_id=best_node.id,
        is_content_update=_has_content_update(candidate.merged_summary, existing_summary),
        new_aliases=[rep.name] if decision == "alias" else [],
    )


async def _resolve_secondary_entity(
    session: Session,
    candidate: ClusteredCandidate,
    subject: str,
    candidate_embedding: list[float],
    candidate_name_to_resolved_node_id: dict[str, int],
) -> ResolveResult:
    """Resolve secondary KnowledgeUnit candidates within their parent scope."""

    rep = candidate.representative
    normalized_name = normalize_name(rep.name)

    normalized_type = normalize_knowledge_unit_type(rep.knowledge_unit_type)
    existing = knowledge_unit_repo.find_knowledge_unit_by_normalized_name(
        session,
        subject,
        normalized_name,
        normalized_type,
    )
    if existing is not None:
        existing_summary = _get_current_summary(session, existing)
        return ResolveResult(
            decision="exact",
            matched_node_id=existing.id,
            is_content_update=_has_content_update(candidate.merged_summary, existing_summary),
        )

    parent_name = rep.parent_entity_name
    if not parent_name:
        return ResolveResult(decision="no_match")

    parent_node_id = candidate_name_to_resolved_node_id.get(parent_name)
    if parent_node_id is None:
        parent_normalized_name = normalize_name(parent_name)
        for parent_type in PARENT_KNOWLEDGE_UNIT_TYPES:
            parent_node = knowledge_unit_repo.find_knowledge_unit_by_normalized_name(
                session,
                subject,
                parent_normalized_name,
                parent_type,
            )
            if parent_node is not None:
                parent_node_id = parent_node.id
                break

    if parent_node_id is None:
        return ResolveResult(decision="no_match")

    edges = knowledge_relation_repo.list_edges_by_knowledge_unit(session, parent_node_id, status="active")
    sibling_node_ids: list[int] = []
    for edge in edges:
        if edge.edge_type not in {"derivation", "example_of"}:
            continue
        if edge.edge_type == "derivation" and edge.target_node_id == parent_node_id:
            sibling_node_ids.append(edge.source_node_id)
        elif edge.edge_type == "example_of" and edge.target_node_id == parent_node_id:
            sibling_node_ids.append(edge.source_node_id)

    if not sibling_node_ids or not candidate_embedding:
        return ResolveResult(decision="no_match")

    siblings: list[KnowledgeUnit] = []
    for sibling_id in sibling_node_ids:
        sibling_node = knowledge_unit_repo.get_knowledge_unit_by_id(session, sibling_id)
        if sibling_node and sibling_node.knowledge_unit_type == normalized_type and sibling_node.status in {"active", "pending"}:
            siblings.append(sibling_node)

    if not siblings:
        return ResolveResult(decision="no_match")

    sibling_texts = [
        f"{sibling.canonical_name}: {_get_current_summary(session, sibling)}"
        for sibling in siblings
    ]
    sibling_embeddings = await aembed_texts(sibling_texts, soft_fail=True)

    best_similarity = 0.0
    best_sibling: KnowledgeUnit | None = None
    for sibling, embedding in zip(siblings, sibling_embeddings):
        similarity = _cosine_similarity(candidate_embedding, embedding)
        if similarity > best_similarity:
            best_similarity = similarity
            best_sibling = sibling

    if best_similarity < _SECONDARY_SIMILARITY_THRESHOLD or best_sibling is None:
        return ResolveResult(decision="no_match")

    existing_summary = _get_current_summary(session, best_sibling)
    return ResolveResult(
        decision="exact",
        matched_node_id=best_sibling.id,
        is_content_update=_has_content_update(candidate.merged_summary, existing_summary),
    )


async def resolve_node(
    session: Session,
    candidate: ClusteredCandidate,
    subject: str,
    candidate_embedding: list[float],
    similarity_threshold: float = _EMBEDDING_SIMILARITY_THRESHOLD,
    *,
    candidate_name_to_resolved_node_id: dict[str, int] | None = None,
) -> ResolveResult:
    """Resolve one clustered candidate against the current subject graph."""

    rep = candidate.representative
    normalized_type = normalize_knowledge_unit_type(rep.knowledge_unit_type)
    rep.knowledge_unit_type = normalized_type
    if normalized_type in _PRIMARY_NODE_TYPES:
        result = await _resolve_primary_entity(
            session,
            candidate,
            subject,
            candidate_embedding,
            similarity_threshold,
        )
    elif normalized_type in _SECONDARY_NODE_TYPES:
        result = await _resolve_secondary_entity(
            session,
            candidate,
            subject,
            candidate_embedding,
            candidate_name_to_resolved_node_id or {},
        )
    else:
        logger.warning("unknown_node_type", knowledge_unit_type=rep.knowledge_unit_type, name=rep.name)
        result = ResolveResult(decision="no_match")

    logger.info(
        "resolve_node_complete",
        name=rep.name,
        knowledge_unit_type=rep.knowledge_unit_type,
        decision=result.decision,
        matched_node_id=result.matched_node_id,
    )
    return result


def compute_edge_confidence(
    active_evidence_count: int,
    contradicting_evidence_count: int = 0,
    max_confidence: float = 0.95,
) -> float:
    """Compute edge confidence from supporting and contradicting evidence."""

    if active_evidence_count == 0:
        return 0.0
    base = 1.0 - 1.0 / (1.0 + active_evidence_count)
    penalty = 0.1 * contradicting_evidence_count
    return max(0.0, min(max_confidence, base - penalty))


def _resolve_edge_endpoint(
    *,
    name: str,
    candidate_id: str | None,
    expected_node_type: str | None,
    scope_hint: str | None,
    candidate_lookup_to_resolved_node_id: dict[str, int],
    candidate_lookup_to_cluster_id: dict[str, int],
    cluster_id_to_resolved_node_id: dict[int, int],
    session: Session,
    subject: str,
) -> int | None:
    """Resolve one edge endpoint to a persisted knowledge node id."""

    normalized_expected_type = normalize_knowledge_unit_type(expected_node_type) if expected_node_type else None
    lookup_keys = [
        candidate_id or "",
        build_candidate_name_key(normalized_expected_type, name, scope=scope_hint)
        if normalized_expected_type
        else "",
        build_candidate_name_key(normalized_expected_type, name, scope=None)
        if normalized_expected_type
        else "",
    ]

    for lookup_key in dict.fromkeys(key for key in lookup_keys if key):
        node_id = candidate_lookup_to_resolved_node_id.get(lookup_key)
        if node_id is not None:
            return node_id

        cluster_id = candidate_lookup_to_cluster_id.get(lookup_key)
        if cluster_id is None:
            continue

        node_id = cluster_id_to_resolved_node_id.get(cluster_id)
        if node_id is not None:
            return node_id

    if not normalized_expected_type:
        return None

    normalized_name = normalize_name(name)
    node = knowledge_unit_repo.find_knowledge_unit_by_normalized_name(
        session,
        subject,
        normalized_name,
        normalized_expected_type,
    )
    if node is None:
        return None
    return node.id


def resolve_edge(
    session: Session,
    candidate: CandidateEdge,
    subject: str,
    candidate_lookup_to_resolved_node_id: dict[str, int],
    candidate_lookup_to_cluster_id: dict[str, int],
    cluster_id_to_resolved_node_id: dict[int, int],
) -> tuple[KnowledgeEdge | None, bool, float]:
    """Resolve one candidate edge against the persisted graph."""

    candidate.edge_type = normalize_relation_type(candidate.edge_type)
    candidate.source_node_type = normalize_knowledge_unit_type(candidate.source_node_type)
    candidate.target_node_type = normalize_knowledge_unit_type(candidate.target_node_type)
    if not validate_relation_direction(
        edge_type=candidate.edge_type,
        source_type=candidate.source_node_type,
        target_type=candidate.target_node_type,
    ):
        logger.warning(
            "edge_invalid_direction",
            source=candidate.source_name,
            target=candidate.target_name,
            edge_type=candidate.edge_type,
            source_type=candidate.source_node_type,
            target_type=candidate.target_node_type,
        )
        return None, False, 0.0

    source_id = _resolve_edge_endpoint(
        name=candidate.source_name,
        candidate_id=candidate.source_candidate_id,
        expected_node_type=candidate.source_node_type,
        scope_hint=None,
        candidate_lookup_to_resolved_node_id=candidate_lookup_to_resolved_node_id,
        candidate_lookup_to_cluster_id=candidate_lookup_to_cluster_id,
        cluster_id_to_resolved_node_id=cluster_id_to_resolved_node_id,
        session=session,
        subject=subject,
    )
    target_id = _resolve_edge_endpoint(
        name=candidate.target_name,
        candidate_id=candidate.target_candidate_id,
        expected_node_type=candidate.target_node_type,
        scope_hint=candidate.source_name if candidate.target_node_type in {"definition", "example"} else None,
        candidate_lookup_to_resolved_node_id=candidate_lookup_to_resolved_node_id,
        candidate_lookup_to_cluster_id=candidate_lookup_to_cluster_id,
        cluster_id_to_resolved_node_id=cluster_id_to_resolved_node_id,
        session=session,
        subject=subject,
    )

    if source_id is None or target_id is None:
        logger.warning(
            "edge_endpoint_unresolved",
            source=candidate.source_name,
            target=candidate.target_name,
            source_resolved=source_id is not None,
            target_resolved=target_id is not None,
        )
        return None, False, 0.0

    if source_id == target_id:
        logger.warning("edge_self_loop", source=candidate.source_name, target=candidate.target_name)
        return None, False, 0.0

    existing_edge = knowledge_relation_repo.find_edge(session, source_id, target_id, candidate.edge_type)
    if existing_edge is not None:
        active_count = knowledge_relation_repo.count_active_evidence(session, "edge", existing_edge.id)
        confidence = compute_edge_confidence(active_count + 1)
        logger.info(
            "edge_matched_existing",
            edge_id=existing_edge.id,
            edge_type=candidate.edge_type,
            new_confidence=confidence,
        )
        return existing_edge, False, confidence

    confidence = compute_edge_confidence(1)
    logger.info(
        "edge_new",
        source_id=source_id,
        target_id=target_id,
        edge_type=candidate.edge_type,
        confidence=confidence,
    )
    new_edge = KnowledgeEdge(
        subject=subject,
        source_node_id=source_id,
        target_node_id=target_id,
        edge_type=candidate.edge_type,
        confidence=confidence,
        status="pending",
    )
    return new_edge, True, confidence


__all__ = [
    "ResolveResult",
    "compute_edge_confidence",
    "resolve_edge",
    "resolve_node",
]




