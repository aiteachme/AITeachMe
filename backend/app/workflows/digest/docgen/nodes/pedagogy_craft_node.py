"""Pedagogy craft node for the DocGen lane."""

from __future__ import annotations

from copy import deepcopy
from time import perf_counter

from app.shared.infra.skills import PedagogyWriter, SkillContext
from app.shared.infra.tools.builtin.markdown_processing import build_draft_excerpt, count_words
from app.utils.docgen_store import append_knowledge_build_recent_event, upsert_knowledge_build_chapter_progress
from app.utils.time import utcnow
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import ensure_chapter_heading, publish_docgen_progress, resolve_docgen_dependency
from app.workflows.digest.docgen.state import DocGenState


def build_pedagogy_craft_node(*, context: WorkflowContext):
    async def pedagogy_craft_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        material = deepcopy(state["chapter_material"])
        chapter_index = int(material.get("chapter_index", 0) or 0)
        chapter_title = str(material.get("title") or f"第 {chapter_index} 章").strip() or f"第 {chapter_index} 章"
        upsert_knowledge_build_chapter_progress(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_progress={
                "chapter_index": chapter_index,
                "title": chapter_title,
                "status": "drafting",
                "source_count": len(list(material.get("sources") or [])),
                "local_hits": int(material.get("local_hits", 0) or 0),
                "web_hits": int(material.get("web_hits", 0) or 0),
                "query_count": int(material.get("query_count", 0) or 0),
                "fallback_used": bool(material.get("fallback_used", False)),
            },
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "drafting",
                "chapter_index": chapter_index,
                "title": chapter_title,
                "summary": f"{chapter_title} 开始写作，正在把研究材料转成教学化章节。",
                "created_at": utcnow(),
            },
        )

        skill_context = SkillContext(
            subject=state["subject"],
            build_session_id=state.get("build_session_id", ""),
            workflow_context=context,
            planner_session_id=state.get("planner_session_id", ""),
            confirmed_plan_id=state.get("confirmed_plan_id", ""),
            digest_mode=state.get("digest_mode", ""),
            chapter_index=chapter_index,
        )
        writer_cls = resolve_docgen_dependency("PedagogyWriter", PedagogyWriter)
        writer = writer_cls(skill_context)
        result = await writer.run(
            chapter_plan=material,
            dense_context=str(material.get("dense_context") or ""),
            tone=state.get("tone") or "encouraging",
            digest_mode=state.get("digest_mode") or "systematic",
        )
        markdown = ensure_chapter_heading(chapter_title, result.content)
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        draft = {
            "chapter_index": chapter_index,
            "title": chapter_title,
            "markdown": markdown,
            "summary": build_draft_excerpt(markdown, max_chars=260),
            "tags": list(material.get("required_elements") or []),
            "source_file_ids": list(material.get("source_file_ids") or []),
            "sources": list(material.get("sources") or []),
            "source_details": list(material.get("source_details") or []),
            "digest_mode": state.get("digest_mode") or "",
            "research_summary": str(material.get("research_summary") or ""),
            "research_ms": int(material.get("research_ms", 0) or 0),
            "local_hits": int(material.get("local_hits", 0) or 0),
            "web_hits": int(material.get("web_hits", 0) or 0),
            "fallback_used": bool(material.get("fallback_used", False)),
            "compression_mode": str(material.get("compression_mode") or ""),
            "executed_queries": list(material.get("executed_queries") or []),
            "base_queries": list(material.get("base_queries") or []),
            "planned_queries": list(material.get("planned_queries") or []),
            "fallback_queries": list(material.get("fallback_queries") or []),
            "query_count": int(material.get("query_count", 0) or 0),
            "scraped_url_count": int(material.get("scraped_url_count", 0) or 0),
            "document_count": int(material.get("document_count", 0) or 0),
            "purify_used": bool(material.get("purify_used", False)),
            "curated_source_count": int(material.get("curated_source_count", 0) or 0),
            "draft_ms": elapsed_ms,
            "word_count": count_words(markdown),
            "placeholder_count": markdown.count("[MERMAID:") + markdown.count("[IMAGE:") + markdown.count("[INTERACTIVE:"),
        }
        upsert_knowledge_build_chapter_progress(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_progress={
                "chapter_index": chapter_index,
                "title": chapter_title,
                "status": "drafted",
                "source_count": len(list(draft.get("sources") or [])),
                "local_hits": int(draft.get("local_hits", 0) or 0),
                "web_hits": int(draft.get("web_hits", 0) or 0),
                "query_count": int(draft.get("query_count", 0) or 0),
                "word_count": int(draft.get("word_count", 0) or 0),
                "fallback_used": bool(draft.get("fallback_used", False)),
            },
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "draft_completed",
                "chapter_index": chapter_index,
                "title": chapter_title,
                "summary": f"{chapter_title} 写作完成，生成约 {draft['word_count']} 字，保留 {draft['placeholder_count']} 个媒体占位。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="draft_chapter_completed",
            payload={
                "chapter_index": chapter_index,
                "title": draft["title"],
                "word_count": draft["word_count"],
                "placeholder_count": draft["placeholder_count"],
            },
        )
        return {
            "chapter_drafts": [draft],
            "draft_ms": elapsed_ms,
            "llm_calls_total": 1,
        }

    return pedagogy_craft_node


__all__ = ["build_pedagogy_craft_node"]
