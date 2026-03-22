"""节点：Outline Map — 并发提取/生成局部标题。

Reads DB: ``docgen_job``.
Writes DB: ``docgen_job`` progress.
Writes FS: none.
Idempotency: reruns recompute local outlines from the same cleaned chunks for the active job.
"""

from __future__ import annotations

import asyncio

import structlog

from app.core.database import managed_session
from app.repositories.knowledge import docgen_repo
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.outline_service import (
    extract_headers,
    generate_local_titles,
)
from app.workflows.digest.docs.state import DocGenState

logger = structlog.get_logger()


def build_outline_map_node(*, context: WorkflowContext):
    """构建并发局部标题提取节点。"""

    async def outline_map_node(state: DocGenState) -> dict:
        node_logger = context.get_logger().bind(node="outline_map")
        node_logger.info("outline_map_started")

        job_id = state["job_id"]
        clean_chunks = state.get("clean_chunks", [])

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="outlining_map", progress=25,
            )

        async def _map_chunk(i: int, chunk: dict) -> dict:
            content = chunk["content"]
            existing = extract_headers(content)
            if len(existing) >= 2:
                titles = existing[:10]
            else:
                titles = await generate_local_titles(content)
            return {
                "chunk_index": i,
                "source_filename": chunk.get("source_filename", f"chunk_{i}"),
                "titles": titles,
            }

        local_outlines = await asyncio.gather(
            *(_map_chunk(i, c) for i, c in enumerate(clean_chunks))
        )

        with managed_session() as session:
            docgen_repo.update_docgen_job(session, job_id, progress=30)

        node_logger.info("outline_map_done", count=len(local_outlines))
        return {"local_outlines": list(local_outlines)}

    return outline_map_node
