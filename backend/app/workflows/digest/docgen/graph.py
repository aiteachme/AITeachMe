"""DocGen LangGraph definition."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from time import perf_counter
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from app.shared.infra.config import get_settings
from app.shared.infra.skills import ImageGenerator, MermaidGenerator, PedagogyWriter, ResearchConductor, SkillContext
from app.shared.infra.tools.builtin.latex_processing import normalize_math_delimiters, validate_latex
from app.shared.infra.tools.builtin.markdown_processing import (
    append_reference_section,
    build_draft_excerpt,
    prepend_table_of_contents,
)
from app.utils.docgen_store import update_knowledge_build_status
from app.workflows.common.context import WorkflowContext, create_langgraph_dev_context
from app.workflows.digest.docgen.nodes.finalize_node import build_finalize_assemble_node
from app.workflows.digest.docgen.publish import build_merged_markdown
from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.observability import wrap_digest_node
from app.workflows.digest.planner.models import build_fallback_plan
from app.workflows.digest.shared.prepare import prepare_shared_inputs


def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the DocGen graph."""

    workflow = StateGraph(DocGenState)
    workflow.add_node(
        "load_context",
        wrap_digest_node(
            build_load_context_node(context=context),
            workflow_name=context.workflow_name,
            lane="docgen",
            node_name="load_context",
            timing_field="load_ms",
        ),
    )
    workflow.add_node(
        "targeted_research",
        wrap_digest_node(
            build_targeted_research_node(context=context),
            workflow_name=context.workflow_name,
            lane="docgen",
            node_name="targeted_research",
        ),
    )
    workflow.add_node(
        "collect_materials",
        wrap_digest_node(
            build_collect_materials_node(context=context),
            workflow_name=context.workflow_name,
            lane="docgen",
            node_name="collect_materials",
        ),
    )
    workflow.add_node(
        "pedagogy_craft",
        wrap_digest_node(
            build_pedagogy_craft_node(context=context),
            workflow_name=context.workflow_name,
            lane="docgen",
            node_name="pedagogy_craft",
        ),
    )
    workflow.add_node(
        "collect_drafts",
        wrap_digest_node(
            build_collect_drafts_node(context=context),
            workflow_name=context.workflow_name,
            lane="docgen",
            node_name="collect_drafts",
        ),
    )
    workflow.add_node(
        "enrich_document",
        wrap_digest_node(
            build_enrich_document_node(context=context),
            workflow_name=context.workflow_name,
            lane="docgen",
            node_name="enrich_document",
            timing_field="enrich_ms",
        ),
    )
    workflow.add_node(
        "inject_examine",
        wrap_digest_node(
            build_inject_examine_node(context=context),
            workflow_name=context.workflow_name,
            lane="docgen",
            node_name="inject_examine",
            timing_field="examine_ms",
        ),
    )
    workflow.add_node(
        "finalize_assemble",
        wrap_digest_node(
            build_finalize_assemble_node(context=context),
            workflow_name=context.workflow_name,
            lane="docgen",
            node_name="finalize_assemble",
        ),
    )

    workflow.set_entry_point("load_context")
    workflow.add_conditional_edges("load_context", route_after_load_context, {"continue": "targeted_research", "fail": END})
    workflow.add_edge("targeted_research", "collect_materials")
    workflow.add_conditional_edges("collect_materials", build_craft_sends)
    workflow.add_edge("pedagogy_craft", "collect_drafts")
    workflow.add_conditional_edges("collect_drafts", route_after_step, {"continue": "enrich_document", "fail": END})
    workflow.add_conditional_edges("enrich_document", route_after_step, {"continue": "inject_examine", "fail": END})
    workflow.add_conditional_edges("inject_examine", route_after_step, {"continue": "finalize_assemble", "fail": END})
    workflow.add_edge("finalize_assemble", END)
    return workflow


