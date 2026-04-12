"""Enrich document node for the DocGen lane."""

from __future__ import annotations

from copy import deepcopy

from app.shared.infra.traced_execution import TracedExecutionContext
from app.shared.infra.tools.builtin.latex_processing import normalize_math_delimiters, validate_latex
from app.shared.infra.tools.builtin.markdown_processing import (
    append_reference_section,
    build_draft_excerpt,
    normalize_mermaid_blocks,
    prepend_table_of_contents,
)
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.runtime import DocGenAssetRuntime
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress, resolve_docgen_course_type, resolve_docgen_dependency
from app.workflows.digest.docgen.publish import build_merged_markdown
from app.workflows.digest.docgen.state import DocGenState


def build_enrich_document_node(*, context: WorkflowContext):
    async def enrich_document_node(state: DocGenState) -> dict:
        chapter_metadatas = sorted(
            deepcopy(list(state.get("chapter_metadatas", []))),
            key=lambda item: item.get("chapter_index", 0),
        )
        if not chapter_metadatas:
            return {"error": "当前没有可用于增强处理的章节草稿。"}

        include_sources = bool((state.get("confirmed_plan") or {}).get("build_constraints", {}).get("include_sources", True))
        mermaid_count = 0
        image_count = 0
        interactive_count = 0
        for chapter in chapter_metadatas:
            markdown = str(chapter.get("markdown") or "")
            mermaid_count += markdown.count("[MERMAID:")
            image_count += markdown.count("[IMAGE:")
            interactive_count += markdown.count("[INTERACTIVE:")
            asset_runtime = DocGenAssetRuntime(
                TracedExecutionContext(
                    subject=state["subject"],
                    build_session_id=state.get("build_session_id", ""),
                    workflow_context=context,
                    planner_session_id=state.get("planner_session_id", ""),
                    confirmed_plan_id=state.get("confirmed_plan_id", ""),
                    digest_mode=state.get("digest_mode", ""),
                    course_type=resolve_docgen_course_type(state.get("course_type") or state.get("digest_mode")),
                    teaching_action="document_enrich",
                    chapter_index=int(chapter.get("chapter_index", 0) or 0),
                )
            )
            if "[MERMAID:" in markdown:
                asset_runtime.context.asset_kind = "mermaid"
                markdown = await asset_runtime.process_mermaid_placeholders(markdown)
            if "[IMAGE:" in markdown:
                asset_runtime.context.asset_kind = "image"
                markdown = await asset_runtime.process_image_placeholders(markdown)
            if "[INTERACTIVE:" in markdown:
                asset_runtime.context.asset_kind = "interactive_html"
                markdown = await asset_runtime.process_interactive_placeholders(
                    markdown,
                    digest_mode=state.get("digest_mode") or "",
                )
            markdown = normalize_math_delimiters(markdown)
            markdown = validate_latex(markdown)
            markdown = normalize_mermaid_blocks(markdown)
            if include_sources:
                markdown = append_reference_section(markdown, list(chapter.get("source_details") or []))
            chapter["markdown"] = markdown
            chapter["summary"] = build_draft_excerpt(markdown, max_chars=260)
            chapter["interactive_block_count"] = markdown.count('data-atm-kind="')

        merged_markdown = prepend_table_of_contents(
            build_merged_markdown(
                chapter_metadatas,
                document_context=dict(state.get("document_context") or {}),
            ),
            min_level=2,
            max_level=4,
        )
        merged_markdown = normalize_mermaid_blocks(merged_markdown)
        update_status = resolve_docgen_dependency("update_knowledge_build_status", update_knowledge_build_status, owner_module=__name__)
        update_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="injecting_examine",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="文档增强完成，开始注入练习与自检内容。",
            draft_available=bool(merged_markdown.strip()),
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "document_enriched",
                "summary": f"文档增强完成，处理 Mermaid 占位 {mermaid_count} 个，图片占位 {image_count} 个，交互块占位 {interactive_count} 个。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="document_enriched",
            payload={
                "chapter_count": len(chapter_metadatas),
                "mermaid_placeholder_count": mermaid_count,
                "image_placeholder_count": image_count,
                "interactive_placeholder_count": interactive_count,
            },
        )
        asset_summary = {
            "mermaid": mermaid_count,
            "image": image_count,
            "interactive_html": interactive_count,
            "animation": 0,
        }
        return {
            "chapter_metadatas": chapter_metadatas,
            "enriched_markdown": merged_markdown,
            "merged_markdown": merged_markdown,
            "mermaid_block_count": mermaid_count,
            "image_block_count": image_count,
            "interactive_block_count": sum(int(chapter.get("interactive_block_count", 0) or 0) for chapter in chapter_metadatas),
            "asset_count": sum(asset_summary.values()),
            "asset_summary": asset_summary,
        }

    return enrich_document_node


__all__ = ["build_enrich_document_node"]
