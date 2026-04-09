"""Enrich document node for the DocGen lane."""

from __future__ import annotations

from copy import deepcopy

from app.shared.infra.config import get_settings
from app.shared.infra.skills import ImageGenerator, MermaidGenerator, SkillContext
from app.shared.infra.tools.builtin.latex_processing import normalize_math_delimiters, validate_latex
from app.shared.infra.tools.builtin.markdown_processing import append_reference_section, build_draft_excerpt, prepend_table_of_contents
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.common.context import WorkflowContext
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

        settings = get_settings()
        include_sources = bool((state.get("confirmed_plan") or {}).get("build_constraints", {}).get("include_sources", True))
        mermaid_count = 0
        image_count = 0
        for chapter in chapter_metadatas:
            markdown = str(chapter.get("markdown") or "")
            mermaid_count += markdown.count("[MERMAID:")
            image_count += markdown.count("[IMAGE:")
            if "[MERMAID:" in markdown and settings.mermaid_generation_enabled:
                markdown = await MermaidGenerator(
                    SkillContext(
                        subject=state["subject"],
                        build_session_id=state.get("build_session_id", ""),
                        workflow_context=context,
                        planner_session_id=state.get("planner_session_id", ""),
                        confirmed_plan_id=state.get("confirmed_plan_id", ""),
                        digest_mode=state.get("digest_mode", ""),
                        course_type=resolve_docgen_course_type(state.get("course_type") or state.get("digest_mode")),
                        teaching_action="document_enrich",
                        asset_kind="mermaid",
                        chapter_index=int(chapter.get("chapter_index", 0) or 0),
                    )
                ).process_placeholders(markdown)
            if "[IMAGE:" in markdown:
                markdown = await ImageGenerator(
                    SkillContext(
                        subject=state["subject"],
                        build_session_id=state.get("build_session_id", ""),
                        workflow_context=context,
                        planner_session_id=state.get("planner_session_id", ""),
                        confirmed_plan_id=state.get("confirmed_plan_id", ""),
                        digest_mode=state.get("digest_mode", ""),
                        course_type=resolve_docgen_course_type(state.get("course_type") or state.get("digest_mode")),
                        teaching_action="document_enrich",
                        asset_kind="image",
                        chapter_index=int(chapter.get("chapter_index", 0) or 0),
                    )
                ).process_placeholders(markdown)
            markdown = normalize_math_delimiters(markdown)
            markdown = validate_latex(markdown)
            if include_sources:
                markdown = append_reference_section(markdown, list(chapter.get("source_details") or []))
            chapter["markdown"] = markdown
            chapter["summary"] = build_draft_excerpt(markdown, max_chars=260)

        merged_markdown = prepend_table_of_contents(
            build_merged_markdown(
                chapter_metadatas,
                document_context=dict(state.get("document_context") or {}),
            ),
            min_level=2,
            max_level=4,
        )
        update_status = resolve_docgen_dependency("update_knowledge_build_status", update_knowledge_build_status)
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
                "summary": f"文档增强完成，处理 Mermaid 占位 {mermaid_count} 个，图片占位 {image_count} 个。",
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
            },
        )
        return {
            "chapter_metadatas": chapter_metadatas,
            "enriched_markdown": merged_markdown,
            "merged_markdown": merged_markdown,
        }

    return enrich_document_node


__all__ = ["build_enrich_document_node"]