def create_docgen_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    user_prompt: str | None,
    requested_at: datetime,
    build_session_id: str | None,
    shared_inputs: Any | None = None,
    confirmed_plan: dict[str, Any] | None = None,
    planner_session_id: str | None = None,
    confirmed_plan_id: str | None = None,
    digest_mode: str | None = None,
    tone: str | None = None,
) -> DocGenState:
    """Create initial state for the DocGen graph."""

    return {
        "subject": subject,
        "file_ids": file_ids,
        "user_prompt": user_prompt,
        "requested_at": requested_at,
        "build_session_id": build_session_id or "",
        "shared_inputs": shared_inputs,
        "confirmed_plan": confirmed_plan,
        "planner_session_id": planner_session_id or "",
        "confirmed_plan_id": confirmed_plan_id or "",
        "digest_mode": digest_mode or "",
        "tone": tone or "",
        "document_context": None,
        "error": None,
    }


def route_after_step(state: DocGenState) -> str:
    return "fail" if state.get("error") else "continue"


def route_after_load_context(state: DocGenState) -> list[Send] | str:
    if state.get("error"):
        return "fail"
    return build_research_sends(state)


def build_research_sends(state: DocGenState) -> list[Send]:
    assignments = sorted(
        list(state.get("chapter_assignments", [])),
        key=lambda item: item.get("chapter_index", 0),
    )
    total = len(assignments)
    return [
        Send(
            "targeted_research",
            {
                "subject": state["subject"],
                "requested_at": state["requested_at"],
                "build_session_id": state.get("build_session_id", ""),
                "planner_session_id": state.get("planner_session_id", ""),
                "confirmed_plan_id": state.get("confirmed_plan_id", ""),
                "digest_mode": state.get("digest_mode", ""),
                "tone": state.get("tone", ""),
                "shared_inputs": state.get("shared_inputs"),
                "chapter_assignment": chapter,
                "total_chapters": total,
            },
        )
        for chapter in assignments
    ]


def build_craft_sends(state: DocGenState) -> list[Send]:
    materials = sorted(
        list(state.get("chapter_materials", [])),
        key=lambda item: item.get("chapter_index", 0),
    )
    total = len(materials)
    return [
        Send(
            "pedagogy_craft",
            {
                "subject": state["subject"],
                "requested_at": state["requested_at"],
                "build_session_id": state.get("build_session_id", ""),
                "planner_session_id": state.get("planner_session_id", ""),
                "confirmed_plan_id": state.get("confirmed_plan_id", ""),
                "digest_mode": state.get("digest_mode", ""),
                "tone": state.get("tone", ""),
                "chapter_material": material,
                "total_chapters": total,
            },
        )
        for material in materials
    ]


