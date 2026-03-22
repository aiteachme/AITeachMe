"""DocGen LangGraph definition."""

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


def _route_after_step(state: DocGenState) -> str:
    if state.get("error"):
        return "fail"
    return "continue"


def _fan_out_to_draft(state: DocGenState) -> list[Send]:
    assignments = state.get("chapter_assignments", [])
    outline_tree = state.get("outline_tree", {})
    total = len(assignments)

    sends: list[Send] = []
    for index, chapter in enumerate(assignments):
        prev_summary = ""
        if index > 0:
            prev_chapter = assignments[index - 1]
            prev_source = "\n".join(prev_chapter.get("source_contents", []))[:400]
            prev_summary = f"上一章《{prev_chapter['title']}》内容摘要：\n{prev_source}"

        next_preview = ""
        if index < total - 1:
            next_chapter = assignments[index + 1]
            next_preview = f"下一章《{next_chapter['title']}》将继续展开相关内容。"

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
                    "prev_summary": prev_summary,
                    "next_preview": next_preview,
                },
            )
        )
    return sends


def _fan_out_to_review(state: DocGenState) -> list[Send]:
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
            },
        )
        for draft in drafts
    ]


def _fan_out_to_metadata(state: DocGenState) -> list[Send]:
    reviews = state.get("chapter_reviews", [])
    assignments = state.get("chapter_assignments", [])
    sends: list[Send] = []
    for reviewed in reviews:
        chapter_index = reviewed.get("chapter_index", 0)
        source_file_ids: list[int] = []
        for assignment in assignments:
            if assignment.get("chapter_index") == chapter_index:
                source_file_ids = assignment.get("source_file_ids", [])
                break
        sends.append(
            Send(
                "extract_metadata",
                {
                    "reviewed": {**reviewed, "source_file_ids": source_file_ids},
                    "requested_at": state["requested_at"],
                },
            )
        )
    return sends


def build_collect_drafts_node(*, context: WorkflowContext):
    """Collect chapter drafts after fan-out."""

    async def collect_drafts(state: DocGenState) -> dict:
        drafts = state.get("chapter_drafts", [])
        context.get_logger().bind(node="collect_drafts").info(
            "docgen_draft_collection_completed",
            chapter_count=len(drafts),
            total_draft_ms=state.get("draft_ms", 0),
            llm_calls_total=state.get("llm_calls_total", 0),
            llm_calls_skipped=state.get("llm_calls_skipped", 0),
        )
        return {}

    return collect_drafts


def build_collect_reviews_node(*, context: WorkflowContext):
    """Collect chapter review results after fan-out."""

    async def collect_reviews(state: DocGenState) -> dict:
        reviews = state.get("chapter_reviews", [])
        context.get_logger().bind(node="collect_reviews").info(
            "docgen_review_collection_completed",
            chapter_count=len(reviews),
            total_review_ms=state.get("review_ms", 0),
            llm_calls_total=state.get("llm_calls_total", 0),
            llm_calls_skipped=state.get("llm_calls_skipped", 0),
        )
        return {}

    return collect_reviews


def build_docgen_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the knowledge docs fan-out workflow graph."""

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
    workflow.add_conditional_edges("load_files", _route_after_step, {"continue": "cleanse", "fail": END})
    workflow.add_conditional_edges("cleanse", _route_after_step, {"continue": "outline_map", "fail": END})
    workflow.add_edge("outline_map", "outline_reduce")
    workflow.add_conditional_edges("outline_reduce", _fan_out_to_draft)
    workflow.add_edge("draft_chapter", "collect_drafts")
    workflow.add_conditional_edges("collect_drafts", _fan_out_to_review)
    workflow.add_edge("review_chapter", "collect_reviews")
    workflow.add_conditional_edges("collect_reviews", _fan_out_to_metadata)
    workflow.add_edge("extract_metadata", "finalize_assemble")
    workflow.add_edge("finalize_assemble", END)

    return workflow


def create_docgen_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    user_prompt: str | None = None,
    requested_at: datetime,
) -> DocGenState:
    """Create the initial workflow state."""

    return DocGenState(
        subject=subject,
        file_ids=file_ids,
        user_prompt=user_prompt,
        requested_at=requested_at,
        error=None,
    )


__all__ = ["build_docgen_graph", "create_docgen_initial_state"]
