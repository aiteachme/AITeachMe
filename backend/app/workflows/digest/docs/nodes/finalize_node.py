"""Finalize knowledge docs — stage or publish depending on mode."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.digest.docs.publish import (
    publish_staged_knowledge_docs,
    stage_knowledge_docs,
)
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState

logger = structlog.get_logger()


def _is_standalone_mode(state: DocGenState) -> bool:
    """Return True when running outside a unified build session."""

    build_session_id = state.get("build_session_id", "")
    if not build_session_id:
        return True
    try:
        from app.workflows.digest.unified.session import get_unified_build_session

        get_unified_build_session(build_session_id)
        return False  # session exists → unified mode
    except (KeyError, ImportError):
        return True  # no session → standalone mode


def build_finalize_assemble_node(*, context: WorkflowContext):
    """Build the final staging / publishing node for docs outputs.

    * **unified mode** — only *stage* docs; the unified graph will publish
      them in a coordinated ``publish_outputs`` step later.
    * **standalone mode** — directly *publish* docs so the pipeline is
      self-contained.
    """

    async def finalize_assemble_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="finalize_assemble")
        subject = state["subject"]
        chapter_metadatas = state.get("chapter_metadatas", [])
        chapter_assignments = state.get("chapter_assignments", [])
        user_prompt = state.get("user_prompt")
        requested_at = state["requested_at"]
        standalone = _is_standalone_mode(state)

        if not chapter_metadatas:
            return {"error": "没有章节数据，无法组装。"}

        sorted_chapters = sorted(chapter_metadatas, key=lambda item: item.get("chapter_index", 0))
        node_logger.info(
            "docgen_finalize_started",
            chapter_count=len(sorted_chapters),
            requested_at=requested_at.isoformat(),
            standalone=standalone,
        )

        # Always stage first
        staged_docs = await stage_knowledge_docs(
            subject=subject,
            chapter_metadatas=sorted_chapters,
        )

        doc_ids: list[int] = []

        if standalone:
            # Standalone mode — publish immediately
            doc_ids = publish_staged_knowledge_docs(
                subject=subject,
                chapter_metadatas=sorted_chapters,
                chapter_assignments=list(chapter_assignments),
                user_prompt=user_prompt,
                requested_at=requested_at,
                version_no=1,
                build_session_id=state.get("build_session_id"),
            )
            node_logger.info(
                "docgen_standalone_publish_completed",
                doc_count=len(doc_ids),
            )

        finalize_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_finalize_completed",
            chapter_count=len(staged_docs.built_paths),
            merged_chars=len(staged_docs.merged_markdown),
            finalize_ms=finalize_ms,
            published=standalone,
        )
        return {
            "doc_ids": doc_ids,
            "built_paths": staged_docs.built_paths,
            "merged_markdown": staged_docs.merged_markdown,
            "user_prompt": user_prompt,
            "chapter_assignments": chapter_assignments,
            "finalize_ms": finalize_ms,
        }

    return finalize_assemble_node