def build_load_context_node(*, context: WorkflowContext):
    async def load_context_node(state: DocGenState) -> dict:
        shared_inputs = state.get("shared_inputs")
        if shared_inputs is None:
            build_session_id = state.get("build_session_id", "")
            if build_session_id:
                try:
                    from app.workflows.digest.unified.session import get_unified_build_session

                    shared_inputs = get_unified_build_session(build_session_id).shared_inputs
                except KeyError:
                    shared_inputs = None
        if shared_inputs is None:
            shared_inputs = await prepare_shared_inputs(
                state["subject"],
                state.get("file_ids", []),
                user_prompt=state.get("user_prompt"),
            )
        if not shared_inputs.source_packets:
            return {"error": "当前没有可用于文档构建的已解析资料。"}

        digest_mode = state.get("digest_mode") or shared_inputs.digest_mode_decision.mode.value
        tone = state.get("tone") or "encouraging"
        plan_payload = deepcopy(state.get("confirmed_plan") or {})
        if not plan_payload.get("chapter_plan"):
            fallback = build_fallback_plan(
                subject=state["subject"],
                user_goal=state.get("user_prompt") or "生成一份结构化的学习文档。",
                digest_mode=digest_mode,
                tone=tone,
                shared_inputs=shared_inputs,
            )
            plan_payload = fallback.model_dump(mode="json")
        digest_mode = str(plan_payload.get("digest_mode") or digest_mode)
        tone = str(plan_payload.get("tone") or tone)
        assignments = _normalize_chapter_assignments(
            plan_payload.get("chapter_plan") or [],
            default_source_file_ids=list(state.get("file_ids", [])),
        )
        if not assignments:
            return {"error": "已确认的构建方案中没有可执行的章节。"}

        document_context = {
            "subject": state["subject"],
            "digest_mode": digest_mode,
            "tone": tone,
            "user_goal": str(plan_payload.get("user_goal") or state.get("user_prompt") or ""),
            "plan_summary": str(plan_payload.get("plan_summary") or ""),
        }

        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="planner_confirmed",
            planner_session_id=state.get("planner_session_id") or None,
            confirmed_plan_id=state.get("confirmed_plan_id") or None,
            digest_mode=digest_mode,
            mode_reason=(plan_payload.get("mode_reason") or "confirmed_build_plan"),
            current_stage_description=str(plan_payload.get("plan_summary") or "已确认构建方案，开始按规划执行。"),
            total_chunks=len(assignments),
            processed_chunks=0,
            current_chunk=0,
        )
        return {
            "shared_inputs": shared_inputs,
            "raw_chunks": [_serialize_section(section) for section in shared_inputs.section_packets],
            "subject_profile": shared_inputs.subject_profile.model_dump(mode="json"),
            "chapter_assignments": assignments,
            "confirmed_plan": plan_payload,
            "digest_mode": digest_mode,
            "tone": tone,
            "document_context": document_context,
            "planner_ms": 0,
        }

    return load_context_node


def build_targeted_research_node(*, context: WorkflowContext):
    async def targeted_research_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        assignment = deepcopy(state["chapter_assignment"])
        skill_context = SkillContext(
            subject=state["subject"],
            build_session_id=state.get("build_session_id", ""),
            workflow_context=context,
            planner_session_id=state.get("planner_session_id", ""),
            confirmed_plan_id=state.get("confirmed_plan_id", ""),
            digest_mode=state.get("digest_mode", ""),
            chapter_index=int(assignment.get("chapter_index", 0) or 0),
        )
        researcher = ResearchConductor(skill_context)
        shared_inputs = state.get("shared_inputs")
        section_packets = list(getattr(shared_inputs, "section_packets", []) or [])
        queries = [
            str(item).strip()
            for item in assignment.get("search_queries", [])
            if str(item).strip()
        ]
        if not queries:
            queries = [str(assignment.get("title") or "").strip()]
        result = await researcher.run(
            queries=queries[: max(1, int(get_settings().docgen_max_research_queries))],
            local_rag_subject=state["subject"],
            local_sections=section_packets,
            chapter_title=str(assignment.get("title") or ""),
            objective=str(assignment.get("objective") or ""),
            required_elements=list(assignment.get("required_elements") or []),
            digest_mode=state.get("digest_mode") or "",
        )
        dense_context = result.content.strip()
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        chapter_material = {
            **assignment,
            "dense_context": dense_context,
            "sources": list(result.sources),
            "source_details": list(result.metadata.get("source_details", [])),
            "research_summary": build_draft_excerpt(dense_context, max_chars=320) if dense_context else "",
            "research_ms": elapsed_ms,
            "local_hits": int(result.metadata.get("local_hits", 0)),
            "web_hits": int(result.metadata.get("web_hits", 0)),
            "fallback_used": bool(result.metadata.get("fallback_used", False)),
            "compression_mode": str(result.metadata.get("compression_mode", "")),
            "executed_queries": list(result.metadata.get("executed_queries", [])),
            "curated_source_count": int(result.metadata.get("curated_source_count", 0)),
        }
        return {
            "chapter_materials": [chapter_material],
            "research_sources": list(result.sources),
            "research_ms": elapsed_ms,
            "llm_calls_total": 1 if bool(result.metadata.get("purify_used", False)) else 0,
        }

    return targeted_research_node


