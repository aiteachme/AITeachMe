"""Collect drafts node for the DocGen lane."""

from __future__ import annotations

from app.shared.infra.tools.builtin.markdown_processing import prepend_table_of_contents
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import (
    get_effective_chapter_title,
    publish_docgen_progress,
    resolve_docgen_dependency,
)
from app.workflows.digest.docgen.publish import build_merged_markdown
from app.workflows.digest.docgen.state import DocGenState


def build_collect_drafts_node(*, context: WorkflowContext):
    async def collect_drafts_node(state: DocGenState) -> dict:
        drafts = sorted(
            list(state.get("chapter_drafts", [])),
            key=lambda item: item.get("chapter_index", 0),
        )
        chapter_metadatas = [
            {
                **draft,
                "chapter_index": int(draft.get("chapter_index", index)),
                "title": str(draft.get("title") or f"第 {index} 章"),
                "resolved_title": str(draft.get("resolved_title") or "").strip(),
                "markdown": str(draft.get("markdown") or ""),
                "summary": str(draft.get("summary") or ""),
                "tags": list(draft.get("tags") or []),
                "source_file_ids": list(draft.get("source_file_ids") or []),
                "sources": list(draft.get("sources") or []),
                "source_details": list(draft.get("source_details") or []),
                "digest_mode": str(draft.get("digest_mode") or ""),
                "research_summary": str(draft.get("research_summary") or ""),
                "research_ms": int(draft.get("research_ms", 0) or 0),
                "local_hits": int(draft.get("local_hits", 0) or 0),
                "web_hits": int(draft.get("web_hits", 0) or 0),
                "fallback_used": bool(draft.get("fallback_used", False)),
                "compression_mode": str(draft.get("compression_mode") or ""),
                "executed_queries": list(draft.get("executed_queries") or []),
                "base_queries": list(draft.get("base_queries") or []),
                "planned_queries": list(draft.get("planned_queries") or []),
                "fallback_queries": list(draft.get("fallback_queries") or []),
                "query_count": int(draft.get("query_count", 0) or 0),
                "scraped_url_count": int(draft.get("scraped_url_count", 0) or 0),
                "document_count": int(draft.get("document_count", 0) or 0),
                "purify_used": bool(draft.get("purify_used", False)),
                "curated_source_count": int(draft.get("curated_source_count", 0) or 0),
            }
            for index, draft in enumerate(drafts, start=1)
        ]
        merged_markdown = (
            prepend_table_of_contents(
                build_merged_markdown(
                    chapter_metadatas,
                    document_context=dict(state.get("document_context") or {}),
                ),
                min_level=2,
                max_level=4,
            )
            if chapter_metadatas
            else ""
        )
        update_status = resolve_docgen_dependency("update_knowledge_build_status", update_knowledge_build_status, owner_module=__name__)
        update_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="enriching",
            digest_mode=state.get("digest_mode") or None,
            staged_chapter_count=len(chapter_metadatas),
            current_stage_description=f"已生成 {len(chapter_metadatas)} 章草稿，开始增强文档与媒体占位。",
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "draft_collection_completed",
                "summary": f"章节草稿已收齐，共 {len(chapter_metadatas)} 章，开始统一增强文档格式。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="draft_collection_completed",
            payload={
                "chapter_count": len(chapter_metadatas),
                "chapter_titles": [
                    get_effective_chapter_title(item, fallback_index=int(item.get("chapter_index", 0) or 0) or None)
                    for item in chapter_metadatas[:3]
                ],
                "placeholder_count": sum(int(item.get("placeholder_count", 0) or 0) for item in chapter_metadatas),
                "word_count": sum(int(item.get("word_count", 0) or 0) for item in chapter_metadatas),
            },
        )
        context.get_logger().bind(node="collect_drafts").info(
            "docgen_draft_collection_completed",
            chapter_count=len(chapter_metadatas),
        )
        return {
            "chapter_metadatas": chapter_metadatas,
            "merged_markdown": merged_markdown,
            "enriched_markdown": merged_markdown,
        }

    return collect_drafts_node


__all__ = ["build_collect_drafts_node"]
