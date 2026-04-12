"""DocGen LangGraph definition."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from app.utils.docgen_store import update_knowledge_build_status
from app.workflows.common import wrap_traceable_run
from app.workflows.common.context import WorkflowContext, create_langgraph_dev_context
from app.workflows.digest.docgen.nodes import (
    build_collect_drafts_node,
    build_collect_materials_node,
    build_enrich_document_node,
    build_finalize_assemble_node,
    build_inject_examine_node,
    build_load_context_node,
    build_pedagogy_craft_node,
    build_resolve_titles_node,
    build_targeted_research_node,
)
from app.workflows.digest.docgen.nodes.common import resolve_docgen_course_type, resolve_docgen_retrieval_profile
from app.workflows.digest.docgen.state import DocGenState

def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the DocGen graph."""

    workflow = StateGraph(DocGenState)
    workflow.add_node(
        "load_context",
        wrap_traceable_run(
            build_load_context_node(context=context),
            run_type="chain",
            workflow=context.workflow_name,
            lane="docgen",
            name="load_context",
            timing_field="load_ms",
        ),
    )
    workflow.add_node(
        "targeted_research",
        wrap_traceable_run(
            build_targeted_research_node(context=context),
            run_type="chain",
            workflow=context.workflow_name,
            lane="docgen",
            name="targeted_research",
        ),
    )
    workflow.add_node(
        "collect_materials",
        wrap_traceable_run(
            build_collect_materials_node(context=context),
            run_type="chain",
            workflow=context.workflow_name,
            lane="docgen",
            name="collect_materials",
        ),
    )
    workflow.add_node(
        "resolve_titles",
        wrap_traceable_run(
            build_resolve_titles_node(context=context),
            run_type="chain",
            workflow=context.workflow_name,
            lane="docgen",
            name="resolve_titles",
        ),
    )
    workflow.add_node(
        "pedagogy_craft",
        wrap_traceable_run(
            build_pedagogy_craft_node(context=context),
            run_type="chain",
            workflow=context.workflow_name,
            lane="docgen",
            name="pedagogy_craft",
        ),
    )
    workflow.add_node(
        "collect_drafts",
        wrap_traceable_run(
            build_collect_drafts_node(context=context),
            run_type="chain",
            workflow=context.workflow_name,
            lane="docgen",
            name="collect_drafts",
        ),
    )
    workflow.add_node(
        "enrich_document",
        wrap_traceable_run(
            build_enrich_document_node(context=context),
            run_type="chain",
            workflow=context.workflow_name,
            lane="docgen",
            name="enrich_document",
            timing_field="enrich_ms",
        ),
    )
    workflow.add_node(
        "inject_examine",
        wrap_traceable_run(
            build_inject_examine_node(context=context),
            run_type="chain",
            workflow=context.workflow_name,
            lane="docgen",
            name="inject_examine",
            timing_field="examine_ms",
        ),
    )
    workflow.add_node(
        "finalize_assemble",
        wrap_traceable_run(
            build_finalize_assemble_node(context=context),
            run_type="chain",
            workflow=context.workflow_name,
            lane="docgen",
            name="finalize_assemble",
        ),
    )

    workflow.set_entry_point("load_context")
    workflow.add_conditional_edges("load_context", route_after_load_context, {"continue": "targeted_research", "fail": END})
    workflow.add_edge("targeted_research", "collect_materials")
    workflow.add_edge("collect_materials", "resolve_titles")
    workflow.add_conditional_edges("resolve_titles", build_craft_sends)
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


def get_langgraph_dev_docgen_graph() -> StateGraph:
    """Create the DocGen graph used by ``langgraph dev``."""

    return build_docgen_graph(context=create_langgraph_dev_context("digest.docgen.langgraph_dev"))


__all__ = [
    "build_collect_drafts_node",
    "build_collect_materials_node",
    "build_craft_sends",
    "build_docgen_graph",
    "build_enrich_document_node",
    "build_inject_examine_node",
    "build_load_context_node",
    "build_pedagogy_craft_node",
    "build_resolve_titles_node",
    "build_research_sends",
    "build_targeted_research_node",
    "create_docgen_initial_state",
    "get_langgraph_dev_docgen_graph",
    "route_after_load_context",
    "route_after_step",
    "update_knowledge_build_status",
]
