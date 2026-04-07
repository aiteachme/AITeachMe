"""Extract chapter metadata for docgen lane output."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.services.writer_service import (
    extract_metadata,
    extract_metadata_rule_based,
)
from app.workflows.digest.docgen.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_extract_metadata_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the metadata extraction node."""

    async def extract_metadata_node(state: dict) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="extract_metadata")
        reviewed = state["reviewed"]
        chapter_index = int(reviewed["chapter_index"])
        chapter_title = str(reviewed["title"])
        markdown = str(reviewed["markdown"])

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
            tag_count=len(meta.get("tags", [])),
            metadata_ms=metadata_ms,
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
                    "chunk_uids": reviewed.get("chunk_uids", []),
                    "section_titles": reviewed.get("section_titles", []),
                    "metadata_ms": metadata_ms,
                }
            ],
            "metadata_ms": metadata_ms,
            "llm_calls_total": llm_calls_total,
            "llm_calls_skipped": 0 if llm_calls_total else 1,
        }

    return extract_metadata_node



