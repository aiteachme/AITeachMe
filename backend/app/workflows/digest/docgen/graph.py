"""DocGen LangGraph definition."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from app.utils.docgen_store import update_knowledge_build_status
from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.workflows.digest.docgen.nodes import (
    build_append_practice_node,
    build_enrich_assets_node,
    build_load_context_node,
    build_merge_drafts_node,
    build_merge_research_node,
    build_finalize_titles_node,
    build_publish_document_node,
    build_research_chapters_node,
    build_write_chapters_node,
)
from app.workflows.digest.docgen.nodes.common import resolve_docgen_course_type, resolve_docgen_retrieval_profile
from app.workflows.digest.docgen.state import DocGenState

def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the DocGen graph."""

    workflow = StateGraph(DocGenState)
    trace = workflow_tracer(context=context, lane="docgen")
    workflow.add_node(
        "load_context",
        trace.node(
            build_load_context_node(context=context),
            name="load_context",
            timing_field="load_ms",
        ),
    )
    workflow.add_node(
        "research_chapters",
        trace.node(
            build_research_chapters_node(context=context),
            name="research_chapters",
        ),
    )
    workflow.add_node(
        "merge_research",
        trace.node(
            build_merge_research_node(context=context),
            name="merge_research",
        ),
    )
    workflow.add_node(
        "finalize_titles",
        trace.node(
            build_finalize_titles_node(context=context),
            name="finalize_titles",
        ),
    )
    workflow.add_node(
        "write_chapters",
        trace.node(
            build_write_chapters_node(context=context),
            name="write_chapters",
        ),
    )
    workflow.add_node(
        "merge_drafts",
        trace.node(
            build_merge_drafts_node(context=context),
            name="merge_drafts",
        ),
    )
    workflow.add_node(
        "enrich_assets",
        trace.node(
            build_enrich_assets_node(context=context),
            name="enrich_assets",
            timing_field="enrich_ms",
        ),
    )
    workflow.add_node(
        "append_practice",
        trace.node(
            build_append_practice_node(context=context),
            name="append_practice",
            timing_field="examine_ms",
        ),
    )
    workflow.add_node(
        "publish_document",
        trace.node(
            build_publish_document_node(context=context),
            name="publish_document",
        ),
    )

    workflow.set_entry_point("load_context")
    workflow.add_conditional_edges(
        "load_context",
        route_after_load_context,
        {"continue": "research_chapters", "fail": END},
    )
    workflow.add_edge("research_chapters", "merge_research")
    workflow.add_edge("merge_research", "finalize_titles")
    workflow.add_conditional_edges(
        "finalize_titles",
        build_craft_sends,
        ["write_chapters"],
    )
    workflow.add_edge("write_chapters", "merge_drafts")
    workflow.add_conditional_edges(
        "merge_drafts",
        route_after_step,
        {"continue": "enrich_assets", "fail": END},
    )
    workflow.add_conditional_edges(
        "enrich_assets",
        route_after_step,
        {"continue": "append_practice", "fail": END},
    )
    workflow.add_conditional_edges(
        "append_practice",
        route_after_step,
        {"continue": "publish_document", "fail": END},
    )
    workflow.add_edge("publish_document", END)
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
    selected_skillpacks: list[str] | None = None,
) -> DocGenState:
    """Create initial state for the DocGen graph."""

    course_type = resolve_docgen_course_type(digest_mode)
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
        "course_type": course_type,
        "retrieval_profile": resolve_docgen_retrieval_profile(course_type),
        "teaching_action": "docgen_build",
        "tone": tone or "",
        "selected_skillpacks": list(selected_skillpacks or []),
        "document_context": None,
        "error": None,
    }


def route_after_step(state: DocGenState) -> Literal["fail", "continue"]:
    return "fail" if state.get("error") else "continue"


def route_after_load_context(state: DocGenState) -> list[Send] | Literal["fail"]:
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
            "research_chapters",
            {
                "subject": state["subject"],
                "requested_at": state["requested_at"],
                "build_session_id": state.get("build_session_id", ""),
                "planner_session_id": state.get("planner_session_id", ""),
                "confirmed_plan_id": state.get("confirmed_plan_id", ""),
                "digest_mode": state.get("digest_mode", ""),
                "course_type": state.get("course_type", ""),
                "retrieval_profile": state.get("retrieval_profile", ""),
                "teaching_action": "chapter_research",
                "tone": state.get("tone", ""),
                "selected_skillpacks": list(state.get("selected_skillpacks", []) or []),
                "shared_inputs": state.get("shared_inputs"),
                "document_context": state.get("document_context"),
                "chapter_assignment": chapter,
                "total_chapters": total,
            },
        )
        for chapter in assignments
    ]


def build_craft_sends(state: DocGenState) -> list[Send]:
    materials = sorted(
        _dedupe_chapter_items(
            list(state.get("title_resolved_chapter_materials", []) or state.get("chapter_materials", []))
        ),
        key=lambda item: item.get("chapter_index", 0),
    )
    total = len(materials)
    return [
        Send(
            "write_chapters",
            {
                "subject": state["subject"],
                "requested_at": state["requested_at"],
                "build_session_id": state.get("build_session_id", ""),
                "planner_session_id": state.get("planner_session_id", ""),
                "confirmed_plan_id": state.get("confirmed_plan_id", ""),
                "digest_mode": state.get("digest_mode", ""),
                "course_type": state.get("course_type", ""),
                "retrieval_profile": state.get("retrieval_profile", ""),
                "teaching_action": "chapter_write",
                "tone": state.get("tone", ""),
                "selected_skillpacks": list(state.get("selected_skillpacks", []) or []),
                "document_context": state.get("document_context"),
                "chapter_material": material,
                "total_chapters": total,
            },
        )
        for material in materials
    ]


def _chapter_item_score(item: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        1 if str(item.get("resolved_title") or "").strip() else 0,
        1 if str(item.get("dense_context") or "").strip() else 0,
        len(list(item.get("sources") or [])),
        len(str(item.get("research_summary") or "")),
    )


def _dedupe_chapter_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_index: dict[int, dict[str, Any]] = {}
    for item in items:
        chapter_index = int(item.get("chapter_index", 0) or 0)
        if chapter_index <= 0:
            continue
        existing = best_by_index.get(chapter_index)
        if existing is None or _chapter_item_score(item) >= _chapter_item_score(existing):
            best_by_index[chapter_index] = item
    return [best_by_index[index] for index in sorted(best_by_index)]


def get_langgraph_dev_docgen_graph() -> StateGraph:
    """Create the DocGen graph used by ``langgraph dev``."""

    return build_docgen_graph(context=create_langgraph_dev_context("digest.docgen.langgraph_dev"))


__all__ = [
    "build_append_practice_node",
    "build_craft_sends",
    "build_docgen_graph",
    "build_enrich_assets_node",
    "build_finalize_titles_node",
    "build_load_context_node",
    "build_merge_drafts_node",
    "build_merge_research_node",
    "build_publish_document_node",
    "build_research_chapters_node",
    "build_research_sends",
    "build_write_chapters_node",
    "create_docgen_initial_state",
    "get_langgraph_dev_docgen_graph",
    "route_after_load_context",
    "route_after_step",
    "update_knowledge_build_status",
]
