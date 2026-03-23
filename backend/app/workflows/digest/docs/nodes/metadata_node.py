"""Extract chapter metadata for the knowledge docs."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.writer_service import (
    extract_metadata,
    extract_metadata_rule_based,
)
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_extract_metadata_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the fan-out metadata extraction node."""

    async def extract_metadata_node(state: dict) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="extract_metadata")

        reviewed = state["reviewed"]
        chapter_index = reviewed["chapter_index"]
        chapter_title = reviewed["title"]
        markdown = reviewed["markdown"]

        node_logger.info(
            "docgen_extracting_metadata",
            chapter_index=chapter_index,
            chapter_title=chapter_title,
        )

        meta = extract_metadata_rule_based(markdown)
        llm_calls_total = 0
        if strategy.metadata_fallback_llm or not meta.get("summary") or not meta.get("tags"):
            llm_meta = await extract_metadata(markdown)
            llm_calls_total = 1
            if llm_meta.get("summary"):
                meta["summary"] = llm_meta["summary"]
            if llm_meta.get("tags"):
                meta["tags"] = llm_meta["tags"]

        metadata_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_extracting_metadata_completed",
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            metadata_ms=metadata_ms,
            tag_count=len(meta.get("tags", [])),
        )
        return {
            "chapter_metadatas": [
                {
                    "chapter_index": chapter_index,
                    "title": chapter_title,
                    "markdown": markdown,
                    "summary": meta.get("summary", ""),
                    "tags": meta.get("tags", []),
                    "source_file_ids": reviewed.get("source_file_ids", []),
                }
            ],
            "metadata_ms": metadata_ms,
            "llm_calls_total": llm_calls_total,
            "llm_calls_skipped": 0 if llm_calls_total else 1,
        }

    return extract_metadata_node
