"""Map local outline candidates from cleaned chunks."""

from __future__ import annotations

import asyncio
from time import perf_counter

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.services.outline_service import (
    build_chunk_preview,
    extract_headers,
    infer_outline_candidates,
)
from app.workflows.digest.docgen.state import DocGenState

logger = structlog.get_logger()


def build_outline_map_node(*, context: WorkflowContext):
    """Build the local outline extraction node."""

    async def outline_map_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="outline_map")
        clean_chunks = state.get("clean_chunks", [])
        node_logger.info("docgen_mapping_local_outline", clean_chunk_count=len(clean_chunks))

        async def _map_chunk(index: int, chunk: dict) -> dict:
            content = chunk["content"]
            titles = extract_headers(content)
            if not titles:
                titles = infer_outline_candidates(
                    content,
                    source_filename=str(chunk.get("source_filename", f"chunk_{index}")),
                )
            return {
                "chunk_index": index,
                "source_filename": chunk.get("source_filename", f"chunk_{index}"),
                "titles": titles[:10],
                "preview": build_chunk_preview(content),
                "llm_calls_total": 0,
                "llm_calls_skipped": 1,
            }

        local_outlines = list(await asyncio.gather(*(_map_chunk(index, chunk) for index, chunk in enumerate(clean_chunks))))
        llm_calls_total = sum(int(item.get("llm_calls_total", 0)) for item in local_outlines)
        llm_calls_skipped = sum(int(item.get("llm_calls_skipped", 0)) for item in local_outlines)
        outline_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_mapping_local_outline_completed",
            chunk_count=len(local_outlines),
            outline_ms=outline_ms,
            llm_calls_total=llm_calls_total,
            llm_calls_skipped=llm_calls_skipped,
        )
        return {
            "local_outlines": local_outlines,
            "outline_ms": outline_ms,
            "llm_calls_total": llm_calls_total,
            "llm_calls_skipped": llm_calls_skipped,
        }

    return outline_map_node
