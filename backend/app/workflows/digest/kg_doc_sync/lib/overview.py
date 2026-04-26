"""Aggregated knowledge overview derived from the knowledge-graph lane."""

from __future__ import annotations

from sqlmodel import Session

from app.schemas.knowledge import (
    FullGraphResponse,
    KnowledgeOverviewResponse,
    KnowledgeOverviewStats,
)
from app.shared.infra.subject import get_subject_vector_status_by_slug
from app.utils.time import utcnow
from app.workflows.digest.kg_doc_sync.lib.query import get_full_graph

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
    subject: str,
    include: list[str] | None = None,
    full: bool = True,
) -> KnowledgeOverviewResponse:
    """Return one aggregated payload for summary tabs."""

    sections = _resolve_sections(include, full)

    need_graph = "graph" in sections
    need_stats = "stats" in sections

    if need_stats:
        need_graph = True

    graph: FullGraphResponse | None = None

    if need_graph:
        graph = get_full_graph(session, subject=subject)

    stats = KnowledgeOverviewStats(
        node_count=len(graph.nodes) if graph is not None else 0,
        edge_count=len(graph.edges) if graph is not None else 0,
    )

    return KnowledgeOverviewResponse(
        subject=subject,
        generated_at=utcnow(),
        graph=graph if "graph" in sections else None,
        stats=stats if "stats" in sections else KnowledgeOverviewStats(),
        vector_status=get_subject_vector_status_by_slug(session, subject),
    )


__all__ = ["get_knowledge_overview"]
