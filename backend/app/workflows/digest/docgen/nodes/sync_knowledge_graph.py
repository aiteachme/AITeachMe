"""Sync the course knowledge graph as the final DocGen post-publish node."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.shared.infra.knowledge.build_store import read_knowledge_build_runtime
from app.shared.infra.llm_support.common import capture_llm_runtime_snapshot
from app.shared.infra.llm_support.model_choices import build_runtime_model_override_snapshot
from app.shared.infra.settings import get_settings
from app.shared.infra.storage import build_course_storage_scope
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.kg_doc_sync.lib.builds import run_graph_docs_sync_auto_build

logger = structlog.get_logger(__name__)


def build_sync_knowledge_graph_node(*, context: WorkflowContext):
    """Build the in-graph DocGen -> KG sync node."""

    async def sync_knowledge_graph_node(state: DocGenState) -> dict[str, object]:
        started_at = perf_counter()
        course_id = state["course_id"]
        user_id = str(state.get("user_id") or "").strip()
        requested_at = state["requested_at"]
        build_group_id = str(state.get("build_group_id") or "").strip()
        build_session_id = str(state.get("build_session_id") or "").strip()
        file_ids = list(state.get("file_ids") or [])
        prompt = state.get("user_prompt")
        course_scope = build_course_storage_scope(user_id=user_id, course_id=course_id) if user_id else None

        if not get_settings().knowledge_graph.sync_after_docgen:
            return {
                "graph_sync_status": "skipped",
                "graph_sync_metrics": {},
                "graph_sync_ms": int((perf_counter() - started_at) * 1000),
            }

        llm_snapshot = (
            build_runtime_model_override_snapshot(state.get("model_override"))
            or capture_llm_runtime_snapshot()
        )
        graph_status = await run_graph_docs_sync_auto_build(
            course_id=course_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            build_session_id=build_session_id,
            file_ids=file_ids,
            prompt=str(prompt) if prompt is not None else None,
            llm_snapshot=llm_snapshot,
            docgen_state=dict(state),
            course_scope=course_scope,
        )
        runtime = read_knowledge_build_runtime(course_id, course_scope=course_scope)
        graph_metrics: dict[str, object] = {}
        if runtime is not None and runtime.graph_runtime is not None:
            graph_metrics = dict(runtime.graph_runtime.metrics or {})
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "docgen_inline_graph_sync_completed",
            course_id=course_id,
            build_session_id=build_session_id,
            graph_status=graph_status,
            elapsed_ms=elapsed_ms,
        )
        return {
            "graph_sync_status": graph_status,
            "graph_sync_metrics": graph_metrics,
            "graph_sync_ms": elapsed_ms,
        }

    return sync_knowledge_graph_node


__all__ = ["build_sync_knowledge_graph_node"]