def build_collect_materials_node(*, context: WorkflowContext):
    async def collect_materials_node(state: DocGenState) -> dict:
        materials = sorted(
            list(state.get("chapter_materials", [])),
            key=lambda item: item.get("chapter_index", 0),
        )
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="drafting",
            digest_mode=state.get("digest_mode") or None,
            processed_chunks=len(materials),
            total_chunks=len(materials),
            current_chunk=len(materials),
            current_stage_description=f"已完成 {len(materials)} 章资料研究，开始生成章节讲义。",
        )
        context.get_logger().bind(node="collect_materials").info(
            "docgen_material_collection_completed",
            chapter_count=len(materials),
        )
        return {}

    return collect_materials_node


def build_pedagogy_craft_node(*, context: WorkflowContext):
    async def pedagogy_craft_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        material = deepcopy(state["chapter_material"])
        chapter_index = int(material.get("chapter_index", 0) or 0)
        skill_context = SkillContext(
            subject=state["subject"],
            build_session_id=state.get("build_session_id", ""),
            workflow_context=context,
            planner_session_id=state.get("planner_session_id", ""),
            confirmed_plan_id=state.get("confirmed_plan_id", ""),
            digest_mode=state.get("digest_mode", ""),
            chapter_index=chapter_index,
        )
        writer = PedagogyWriter(skill_context)
        result = await writer.run(
            chapter_plan=material,
            dense_context=str(material.get("dense_context") or ""),
            tone=state.get("tone") or "encouraging",
            digest_mode=state.get("digest_mode") or "systematic",
        )
        markdown = _ensure_chapter_heading(str(material.get("title") or f"第 {chapter_index} 章"), result.content)
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        draft = {
            "chapter_index": chapter_index,
            "title": str(material.get("title") or f"第 {chapter_index} 章"),
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
            "curated_source_count": int(material.get("curated_source_count", 0) or 0),
            "draft_ms": elapsed_ms,
            "word_count": len([token for token in markdown.split() if token]),
            "placeholder_count": markdown.count("[MERMAID:") + markdown.count("[IMAGE:") + markdown.count("[INTERACTIVE:"),
        }
        return {
            "chapter_drafts": [draft],
            "draft_ms": elapsed_ms,
            "llm_calls_total": 1,
        }

    return pedagogy_craft_node


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
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="enriching",
            digest_mode=state.get("digest_mode") or None,
            staged_chapter_count=len(chapter_metadatas),
            current_stage_description=f"已生成 {len(chapter_metadatas)} 章草稿，开始进行文档增强。",
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
        for chapter in chapter_metadatas:
            skill_context = SkillContext(
                subject=state["subject"],
                build_session_id=state.get("build_session_id", ""),
                workflow_context=context,
                planner_session_id=state.get("planner_session_id", ""),
                confirmed_plan_id=state.get("confirmed_plan_id", ""),
                digest_mode=state.get("digest_mode", ""),
                chapter_index=int(chapter.get("chapter_index", 0) or 0),
            )
            markdown = str(chapter.get("markdown") or "")
            if "[MERMAID:" in markdown and settings.enable_mermaid_generation:
                markdown = await MermaidGenerator(skill_context).process_placeholders(markdown)
            if "[IMAGE:" in markdown:
                markdown = await ImageGenerator(skill_context).process_placeholders(markdown)
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
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="injecting_examine",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="文档增强已完成，开始注入练习与自检内容。",
            draft_available=bool(merged_markdown.strip()),
        )
        return {
            "chapter_metadatas": chapter_metadatas,
            "enriched_markdown": merged_markdown,
            "merged_markdown": merged_markdown,
        }

    return enrich_document_node


