"""Finalize knowledge docs by staging or publishing them."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.publish import publish_staged_knowledge_docs, stage_knowledge_docs
from app.workflows.digest.docgen.state import DocGenState

logger = structlog.get_logger()


def _is_standalone_mode(state: DocGenState) -> bool:
    """Return True when running outside a unified build session."""

    build_session_id = state.get("build_session_id", "")
    if not build_session_id:
        return True
    try:
        from app.workflows.digest.unified.session import get_unified_build_session

        get_unified_build_session(build_session_id)
        return False
    except (KeyError, ImportError):
        return True


def build_finalize_assemble_node(*, context: WorkflowContext):
    """Build the final staging or publishing node for docs outputs."""

    async def finalize_assemble_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="finalize_assemble")
        subject = state["subject"]
        chapter_metadatas = sorted(
            list(state.get("chapter_metadatas", [])),
            key=lambda item: item.get("chapter_index", 0),
        )
        chapter_assignments = list(state.get("chapter_assignments", []))
        document_context = dict(state.get("document_context") or {})
        user_prompt = state.get("user_prompt")
        requested_at = state["requested_at"]
        standalone = _is_standalone_mode(state)

        if not chapter_metadatas:
            return {"error": "当前没有可用于最终发布的章节内容。"}

        node_logger.info(
            "docgen_finalize_started",
            chapter_count=len(chapter_metadatas),
            requested_at=requested_at.isoformat(),
            standalone=standalone,
        )

        staged_docs = await stage_knowledge_docs(
            subject=subject,
            chapter_metadatas=chapter_metadatas,
            document_context=document_context,
        )

        doc_ids: list[int] = []
        if standalone:
            doc_ids = publish_staged_knowledge_docs(
                subject=subject,
                chapter_metadatas=chapter_metadatas,
                chapter_assignments=chapter_assignments,
                document_context=document_context,
                user_prompt=user_prompt,
                requested_at=requested_at,
                version_no=1,
                build_session_id=state.get("build_session_id"),
            )
            node_logger.info("docgen_standalone_publish_completed", doc_count=len(doc_ids))

        finalize_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_finalize_completed",
            chapter_count=len(staged_docs.built_paths),
            merged_chars=len(staged_docs.merged_markdown),
            finalize_ms=finalize_ms,
            published=standalone,
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="docgen_finalized",
            payload={
                "chapter_count": len(staged_docs.built_paths),
                "published_doc_count": len(doc_ids),
                "draft_available": bool(staged_docs.merged_markdown.strip()),
            },
        )
        return {
            "doc_ids": doc_ids,
            "built_paths": staged_docs.built_paths,
            "merged_markdown": staged_docs.merged_markdown,
            "user_prompt": user_prompt,
            "finalize_ms": finalize_ms,
        }

    return finalize_assemble_node
