"""Sync the course knowledge graph as the final DocGen post-publish node."""

from __future__ import annotations

import asyncio
from time import perf_counter

import structlog

from app.shared.infra.course import get_course_record_by_id, get_course_vector_capability
from app.shared.infra.database import managed_session
from app.shared.infra.knowledge.build_store import read_knowledge_build_runtime
from app.shared.infra.llm_support.common import capture_llm_runtime_snapshot
from app.shared.infra.llm_support.model_choices import build_runtime_model_override_snapshot
from app.shared.infra.settings import get_settings
from app.shared.infra.storage import build_course_storage_scope
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.common.indexing import index_course_files_for_retrieval
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.kg_doc_sync.lib.builds import run_graph_docs_sync_auto_build

logger = structlog.get_logger(__name__)


def _vector_capability(course_id: str):
    with managed_session() as session:
        course = get_course_record_by_id(session, course_id)
        return get_course_vector_capability(session, course) if course is not None else None


async def _ensure_course_vector_index(*, course_id: str, file_ids: list[str]) -> tuple[str, int]:
    normalized_file_ids = [
        file_id
        for file_id in dict.fromkeys(str(item or "").strip() for item in file_ids)
        if file_id
    ]
    if not normalized_file_ids:
        return "skipped_no_sources", 0

    capability = _vector_capability(course_id)
    if capability is None:
        return "skipped_course_missing", 0
    if capability.binding is not None and capability.binding.mode.value == "disabled":
        return "skipped_disabled", 0
    if capability.queryable:
        return "ready", 0
    if not capability.writable:
        return "skipped_runtime_unavailable", 0

    last_chunk_count = 0
    for attempt in range(1, 3):
        materialized = await index_course_files_for_retrieval(
            course_id=course_id,
            file_ids=normalized_file_ids,
            reason=f"digest.docgen.finalize_vector_index.attempt_{attempt}",
            raise_errors=True,
        )
        last_chunk_count = len(getattr(materialized, "chunk_ids", []) or [])
        capability = _vector_capability(course_id)
        if capability is not None and capability.queryable:
            return "rebuilt", last_chunk_count

    notice = str(getattr(getattr(capability, "status", None), "notice", "") or "").strip()
    raise RuntimeError(
        "DocGen published successfully but the course vector index is still not queryable"
        + (f": {notice}" if notice else ".")
    )


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

        async def sync_graph() -> str:
            if not get_settings().knowledge_graph.sync_after_docgen:
                return "skipped"
            llm_snapshot = (
                build_runtime_model_override_snapshot(state.get("model_override"))
                or capture_llm_runtime_snapshot()
            )
            return await run_graph_docs_sync_auto_build(
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
        graph_result, vector_result = await asyncio.gather(
            sync_graph(),
            _ensure_course_vector_index(
                course_id=course_id,
                file_ids=file_ids,
            ),
            return_exceptions=True,
        )
        if isinstance(graph_result, BaseException):
            raise graph_result
        if isinstance(vector_result, BaseException):
            raise vector_result

        graph_status = graph_result
        vector_index_status, vector_chunk_count = vector_result
        runtime = read_knowledge_build_runtime(course_id, course_scope=course_scope)
        graph_metrics: dict[str, object] = {}
        if runtime is not None and runtime.graph_runtime is not None:
            graph_metrics = dict(runtime.graph_runtime.metrics or {})
        prefetch_metrics = dict(state.get("kg_prefetch_metrics") or {})
        prefetch_metrics.update(
            {
                key: value
                for key, value in graph_metrics.items()
                if str(key).startswith("prefetch_")
            }
        )
        if graph_status in {"completed", "partial_failed"}:
            prefetch_status = graph_status
            prefetch_ready = (
                graph_status == "completed"
                and int(prefetch_metrics.get("prefetch_failed_section_count", 0) or 0) == 0
            )
            prefetch_metrics["prefetch_status"] = prefetch_status
            prefetch_metrics["prefetch_ready"] = 1 if prefetch_ready else 0
        else:
            prefetch_status = str(state.get("kg_prefetch_status") or graph_status)
            prefetch_ready = bool(state.get("kg_prefetch_ready"))
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "docgen_inline_graph_sync_completed",
            course_id=course_id,
            build_session_id=build_session_id,
            graph_status=graph_status,
            kg_prefetch_status=prefetch_status,
            kg_prefetch_ready=prefetch_ready,
            vector_index_status=vector_index_status,
            vector_chunk_count=vector_chunk_count,
            elapsed_ms=elapsed_ms,
        )
        return {
            "graph_sync_status": graph_status,
            "graph_sync_metrics": graph_metrics,
            "graph_sync_ms": elapsed_ms,
            "kg_prefetch_status": prefetch_status,
            "kg_prefetch_metrics": prefetch_metrics,
            "kg_prefetch_ready": prefetch_ready,
            "vector_index_status": vector_index_status,
            "vector_index_chunk_count": vector_chunk_count,
        }

    return sync_knowledge_graph_node


__all__ = ["build_sync_knowledge_graph_node"]
