"""Aggregated knowledge overview derived from the knowledge-graph lane."""

from __future__ import annotations

from sqlmodel import Session

from app.schemas.knowledge import (
    FullGraphResponse,
    KnowledgeOverviewResponse,
    KnowledgeOverviewStats,
)
from app.repositories import knowledge_relation_repo, knowledge_unit_repo
from app.shared.infra.course import get_course_vector_status_by_id
from app.utils.time import utcnow
from app.workflows.digest.kg_doc_sync.lib.query import get_full_graph, get_visible_graph_counts

_DEFAULT_OVERVIEW_SECTIONS = {
    "graph",
    "stats",
}


def _resolve_sections(include: list[str] | None, full: bool) -> set[str]:
    if full or not include:
        return set(_DEFAULT_OVERVIEW_SECTIONS) if full else set()
    return {item.strip().lower() for item in include if item and item.strip()}


def get_knowledge_overview(
    session: Session,
    *,
    course_id: str,
    include: list[str] | None = None,
    full: bool = True,
) -> KnowledgeOverviewResponse:
    """Return one aggregated payload for summary tabs."""

    sections = _resolve_sections(include, full)

    need_graph = "graph" in sections
    need_stats = "stats" in sections

    graph: FullGraphResponse | None = None

    if need_graph:
        graph = get_full_graph(session, course_id=course_id)

    if graph is not None:
        node_count = len(graph.nodes)
        edge_count = len(graph.edges)
    elif need_stats:
        node_count, edge_count = get_visible_graph_counts(session, course_id=course_id)
    else:
        node_count = knowledge_unit_repo.count_knowledge_units_by_course(session, course_id)
        edge_count = knowledge_relation_repo.count_edges_by_course(session, course_id)

    stats = KnowledgeOverviewStats(node_count=node_count, edge_count=edge_count)

    return KnowledgeOverviewResponse(
        course_id=course_id,
        generated_at=utcnow(),
        graph=graph if "graph" in sections else None,
        stats=stats if "stats" in sections else KnowledgeOverviewStats(),
        vector_status=get_course_vector_status_by_id(session, course_id),
    )


__all__ = ["get_knowledge_overview"]
