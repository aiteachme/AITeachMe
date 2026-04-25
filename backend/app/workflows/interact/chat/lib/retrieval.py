"""KnowledgeUnit-first retrieval helpers for the interact workflow."""

from __future__ import annotations

import math
import re

import structlog
from sqlmodel import Session

from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.repositories import knowledge_relation_repo, knowledge_repo, knowledge_unit_repo, profile_repo
from app.shared.infra.subject import get_subject_vector_search_notice
from app.workflows.interact.chat.lib.types import RetrievedContext

logger = structlog.get_logger(__name__)

_TOKEN_RE = re.compile(r"[\w]+|[\u4e00-\u9fff]", re.UNICODE)


async def retrieve_context(
    *,
    session: Session,
    query: str,
    subject: str,
    top_k: int,
    similarity_threshold: float,
    user_id: str = "local",
) -> list[RetrievedContext]:
    """Retrieve prompt-ready context with KnowledgeUnit as the primary unit.

    The retrieval order is:
    1. match KnowledgeUnits;
    2. expand the matched units through KG edges;
    3. backtrack each selected unit to evidence chunks or unit body text;
    4. fall back to legacy vector chunk retrieval only when the graph has no hit.
    """

    normalized_query = query.strip()
    if not normalized_query or top_k <= 0:
        return []
    if not subject.strip():
        logger.info(
            "interact_retrieval_skipped",
            subject=subject,
            reason="global_chat_scope",
        )
        return []

    graph_results = _retrieve_knowledge_unit_context(
        session,
        query=normalized_query,
        subject=subject,
        top_k=top_k,
        user_id=user_id,
        similarity_threshold=similarity_threshold,
    )
    if graph_results:
        logger.info(
            "interact_kg_retrieval_done",
            subject=subject,
            query_len=len(normalized_query),
            result_count=len(graph_results),
        )
        return graph_results

    vector_results = await _retrieve_vector_context(
        session=session,
        query=normalized_query,
        subject=subject,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
    )
    logger.info(
        "interact_retrieval_done",
        subject=subject,
        query_len=len(normalized_query),
        result_count=len(vector_results),
        source="vector_fallback",
    )
    return vector_results


def _retrieve_knowledge_unit_context(
    session: Session,
    *,
    query: str,
    subject: str,
    top_k: int,
    user_id: str,
    similarity_threshold: float,
) -> list[RetrievedContext]:
    units, _ = knowledge_unit_repo.list_knowledge_units_by_subject(
        session,
        subject,
        status="active",
        limit=500,
        offset=0,
    )
    if not units:
        return []

    ranked = [
        (unit, score)
        for unit in units
        if (score := _score_unit(query, unit)) >= max(0.05, similarity_threshold * 0.25)
    ]
    ranked.sort(key=lambda item: (-item[1], item[0].id or 0))
    if not ranked:
        return []

    center_count = max(1, min(3, top_k))
    center_ids = {unit.id for unit, _ in ranked[:center_count] if unit.id is not None}
    unit_by_id = {unit.id: unit for unit in units if unit.id is not None}
    edges = knowledge_relation_repo.list_all_edges_by_subject(session, subject)
    selected_scores: dict[int, float] = {
        int(unit.id): score for unit, score in ranked[:top_k] if unit.id is not None
    }
    relation_paths: dict[int, str] = {}

    for edge in edges:
        if edge.source_node_id in center_ids and edge.target_node_id in unit_by_id:
            _add_related_unit(edge.target_node_id, edge, unit_by_id, selected_scores, relation_paths, selected_scores[edge.source_node_id])
        if edge.target_node_id in center_ids and edge.source_node_id in unit_by_id:
            _add_related_unit(edge.source_node_id, edge, unit_by_id, selected_scores, relation_paths, selected_scores[edge.target_node_id])

    mastery = _mastery_by_unit_id(session, subject=subject, user_id=user_id)
    ordered_ids = sorted(
        selected_scores,
        key=lambda unit_id: (
            mastery.get(unit_id, 1.0),
            -selected_scores[unit_id],
            unit_id,
        ),
    )[:top_k]
    return [
        _context_from_unit(
            session,
            unit_by_id[unit_id],
            score=selected_scores[unit_id],
            relation_path=relation_paths.get(unit_id),
            mastery_score=mastery.get(unit_id),
        )
        for unit_id in ordered_ids
        if unit_id in unit_by_id
    ]


def _add_related_unit(
    related_id: int,
    edge: KnowledgeEdge,
    unit_by_id: dict[int | None, KnowledgeUnit],
    selected_scores: dict[int, float],
    relation_paths: dict[int, str],
    center_score: float,
) -> None:
    if related_id not in unit_by_id:
        return
    related_score = max(0.05, center_score * float(edge.weight or 1.0) * 0.72)
    source = unit_by_id.get(edge.source_node_id)
    target = unit_by_id.get(edge.target_node_id)
    source_name = source.canonical_name if source else f"KnowledgeUnit#{edge.source_node_id}"
    target_name = target.canonical_name if target else f"KnowledgeUnit#{edge.target_node_id}"
    relation_path = f"{source_name} -[{edge.edge_type}]-> {target_name}"
    if related_score > selected_scores.get(related_id, 0.0):
        selected_scores[related_id] = related_score
    relation_paths.setdefault(related_id, relation_path)


