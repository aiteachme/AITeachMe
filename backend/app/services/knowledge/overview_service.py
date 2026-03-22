"""Knowledge overview aggregation service."""

from __future__ import annotations

from sqlmodel import Session, select

from app.core.exceptions import (
    NoPublishedCurriculumSnapshotError,
    NoPublishedDagError,
    NoPublishedTreeError,
)
from app.models.curriculum import CurriculumDeriveJob
from app.models.knowledge_graph import GraphDigestJob
from app.schemas.knowledge import (
    CurriculumSnapshotResponse,
    FullGraphResponse,
    KnowledgeOverviewBuildStatus,
    KnowledgeOverviewResponse,
    KnowledgeOverviewStats,
    PrereqDagResponse,
    TeachingUnitResponse,
    ThemeTreeNodeResponse,
    ThemeTreeResponse,
)
from app.services.knowledge.curriculum_service import (
    get_current_curriculum_snapshot,
    get_current_prereq_dag,
    get_current_theme_tree,
    get_teaching_units,
)
from app.services.knowledge.graph_query_service import get_full_graph
from app.utils.time import utcnow


_DEFAULT_OVERVIEW_SECTIONS = {
    "snapshot",
    "theme_tree",
    "prereq_dag",
    "graph",
    "units",
    "stats",
    "build_status",
}

_TERMINAL_STATUSES = {"completed", "failed"}


def _count_theme_nodes(nodes: list[ThemeTreeNodeResponse]) -> int:
    total = 0
    for node in nodes:
        total += 1
        total += _count_theme_nodes(node.children or [])
    return total


def _resolve_sections(include: list[str] | None, full: bool) -> set[str]:
    if full or not include:
        return set(_DEFAULT_OVERVIEW_SECTIONS)
    return {item.strip().lower() for item in include if item and item.strip()}


def _resolve_overview_build_status(
    session: Session,
    *,
    subject: str,
    job_id: int | None,
) -> KnowledgeOverviewBuildStatus | None:
    graph_job: GraphDigestJob | None = None
    if job_id is not None:
        candidate = session.get(GraphDigestJob, job_id)
        if candidate is not None and candidate.subject == subject:
            graph_job = candidate
    else:
        graph_job = session.exec(
            select(GraphDigestJob)
            .where(GraphDigestJob.subject == subject)
            .order_by(GraphDigestJob.created_at.desc())
        ).first()

    if graph_job is None or graph_job.id is None:
        return None

    curriculum_job: CurriculumDeriveJob | None = None
    if graph_job.curriculum_job_id is not None:
        candidate = session.get(CurriculumDeriveJob, graph_job.curriculum_job_id)
        if candidate is not None and candidate.subject == subject:
            curriculum_job = candidate

    graph_status = graph_job.status
    curriculum_status = curriculum_job.status if curriculum_job is not None else None
    graph_terminal = graph_status in _TERMINAL_STATUSES
    curriculum_terminal = (
        curriculum_status is None or curriculum_status in _TERMINAL_STATUSES
    )
    is_terminal = graph_terminal and curriculum_terminal
    is_success = graph_status == "completed" and (
        curriculum_status is None or curriculum_status == "completed"
    )
    error_message = graph_job.error_message or (
        curriculum_job.error_message if curriculum_job is not None else None
    )

    return KnowledgeOverviewBuildStatus(
        graph_job_id=graph_job.id,
        graph_status=graph_status,
        curriculum_job_id=curriculum_job.id if curriculum_job is not None else None,
        curriculum_status=curriculum_status,
        is_terminal=is_terminal,
        is_success=is_success,
        error_message=error_message,
    )


def get_knowledge_overview(
    session: Session,
    *,
    subject: str,
    include: list[str] | None = None,
    full: bool = True,
    job_id: int | None = None,
) -> KnowledgeOverviewResponse:
    """Return one aggregated payload for summary tabs."""

    sections = _resolve_sections(include, full)

    need_snapshot = "snapshot" in sections
    need_theme_tree = "theme_tree" in sections
    need_prereq_dag = "prereq_dag" in sections
    need_graph = "graph" in sections
    need_units = "units" in sections
    need_stats = "stats" in sections
    need_build_status = "build_status" in sections

    if need_stats:
        need_theme_tree = True
        need_prereq_dag = True
        need_graph = True
        need_units = True

    snapshot: CurriculumSnapshotResponse | None = None
    theme_tree: ThemeTreeResponse | None = None
    prereq_dag: PrereqDagResponse | None = None
    graph: FullGraphResponse | None = None
    units: list[TeachingUnitResponse] = []
    build_status: KnowledgeOverviewBuildStatus | None = None

    if need_snapshot:
        try:
            snapshot = get_current_curriculum_snapshot(session, subject=subject)
        except NoPublishedCurriculumSnapshotError:
            snapshot = None

    if need_theme_tree:
        try:
            theme_tree = get_current_theme_tree(session, subject=subject)
        except NoPublishedTreeError:
            theme_tree = None

    if need_prereq_dag:
        try:
            prereq_dag = get_current_prereq_dag(session, subject=subject)
        except NoPublishedDagError:
            prereq_dag = None

    if need_graph:
        graph = get_full_graph(session, subject=subject)

    if need_units:
        units = get_teaching_units(
            session,
            subject=subject,
            status="active",
            page=1,
            size=5000,
        ).items

    if need_build_status:
        build_status = _resolve_overview_build_status(
            session,
            subject=subject,
            job_id=job_id,
        )

    stats = KnowledgeOverviewStats(
        node_count=len(graph.nodes) if graph is not None else 0,
        edge_count=len(graph.edges) if graph is not None else 0,
        unit_count=len(units),
        theme_node_count=_count_theme_nodes(theme_tree.tree) if theme_tree is not None else 0,
        dependency_count=len(prereq_dag.dependencies) if prereq_dag is not None else 0,
    )

    return KnowledgeOverviewResponse(
        subject=subject,
        generated_at=utcnow(),
        snapshot=snapshot,
        theme_tree=theme_tree if "theme_tree" in sections else None,
        prereq_dag=prereq_dag if "prereq_dag" in sections else None,
        graph=graph if "graph" in sections else None,
        units=units if "units" in sections else [],
        stats=stats if "stats" in sections else KnowledgeOverviewStats(),
        build_status=build_status if "build_status" in sections else None,
    )