def build_inject_examine_node(*, context: WorkflowContext):
    async def inject_examine_node(state: DocGenState) -> dict:
        chapter_metadatas = sorted(
            deepcopy(list(state.get("chapter_metadatas", []))),
            key=lambda item: item.get("chapter_index", 0),
        )
        if not chapter_metadatas:
            return {"error": "当前没有可用于注入练习内容的章节。"}

        question_titles = [str(chapter.get("title") or "").strip() for chapter in chapter_metadatas[:3] if str(chapter.get("title") or "").strip()]
        exam_questions = [
            {
                "question_index": index,
                "type": "short_answer",
                "question": f"请解释《{title}》的核心思想，并把它和一个具体例子联系起来。",
            }
            for index, title in enumerate(question_titles, start=1)
        ]
        practice_markdown = _build_examine_markdown(question_titles)
        next_index = max(int(chapter.get("chapter_index", 0) or 0) for chapter in chapter_metadatas) + 1
        chapter_metadatas.append(
            {
                "chapter_index": next_index,
                "title": "练习与自检",
                "markdown": practice_markdown,
                "summary": "本章之后的练习提示与自检问题。",
                "tags": ["practice", "self_check"],
                "digest_mode": state.get("digest_mode") or "",
                "source_file_ids": sorted(
                    {
                        int(file_id)
                        for chapter in chapter_metadatas
                        for file_id in chapter.get("source_file_ids", [])
                    }
                ),
                "sources": [],
                "source_details": [],
            }
        )
        merged_markdown = prepend_table_of_contents(
            build_merged_markdown(
                chapter_metadatas,
                document_context=dict(state.get("document_context") or {}),
            ),
            min_level=2,
            max_level=4,
        )
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="publishing",
            digest_mode=state.get("digest_mode") or None,
            staged_chapter_count=len(chapter_metadatas),
            current_stage_description="文档组装完成，开始发布知识文档。",
            draft_available=bool(merged_markdown.strip()),
        )
        return {
            "chapter_metadatas": chapter_metadatas,
            "exam_questions": exam_questions,
            "merged_markdown": merged_markdown,
            "enriched_markdown": merged_markdown,
        }

    return inject_examine_node


def _normalize_chapter_assignments(chapters: list[dict[str, Any]], *, default_source_file_ids: list[int]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, chapter in enumerate(chapters, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        normalized.append(
            {
                "chapter_index": chapter_index,
                "title": str(chapter.get("title") or f"第 {chapter_index} 章"),
                "objective": str(chapter.get("objective") or ""),
                "required_elements": [str(item) for item in chapter.get("required_elements", []) if str(item).strip()],
                "search_queries": [str(item) for item in chapter.get("search_queries", []) if str(item).strip()],
                "writing_instructions": str(chapter.get("writing_instructions") or ""),
                "media_hints": dict(chapter.get("media_hints") or {"images": [], "mermaid": [], "interactive": []}),
                "source_file_ids": list(chapter.get("source_file_ids") or default_source_file_ids),
            }
        )
    return normalized


def _serialize_section(section: Any) -> dict[str, Any]:
    if hasattr(section, "model_dump"):
        return section.model_dump(mode="json")
    return dict(section)


def _ensure_chapter_heading(title: str, markdown: str) -> str:
    cleaned = (markdown or "").strip()
    if not cleaned.startswith("#"):
        cleaned = f"# {title}\n\n{cleaned}".strip()
    return cleaned + "\n"


def _build_examine_markdown(question_titles: list[str]) -> str:
    prompts = question_titles or ["整份文档"]
    lines = ["# 练习与自检", "", "## 简答题", ""]
    for index, title in enumerate(prompts, start=1):
        lines.append(f"{index}. 请用自己的话解释《{title}》最重要的知识点，并补一个你能想到的例子。")
    lines.extend(
        [
            "",
            "## 复盘问题",
            "",
            "- 现在哪一章你仍然最不确定？原因是什么？",
            "- 哪个公式、定义或推理步骤最值得你再回头看一遍？",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def get_langgraph_dev_docgen_graph() -> StateGraph:
    """Create the DocGen graph used by ``langgraph dev``."""

    return build_docgen_graph(context=create_langgraph_dev_context("digest.docgen.langgraph_dev"))



