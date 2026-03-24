"""Stage knowledge docs outputs for the unified publish step."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.digest.docs.publish import (
    stage_knowledge_docs,
)
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState

logger = structlog.get_logger()


def build_finalize_assemble_node(*, context: WorkflowContext):
    """Build the final staging node for docs outputs."""

    async def finalize_assemble_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="finalize_assemble")
        subject = state["subject"]
        chapter_metadatas = state.get("chapter_metadatas", [])
        chapter_assignments = state.get("chapter_assignments", [])
        user_prompt = state.get("user_prompt")
        requested_at = state["requested_at"]

        if not chapter_metadatas:
            return {"error": "没有章节数据，无法组装。"}

        sorted_chapters = sorted(chapter_metadatas, key=lambda item: item.get("chapter_index", 0))
        node_logger.info(
            "docgen_staging_started",
            chapter_count=len(sorted_chapters),
            requested_at=requested_at.isoformat(),
        )
        staged_docs = await stage_knowledge_docs(
            subject=subject,
            chapter_metadatas=sorted_chapters,
        )

        finalize_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_staging_completed",
            chapter_count=len(staged_docs.built_paths),
            merged_chars=len(staged_docs.merged_markdown),
            finalize_ms=finalize_ms,
            requested_at=requested_at.isoformat(),
        )
        return {
            "doc_ids": [],
            "built_paths": staged_docs.built_paths,
            "merged_markdown": staged_docs.merged_markdown,
            "user_prompt": user_prompt,
            "chapter_assignments": chapter_assignments,
            "finalize_ms": finalize_ms,
        }

    return finalize_assemble_node
