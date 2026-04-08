"""Collect drafts node for the DocGen lane."""

from __future__ import annotations

from app.shared.infra.tools.builtin.markdown_processing import prepend_table_of_contents
from app.utils.docgen_store import update_knowledge_build_status
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress, resolve_docgen_dependency
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
        update_status = resolve_docgen_dependency("update_knowledge_build_status", update_knowledge_build_status)
        update_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="enriching",
            digest_mode=state.get("digest_mode") or None,
            staged_chapter_count=len(chapter_metadatas),
            current_stage_description=f"已生成 {len(chapter_metadatas)} 章草稿，开始进行文档增强。",
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="draft_collection_completed",
            payload={
                "chapter_count": len(chapter_metadatas),
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
