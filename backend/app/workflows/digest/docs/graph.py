"""Docs lane LangGraph definition."""

from __future__ import annotations

from datetime import datetime

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.nodes.cleanse_node import build_cleanse_node
from app.workflows.digest.docs.nodes.draft_node import build_draft_chapter_node
from app.workflows.digest.docs.nodes.finalize_node import build_finalize_assemble_node
from app.workflows.digest.docs.nodes.load_files_node import build_load_files_node
from app.workflows.digest.docs.nodes.metadata_node import build_extract_metadata_node
from app.workflows.digest.docs.nodes.outline_map_node import build_outline_map_node
from app.workflows.digest.docs.nodes.outline_reduce_node import build_outline_reduce_node
from app.workflows.digest.docs.nodes.review_node import build_review_chapter_node
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy


def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the docs lane graph."""

    workflow = StateGraph(DocGenState)
    strategy = DocGenExecutionStrategy.from_settings()

    workflow.add_node("load_files", build_load_files_node(context=context, strategy=strategy))
    workflow.add_node("cleanse", build_cleanse_node(context=context, strategy=strategy))
    workflow.add_node("outline_map", build_outline_map_node(context=context))
    workflow.add_node("outline_reduce", build_outline_reduce_node(context=context, strategy=strategy))
    workflow.add_node("draft_chapter", build_draft_chapter_node(context=context, strategy=strategy))
    workflow.add_node("collect_drafts", build_collect_drafts_node(context=context))
    workflow.add_node("review_chapter", build_review_chapter_node(context=context, strategy=strategy))
    workflow.add_node("collect_reviews", build_collect_reviews_node(context=context))
    workflow.add_node("extract_metadata", build_extract_metadata_node(context=context, strategy=strategy))
    workflow.add_node("finalize_assemble", build_finalize_assemble_node(context=context))

    workflow.set_entry_point("load_files")
    workflow.add_conditional_edges("load_files", route_after_step, {"continue": "cleanse", "fail": END})
    workflow.add_conditional_edges("cleanse", route_after_step, {"continue": "outline_map", "fail": END})
    workflow.add_edge("outline_map", "outline_reduce")
    workflow.add_conditional_edges("outline_reduce", fan_out_to_draft)
    workflow.add_edge("draft_chapter", "collect_drafts")
    workflow.add_conditional_edges("collect_drafts", fan_out_to_review)
    workflow.add_edge("review_chapter", "collect_reviews")
    workflow.add_conditional_edges("collect_reviews", fan_out_to_metadata)
    workflow.add_edge("extract_metadata", "finalize_assemble")
    workflow.add_edge("finalize_assemble", END)
    return workflow


def create_docgen_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    user_prompt: str | None,
    requested_at: datetime,
    build_session_id: str | None,
) -> DocGenState:
    """Create initial docs lane state."""

    return {
        "subject": subject,
        "file_ids": file_ids,
        "user_prompt": user_prompt,
        "requested_at": requested_at,
        "build_session_id": build_session_id or "",
        "error": None,
    }


def route_after_step(state: DocGenState) -> str:
    """Route to continue or fail."""

    return "fail" if state.get("error") else "continue"


def fan_out_to_draft(state: DocGenState) -> list[Send]:
    """Fan out chapter drafting."""

    assignments = state.get("chapter_assignments", [])
    outline_tree = state.get("outline_tree", {})
    shared_inputs = state.get("shared_inputs")
    total = len(assignments)
    sends: list[Send] = []
    for index, chapter in enumerate(assignments):
        prev_summary = ""
        if index > 0:
            prev_chapter = assignments[index - 1]
            prev_source = "\n".join(prev_chapter.get("source_contents", []))[:400]
            prev_summary = f"Previous chapter {prev_chapter['title']} summary:\n{prev_source}"

        next_preview = ""
        if index < total - 1:
            next_chapter = assignments[index + 1]
            next_preview = f"Next chapter preview: {next_chapter['title']}"

        sends.append(
            Send(
                "draft_chapter",
                {
                    "chapter": chapter,
                    "subject": state["subject"],
                    "requested_at": state["requested_at"],
                    "outline_tree": outline_tree,
                    "total_chapters": total,
                    "user_prompt": state.get("user_prompt"),
                    "shared_inputs": shared_inputs,
                    "build_session_id": state.get("build_session_id", ""),
                    "prev_summary": prev_summary,
                    "next_preview": next_preview,
                },
            )
        )
    return sends


def fan_out_to_review(state: DocGenState) -> list[Send]:
    """Fan out chapter review."""

    drafts = state.get("chapter_drafts", [])
    outline_tree = state.get("outline_tree", {})
    total = len(drafts)
    return [
        Send(
            "review_chapter",
            {
                "draft": draft,
                "outline_tree": outline_tree,
                "total_chapters": total,
                "user_prompt": state.get("user_prompt"),
                "requested_at": state["requested_at"],
                "subject": state["subject"],
                "build_session_id": state.get("build_session_id", ""),
            },
        )
        for draft in drafts
    ]


def fan_out_to_metadata(state: DocGenState) -> list[Send]:
    """Fan out metadata extraction."""

    reviews = state.get("chapter_reviews", [])
    assignments = state.get("chapter_assignments", [])
    sends: list[Send] = []
    for reviewed in reviews:
        chapter_index = reviewed.get("chapter_index", 0)
        source_file_ids: list[int] = []
        chunk_uids: list[str] = list(reviewed.get("chunk_uids", []))
        for assignment in assignments:
            if assignment.get("chapter_index") != chapter_index:
                continue
            source_file_ids = assignment.get("source_file_ids", [])
            if not chunk_uids:
                chunk_uids = assignment.get("chunk_uids", [])
            break
        sends.append(
            Send(
                "extract_metadata",
                {
                    "reviewed": {
                        **reviewed,
                        "source_file_ids": source_file_ids,
                        "chunk_uids": chunk_uids,
                    },
                    "requested_at": state["requested_at"],
                },
            )
        )
    return sends


def build_collect_drafts_node(*, context: WorkflowContext):
    """Collect draft fan-out results."""

    async def collect_drafts(state: DocGenState) -> dict:
        context.get_logger().bind(node="collect_drafts").info(
            "docgen_draft_collection_completed",
            chapter_count=len(state.get("chapter_drafts", [])),
        )
        return {}

    return collect_drafts


def build_collect_reviews_node(*, context: WorkflowContext):
    """Collect review fan-out results."""

    async def collect_reviews(state: DocGenState) -> dict:
        context.get_logger().bind(node="collect_reviews").info(
            "docgen_review_collection_completed",
            chapter_count=len(state.get("chapter_reviews", [])),
        )
        return {}

    return collect_reviews
