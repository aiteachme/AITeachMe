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
    build_confirm_and_dispatch_node,
    build_enhance_chapters_node,
    build_generate_chapters_node,
    build_load_context_node,
    build_merge_review_node,
    build_prepare_parallel_inputs_node,
    build_publish_document_node,
)
from app.workflows.digest.docgen.nodes.common import resolve_docgen_course_type, resolve_docgen_retrieval_profile
from app.workflows.digest.docgen.state import DocGenState


def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the rewritten DocGen graph."""

    workflow = StateGraph(DocGenState)
    trace = workflow_tracer(context=context, lane="docgen")
    workflow.add_node(
        "load_context",
        trace.node(build_load_context_node(context=context), name="load_context", timing_field="load_ms"),
    )
    workflow.add_node(
        "prepare_parallel_inputs",
        trace.node(
            build_prepare_parallel_inputs_node(context=context),
            name="prepare_parallel_inputs",
            timing_field="prepare_ms",
        ),
    )
    workflow.add_node(
        "confirm_and_dispatch",
        trace.node(
            build_confirm_and_dispatch_node(context=context),
            name="confirm_and_dispatch",
            timing_field="dispatch_ms",
        ),
    )
    workflow.add_node(
        "generate_chapters",
        trace.node(build_generate_chapters_node(context=context), name="generate_chapters"),
    )
    workflow.add_node(
        "enhance_chapters",
        trace.node(build_enhance_chapters_node(context=context), name="enhance_chapters"),
    )
    workflow.add_node(
        "merge_review",
        trace.node(build_merge_review_node(context=context), name="merge_review", timing_field="merge_review_ms"),
    )
    workflow.add_node(
        "publish_document",
        trace.node(build_publish_document_node(context=context), name="publish_document"),
    )

    workflow.set_entry_point("load_context")
    workflow.add_conditional_edges(
        "load_context",
        route_after_step,
        {"continue": "prepare_parallel_inputs", "fail": END},
    )
    workflow.add_conditional_edges(
        "prepare_parallel_inputs",
        route_after_step,
        {"continue": "confirm_and_dispatch", "fail": END},
    )
    workflow.add_conditional_edges(
        "confirm_and_dispatch",
        build_generation_sends,
        {"fail": END},
    )
    workflow.add_edge("generate_chapters", "enhance_chapters")
    workflow.add_edge("enhance_chapters", "merge_review")
    workflow.add_conditional_edges(
        "merge_review",
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
        "docgen_context": {},
        "error": None,
    }


def route_after_step(state: DocGenState) -> Literal["fail", "continue"]:
    return "fail" if state.get("error") else "continue"


def build_generation_sends(state: DocGenState) -> list[Send] | Literal["fail"]:
    if state.get("error"):
        return "fail"
    tasks = sorted(
        list(state.get("chapter_tasks", [])),
        key=lambda item: int(item.get("chapter_index", 0) or 0),
    )
    if not tasks:
        return "fail"
    total = len(tasks)
    return [
        Send(
            "generate_chapters",
            {
                "subject": state["subject"],
                "requested_at": state["requested_at"],
                "build_session_id": state.get("build_session_id", ""),
                "planner_session_id": state.get("planner_session_id", ""),
                "confirmed_plan_id": state.get("confirmed_plan_id", ""),
                "digest_mode": state.get("digest_mode", ""),
                "course_type": state.get("course_type", ""),
                "retrieval_profile": state.get("retrieval_profile", ""),
                "teaching_action": "chapter_generate",
                "tone": state.get("tone", ""),
                "selected_skillpacks": list(state.get("selected_skillpacks", []) or []),
                "shared_inputs": state.get("shared_inputs"),
                "document_context": state.get("document_context"),
                "docgen_context": state.get("docgen_context"),
                "chapter_task": task,
                "total_chapters": total,
            },
        )
        for task in tasks
    ]


def get_langgraph_dev_docgen_graph() -> StateGraph:
    """Create the DocGen graph used by ``langgraph dev``."""

    return build_docgen_graph(context=create_langgraph_dev_context("digest.docgen.langgraph_dev"))


__all__ = [
    "build_docgen_graph",
    "build_generation_sends",
    "create_docgen_initial_state",
    "get_langgraph_dev_docgen_graph",
    "route_after_step",
    "update_knowledge_build_status",
]