def _score_unit(query: str, unit: KnowledgeUnit) -> float:
    haystack = " ".join(
        [
            unit.canonical_name,
            unit.normalized_name,
            unit.summary,
            unit.body_markdown,
            unit.body,
        ]
    ).casefold()
    needle = query.casefold()
    score = 0.0
    if needle and needle in haystack:
        score += 1.0
    if unit.canonical_name.casefold() in needle:
        score += 1.5

    query_tokens = set(_tokens(needle))
    haystack_tokens = set(_tokens(haystack))
    if query_tokens and haystack_tokens:
        overlap = query_tokens & haystack_tokens
        score += len(overlap) / math.sqrt(len(query_tokens) * len(haystack_tokens))
    return min(score, 1.0)


def _tokens(text: str) -> list[str]:
    return [match.group(0).casefold() for match in _TOKEN_RE.finditer(text)]


def _mastery_by_unit_id(session: Session, *, subject: str, user_id: str) -> dict[int, float]:
    return {
        int(state.knowledge_unit_id): float(state.mastery_score)
        for state in profile_repo.list_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            target_kind="node",
        )
        if state.knowledge_unit_id is not None
    }


def _context_from_unit(
    session: Session,
    unit: KnowledgeUnit,
    *,
    score: float,
    relation_path: str | None,
    mastery_score: float | None,
) -> RetrievedContext:
    evidence = _first_unit_evidence(session, unit)
    chunk = knowledge_repo.get_chunk_by_id(session, evidence["chunk_id"]) if evidence["chunk_id"] else None
    content = ""
    title = unit.canonical_name
    header_path = unit.canonical_name
    chunk_id = int(evidence["chunk_id"] or 0)
    document_id = int(evidence["document_id"] or 0)

    if chunk is not None and chunk.subject == unit.subject:
        content = chunk.content
        title = chunk.title or unit.canonical_name
        header_path = chunk.header_path or unit.canonical_name
        chunk_id = int(chunk.id or chunk_id)
        document_id = int(chunk.document_id)
    else:
        content = unit.body_markdown or unit.body or unit.summary or unit.canonical_name

    return RetrievedContext(
        chunk_id=chunk_id,
        document_id=document_id,
        title=title,
        header_path=header_path,
        content=content,
        score=score,
        low_relevance=score < 0.45,
        knowledge_unit_id=unit.id,
        knowledge_unit_name=unit.canonical_name,
        knowledge_unit_type=unit.knowledge_unit_type,
        relation_path=relation_path,
        evidence_quote=str(evidence["quote_text"] or "") or None,
        mastery_score=mastery_score,
        retrieval_source="knowledge_unit",
    )


def _first_unit_evidence(session: Session, unit: KnowledgeUnit) -> dict[str, object]:
    if unit.id is None:
        return {"chunk_id": 0, "document_id": 0, "quote_text": ""}
    evidence_items = knowledge_relation_repo.list_evidence_by_entity(session, "node", int(unit.id))
    if not evidence_items:
        return {"chunk_id": 0, "document_id": 0, "quote_text": ""}
    first = sorted(evidence_items, key=lambda item: (-item.confidence, item.id or 0))[0]
    return {
        "chunk_id": first.chunk_id,
        "document_id": first.document_id,
        "quote_text": first.quote_text,
    }


async def _retrieve_vector_context(
    *,
    session: Session,
    query: str,
    subject: str,
    top_k: int,
    similarity_threshold: float,
) -> list[RetrievedContext]:
    search_notice = get_subject_vector_search_notice(session, subject_slug=subject)
    if search_notice is not None:
        logger.info(
            "interact_vector_retrieval_skipped",
            subject=subject,
            reason=search_notice,
        )
        return []

    from app.shared.infra.search.llamaindex_adapter import build_knowledge_retriever

    try:
        retriever = build_knowledge_retriever(subject=subject, top_k=top_k)
        nodes = await retriever.aretrieve(query)
    except Exception as exc:
        logger.warning(
            "interact_vector_retrieval_soft_failed",
            subject=subject,
            error=str(exc),
            fallback="graph_only",
        )
        return []

    results: list[RetrievedContext] = []
    for node_with_score in nodes:
        node = node_with_score.node
        score = node_with_score.score or 0.0
        metadata = node.metadata or {}
        if score < similarity_threshold:
            continue
        results.append(
            RetrievedContext(
                chunk_id=int(metadata.get("chunk_id", 0)),
                document_id=int(metadata.get("document_id", 0)),
                title=str(metadata.get("title", "")),
                header_path=str(metadata.get("header_path", "")),
                content=node.get_content(),
                score=score,
                low_relevance=score < similarity_threshold * 1.5,
                retrieval_source="vector",
            )
        )

    return results


__all__ = ["retrieve_context"]
