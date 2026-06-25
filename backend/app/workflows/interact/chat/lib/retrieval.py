"""KnowledgeUnit-first retrieval helpers for the interact workflow."""

from __future__ import annotations

import math
import re
from pathlib import Path

import structlog
from sqlmodel import Session, or_, select

from app.models import RawFile, RetrievalChunk
from app.repositories.files_repo import list_raw_files_by_ids_for_user
from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.repositories import knowledge_relation_repo, knowledge_repo, knowledge_unit_repo, profile_repo
from app.shared.infra.observability.trace import traceable_with_context as traceable
from app.utils.course import is_global_course
from app.workflows.interact.chat.lib.types import RetrievedContext

logger = structlog.get_logger(__name__)

_TOKEN_RE = re.compile(r"[\w]+|[\u4e00-\u9fff]", re.UNICODE)
_CJK_PHRASE_RE = re.compile(r"[\u4e00-\u9fff]{2,}", re.UNICODE)
_ASCII_TERM_RE = re.compile(r"[A-Za-z0-9_]{2,}", re.UNICODE)
_KG_UNIT_CANDIDATE_LIMIT = 1200
_KG_UNIT_SUPPLEMENT_LIMIT = 500
_KG_UNIT_SEARCH_TERM_LIMIT = 8
_ATTACHED_FILE_MAX_CHARS = 3600
_ATTACHED_FILE_TOTAL_MAX_CHARS = 12000


def _trace_retrieval_inputs(inputs: dict[str, object]) -> dict[str, object]:
    query = str(inputs.get("query") or "")
    return {
        "course_id": inputs.get("course_id"),
        "query_preview": query[:500],
        "query_chars": len(query),
        "top_k": inputs.get("top_k"),
        "similarity_threshold": inputs.get("similarity_threshold"),
        "user_id": inputs.get("user_id"),
        "attached_file_count": len(inputs.get("attached_file_ids") or []),
    }


def _trace_retrieval_outputs(outputs: object) -> dict[str, object]:
    results = outputs if isinstance(outputs, list) else []
    return {
        "result_count": len(results),
        "results": [
            {
                "title": item.title,
                "source": item.retrieval_source,
                "score": round(item.score, 4),
                "low_relevance": item.low_relevance,
                "knowledge_unit_id": item.knowledge_unit_id,
            }
            for item in results[:8]
            if isinstance(item, RetrievedContext)
        ],
    }


def _trace_kg_inputs(inputs: dict[str, object]) -> dict[str, object]:
    return _trace_retrieval_inputs(inputs)


def _trace_vector_inputs(inputs: dict[str, object]) -> dict[str, object]:
    return _trace_retrieval_inputs(inputs)


