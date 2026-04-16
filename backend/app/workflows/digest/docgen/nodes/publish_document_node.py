"""Finalize knowledge docs by staging or publishing them."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.utils.docgen_store import append_knowledge_build_recent_event, upsert_knowledge_build_chapter_progress
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import get_effective_chapter_title, publish_docgen_progress
from app.workflows.digest.docgen.lib.publish import (
    publish_staged_knowledge_docs,
    stage_knowledge_docs,
)
from app.workflows.digest.docgen.state import DocGenState

logger = structlog.get_logger()


def build_publish_document_node(*, context: WorkflowContext):
    """Build the final staging or publishing node for docs outputs."""

    async def publish_document_node(state: DocGenState) -> dict:
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
        standalone = True

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

        for chapter in chapter_metadatas:
            title = get_effective_chapter_title(
                chapter,
                fallback_index=int(chapter.get("chapter_index", 0) or 0) or None,
            )
            if title == "练习与自检":
                continue
            upsert_knowledge_build_chapter_progress(
                subject,
                requested_at=requested_at,
                chapter_progress={
                    "chapter_index": int(chapter.get("chapter_index", 0) or 0),
                    "title": title,
                    "status": "completed",
                    "source_count": len(list(chapter.get("sources") or [])),
                    "local_hits": int(chapter.get("local_hits", 0) or 0),
                    "web_hits": int(chapter.get("web_hits", 0) or 0),
                    "query_count": int(chapter.get("query_count", 0) or 0),
                    "word_count": int(chapter.get("word_count", 0) or 0),
                    "fallback_used": bool(chapter.get("fallback_used", False)),
                },
            )

        finalize_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_finalize_completed",
            chapter_count=len(staged_docs.built_paths),
            merged_chars=len(staged_docs.merged_markdown),
            finalize_ms=finalize_ms,
            published=standalone,
        )
        append_knowledge_build_recent_event(
            subject,
            requested_at=requested_at,
            event={
                "stage": "docgen_finalized",
                "summary": (
                    f"知识文档已发布，共 {len(doc_ids)} 篇正式文档。"
                    if standalone
                    else f"知识文档草稿已暂存，共 {len(staged_docs.built_paths)} 个章节。"
                ),
                "created_at": utcnow(),
            },
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

    return publish_document_node


__all__ = ["build_publish_document_node"]
