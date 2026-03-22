"""节点：Outline Map — 并发提取/生成局部标题。

Reads DB: ``docgen_job``.
Writes DB: ``docgen_job`` progress.
Writes FS: none.
Idempotency: reruns recompute local outlines from the same cleaned chunks for the active job.
"""

from __future__ import annotations

import asyncio
from time import perf_counter

import structlog

from app.core.database import managed_session
from app.repositories.knowledge import docgen_repo
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.outline_service import (
    build_chunk_preview,
    extract_headers,
    infer_outline_candidates,
)
from app.workflows.digest.docs.state import DocGenState

logger = structlog.get_logger()


def build_outline_map_node(*, context: WorkflowContext):
    """构建并发局部标题提取节点。"""

    async def outline_map_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="outline_map")
        node_logger.info("outline_map_started", clean_chunk_count=len(state.get("clean_chunks", [])))

        job_id = state["job_id"]
        clean_chunks = state.get("clean_chunks", [])

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="outlining", progress=25,
            )

        async def _map_chunk(i: int, chunk: dict) -> dict:
            content = chunk["content"]
            existing = extract_headers(content)
            titles = existing[:10] if existing else infer_outline_candidates(
                content,
                source_filename=str(chunk.get("source_filename", f"chunk_{i}")),
            )
            llm_calls_total = 0
            llm_calls_skipped = 1
            return {
                "chunk_index": i,
                "source_filename": chunk.get("source_filename", f"chunk_{i}"),
                "titles": titles,
                "preview": build_chunk_preview(content),
                "llm_calls_total": llm_calls_total,
                "llm_calls_skipped": llm_calls_skipped,
            }

        local_outlines = await asyncio.gather(
            *(_map_chunk(i, c) for i, c in enumerate(clean_chunks))
        )
        llm_calls_total = sum(int(item.get("llm_calls_total", 0)) for item in local_outlines)
        llm_calls_skipped = sum(int(item.get("llm_calls_skipped", 0)) for item in local_outlines)

        with managed_session() as session:
            docgen_repo.update_docgen_job(session, job_id, progress=30)

        outline_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "outline_map_done",
            count=len(local_outlines),
            outline_ms=outline_ms,
            llm_calls_total=llm_calls_total,
            llm_calls_skipped=llm_calls_skipped,
        )
        return {
            "local_outlines": list(local_outlines),
            "outline_ms": outline_ms,
            "llm_calls_total": llm_calls_total,
            "llm_calls_skipped": llm_calls_skipped,
        }

    return outline_map_node