@traceable(
    name="interact.retrieval.route",
    run_type="retriever",
    process_inputs=_trace_retrieval_inputs,
    process_outputs=_trace_retrieval_outputs,
)
async def retrieve_context(
    *,
    session: Session,
    query: str,
    course_id: str,
    top_k: int,
    similarity_threshold: float,
    user_id: str = "local",
    attached_file_ids: list[str] | None = None,
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
    attached_contexts = _retrieve_attached_file_context(
        session,
        user_id=user_id,
        attached_file_ids=attached_file_ids or [],
    )
    if is_global_course(course_id):
        if attached_contexts:
            logger.info(
                "interact_attached_file_retrieval_done",
                course_id=course_id,
                query_len=len(normalized_query),
                attached_file_count=len(attached_file_ids or []),
                result_count=len(attached_contexts),
            )
            return attached_contexts[:top_k]
        logger.info(
            "interact_retrieval_skipped",
            course_id=course_id,
            reason="global_chat_scope",
        )
        return []

    graph_results = _retrieve_knowledge_unit_context(
        session,
        query=normalized_query,
        course_id=course_id,
        top_k=top_k,
        user_id=user_id,
        similarity_threshold=similarity_threshold,
    )
    if graph_results:
        if len(graph_results) < top_k or all(item.low_relevance for item in graph_results):
            vector_results = await _retrieve_vector_context(
                session=session,
                query=normalized_query,
                course_id=course_id,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
            )
            merged_results = _merge_context_results(graph_results, vector_results, top_k=top_k)
            logger.info(
                "interact_kg_vector_retrieval_done",
                course_id=course_id,
                query_len=len(normalized_query),
                graph_result_count=len(graph_results),
                vector_result_count=len(vector_results),
                result_count=len(merged_results),
            )
            return _merge_context_results(attached_contexts, merged_results, top_k=top_k)
        logger.info(
            "interact_kg_retrieval_done",
            course_id=course_id,
            query_len=len(normalized_query),
            result_count=len(graph_results),
        )
        return _merge_context_results(attached_contexts, graph_results, top_k=top_k)

    vector_results = await _retrieve_vector_context(
        session=session,
        query=normalized_query,
        course_id=course_id,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
    )
    logger.info(
        "interact_retrieval_done",
        course_id=course_id,
        query_len=len(normalized_query),
        result_count=len(vector_results),
        source="vector_fallback",
    )
    return _merge_context_results(attached_contexts, vector_results, top_k=top_k)


def _retrieve_attached_file_context(
    session: Session,
    *,
    user_id: str,
    attached_file_ids: list[str],
) -> list[RetrievedContext]:
    file_ids = _normalize_attached_file_ids(attached_file_ids)
    if not file_ids:
        return []

    raw_files = list_raw_files_by_ids_for_user(session, user_id=user_id, file_ids=file_ids)
    file_by_id = {raw_file.id: raw_file for raw_file in raw_files}
    results: list[RetrievedContext] = []
    remaining_chars = _ATTACHED_FILE_TOTAL_MAX_CHARS

    for file_id in file_ids:
        if remaining_chars <= 0:
            break
        raw_file = file_by_id.get(file_id)
        if raw_file is None:
            continue
        markdown = _raw_file_markdown(raw_file)
        if not markdown:
            continue
        excerpt = _clip_attached_file_markdown(markdown, max_chars=min(_ATTACHED_FILE_MAX_CHARS, remaining_chars))
        if not excerpt:
            continue
        results.append(
            RetrievedContext(
                chunk_id=0,
                file_id=file_id,
                title=raw_file.filename,
                header_path=raw_file.filename,
                content=excerpt,
                score=1.0,
                low_relevance=False,
                retrieval_source="attached_file",
            )
        )
        remaining_chars -= len(excerpt)

    return results


def _normalize_attached_file_ids(file_ids: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for file_id in file_ids:
        value = str(file_id or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _raw_file_markdown(raw_file: RawFile) -> str:
    markdown = str(raw_file.parsed_markdown or "").strip()
    if markdown:
        return markdown
    markdown_path = str(raw_file.markdown_path or "").strip()
    if not markdown_path:
        return ""
    try:
        path = Path(markdown_path)
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning(
            "interact_attached_file_markdown_read_failed",
            file_id=raw_file.id,
            markdown_path=markdown_path,
            error=str(exc),
        )
    return ""


def _clip_attached_file_markdown(markdown: str, *, max_chars: int) -> str:
    normalized = "\n".join(line.rstrip() for line in markdown.strip().splitlines())
    if len(normalized) <= max_chars:
        return normalized
    return f"{normalized[:max_chars].rstrip()}\n\n（资料内容较长，本轮仅截取前 {max_chars} 字作为上下文。）"


def _merge_context_results(
    graph_results: list[RetrievedContext],
    vector_results: list[RetrievedContext],
    *,
    top_k: int,
) -> list[RetrievedContext]:
    merged: list[RetrievedContext] = []
    seen: set[tuple[str, int]] = set()
    strong_graph_results = [item for item in graph_results if not item.low_relevance]
    weak_graph_results = [item for item in graph_results if item.low_relevance]
    for item in [*strong_graph_results, *vector_results, *weak_graph_results]:
        keys = _context_result_keys(item)
        if seen & keys:
            continue
        seen.update(keys)
        merged.append(item)
        if len(merged) >= top_k:
            break
    return merged


def _context_result_keys(item: RetrievedContext) -> set[tuple[str, int]]:
    keys: set[tuple[str, int]] = set()
    if item.knowledge_unit_id is not None:
        keys.add(("unit", int(item.knowledge_unit_id)))
    if item.chunk_id:
        keys.add(("chunk", int(item.chunk_id)))
    if not keys:
        keys.add(("content", hash((item.title, item.content[:160]))))
    return keys


@traceable(
    name="interact.retrieval.knowledge_unit_search",
    run_type="retriever",
    process_inputs=_trace_kg_inputs,
    process_outputs=_trace_retrieval_outputs,
)
def _retrieve_knowledge_unit_context(
    session: Session,
    *,
    query: str,
    course_id: str,
    top_k: int,
    user_id: str,
    similarity_threshold: float,
) -> list[RetrievedContext]:
    units = _candidate_units_for_query(session, course_id=course_id, query=query, top_k=top_k)
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
    edges = knowledge_relation_repo.list_edges_for_knowledge_units(session, course_id, center_ids)
    related_ids = {
        edge.target_node_id if edge.source_node_id in center_ids else edge.source_node_id
        for edge in edges
        if edge.source_node_id in center_ids or edge.target_node_id in center_ids
    }
    missing_related_ids = {unit_id for unit_id in related_ids if unit_id not in unit_by_id}
    if missing_related_ids:
        unit_by_id.update(
            {
                int(unit.id): unit
                for unit in _fetch_units_by_ids(session, course_id=course_id, unit_ids=missing_related_ids)
                if unit.id is not None
            }
        )
    selected_scores: dict[int, float] = {
        int(unit.id): score for unit, score in ranked[:top_k] if unit.id is not None
    }
    relation_paths: dict[int, str] = {}

    for edge in edges:
        if edge.source_node_id in center_ids and edge.target_node_id in unit_by_id:
            _add_related_unit(edge.target_node_id, edge, unit_by_id, selected_scores, relation_paths, selected_scores[edge.source_node_id])
        if edge.target_node_id in center_ids and edge.source_node_id in unit_by_id:
            _add_related_unit(edge.source_node_id, edge, unit_by_id, selected_scores, relation_paths, selected_scores[edge.target_node_id])

    mastery = _mastery_by_unit_id(session, course_id=course_id, user_id=user_id)
    ordered_ids = sorted(
        selected_scores,
        key=lambda unit_id: (
            mastery.get(unit_id, 1.0),
            -selected_scores[unit_id],
            unit_id,
        ),
    )[:top_k]
    selected_units = [
        (
            unit_by_id[unit_id],
            selected_scores[unit_id],
            relation_paths.get(unit_id),
            mastery.get(unit_id),
        )
        for unit_id in ordered_ids
        if unit_id in unit_by_id
    ]
    return _contexts_from_units(session, selected_units)


def _candidate_units_for_query(
    session: Session,
    *,
    course_id: str,
    query: str,
    top_k: int,
) -> list[KnowledgeUnit]:
    limit = max(80, min(_KG_UNIT_CANDIDATE_LIMIT, max(1, top_k) * 120))
    terms = _candidate_search_terms(query)
    units: list[KnowledgeUnit] = []

    if terms:
        predicates = []
        for term in terms:
            pattern = f"%{term}%"
            predicates.extend(
                [
                    KnowledgeUnit.canonical_name.ilike(pattern),
                    KnowledgeUnit.normalized_name.ilike(pattern),
                    KnowledgeUnit.summary.ilike(pattern),
                    KnowledgeUnit.body_markdown.ilike(pattern),
                    KnowledgeUnit.body.ilike(pattern),
                ]
            )
        stmt = (
            select(KnowledgeUnit)
            .where(
                KnowledgeUnit.course_id == course_id,
                KnowledgeUnit.status == "active",
                or_(*predicates),
            )
            .order_by(KnowledgeUnit.id)
            .limit(limit)
        )
        units = list(session.exec(stmt).all())

    if len(units) < min(limit, top_k * 20):
        supplement, _ = knowledge_unit_repo.list_knowledge_units_by_course(
            session,
            course_id,
            status="active",
            limit=min(_KG_UNIT_SUPPLEMENT_LIMIT, limit),
            offset=0,
        )
        units = _dedupe_units([*units, *supplement])
    return units


def _candidate_search_terms(query: str) -> list[str]:
    cleaned = " ".join(str(query or "").split()).strip()
    terms: list[str] = []
    if 1 < len(cleaned) <= 80:
        terms.append(cleaned)
    terms.extend(match.group(0) for match in _CJK_PHRASE_RE.finditer(cleaned))
    terms.extend(match.group(0).casefold() for match in _ASCII_TERM_RE.finditer(cleaned))

    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.strip().casefold()
        if len(normalized) < 2 or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(term.strip())
        if len(deduped) >= _KG_UNIT_SEARCH_TERM_LIMIT:
            break
    return deduped


def _dedupe_units(units: list[KnowledgeUnit]) -> list[KnowledgeUnit]:
    deduped: list[KnowledgeUnit] = []
    seen: set[int] = set()
    for unit in units:
        if unit.id is None or int(unit.id) in seen:
            continue
        seen.add(int(unit.id))
        deduped.append(unit)
    return deduped


def _fetch_units_by_ids(
    session: Session,
    *,
    course_id: str,
    unit_ids: set[int],
) -> list[KnowledgeUnit]:
    normalized_ids = {int(unit_id) for unit_id in unit_ids if int(unit_id or 0) > 0}
    if not normalized_ids:
        return []
    stmt = select(KnowledgeUnit).where(
        KnowledgeUnit.course_id == course_id,
        KnowledgeUnit.status == "active",
        KnowledgeUnit.id.in_(normalized_ids),
    )
    return list(session.exec(stmt).all())


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


def _mastery_by_unit_id(session: Session, *, course_id: str, user_id: str) -> dict[int, float]:
    return {
        int(state.knowledge_unit_id): float(state.mastery_score)
        for state in profile_repo.list_knowledge_states(
            session,
            user_id=user_id,
            course_id=course_id,
            target_kind="knowledge_unit",
        )
        if state.knowledge_unit_id is not None
    }


def _contexts_from_units(
    session: Session,
    selected_units: list[tuple[KnowledgeUnit, float, str | None, float | None]],
) -> list[RetrievedContext]:
    evidence_by_unit_id = {
        int(unit.id): _first_unit_evidence(session, unit)
        for unit, _, _, _ in selected_units
        if unit.id is not None
    }
    chunk_ids = [
        int(evidence["chunk_id"])
        for evidence in evidence_by_unit_id.values()
        if int(evidence.get("chunk_id") or 0) > 0
    ]
    chunk_by_id = {
        int(chunk.id): chunk
        for chunk in knowledge_repo.get_chunks_by_ids(session, chunk_ids)
        if chunk.id is not None
    }
    return [
        _context_from_unit(
            unit,
            score=score,
            relation_path=relation_path,
            mastery_score=mastery_score,
            evidence=evidence_by_unit_id.get(int(unit.id or 0), {"chunk_id": 0, "file_id": "", "quote_text": ""}),
            chunk_by_id=chunk_by_id,
        )
        for unit, score, relation_path, mastery_score in selected_units
    ]


def _context_from_unit(
    unit: KnowledgeUnit,
    *,
    score: float,
    relation_path: str | None,
    mastery_score: float | None,
    evidence: dict[str, object],
    chunk_by_id: dict[int, RetrievalChunk],
) -> RetrievedContext:
    chunk = chunk_by_id.get(int(evidence["chunk_id"] or 0)) if evidence["chunk_id"] else None
    content = ""
    title = unit.canonical_name
    header_path = unit.canonical_name
    chunk_id = int(evidence["chunk_id"] or 0)
    file_id = str(evidence["file_id"] or "")

    if chunk is not None and chunk.course_id == unit.course_id:
        content = chunk.content
        title = chunk.title or unit.canonical_name
        header_path = chunk.header_path or unit.canonical_name
        chunk_id = int(chunk.id or chunk_id)
        file_id = chunk.file_id
    else:
        content = unit.body_markdown or unit.body or unit.summary or unit.canonical_name

    return RetrievedContext(
        chunk_id=chunk_id,
        file_id=file_id,
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
        return {"chunk_id": 0, "file_id": "", "quote_text": ""}
    evidence_items = knowledge_relation_repo.list_evidence_by_entity(session, "node", int(unit.id))
    if not evidence_items:
        return {"chunk_id": 0, "file_id": "", "quote_text": ""}
    first = sorted(evidence_items, key=lambda item: (-item.confidence, item.id or 0))[0]
    return {
        "chunk_id": first.chunk_id,
        "file_id": first.file_id,
        "quote_text": first.quote_text,
    }


@traceable(
    name="interact.retrieval.vector_fallback_search",
    run_type="retriever",
    process_inputs=_trace_vector_inputs,
    process_outputs=_trace_retrieval_outputs,
)
async def _retrieve_vector_context(
    *,
    session: Session,
    query: str,
    course_id: str,
    top_k: int,
    similarity_threshold: float,
) -> list[RetrievedContext]:
    del session
    from app.shared.infra.search.api import search_knowledge

    try:
        chunks = await search_knowledge(
            query,
            course_id,
            top_k=top_k,
            enable_rerank=True,
        )
    except Exception as exc:
        logger.warning(
            "interact_vector_retrieval_soft_failed",
            course_id=course_id,
            error=str(exc),
            fallback="graph_only",
        )
        return []

    results: list[RetrievedContext] = []
    for chunk in chunks:
        score = float(chunk.score or 0.0)
        if score < similarity_threshold:
            continue
        results.append(
            RetrievedContext(
                chunk_id=chunk.chunk_id,
                file_id=chunk.file_id,
                title=chunk.title,
                header_path=chunk.header_path,
                content=chunk.content,
                score=score,
                low_relevance=score < similarity_threshold * 1.5,
                retrieval_source="vector",
            )
        )

    return results


__all__ = ["retrieve_context"]
