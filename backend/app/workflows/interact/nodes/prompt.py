"""Prompt-building node builders for the interact workflow."""

from __future__ import annotations

from app.workflows.common.context import WorkflowContext
from app.workflows.interact.state import InteractWorkflowState
from app.workflows.interact.support.messages import build_chat_messages


def build_prompt_node(*, context: WorkflowContext):
    """Build the node that assembles the final prompt messages."""

    workflow_logger = context.get_logger()

    def build_prompt(state: InteractWorkflowState) -> InteractWorkflowState:
        messages = build_chat_messages(
            subject=state["subject"],
            strategy_mode=state["strategy_mode"],
            retrieval_results=state.get("retrieval_results", []),
            recent_messages=state.get("recent_messages", []),
            weak_points=state.get("weak_points", []),
            recent_mistakes=state.get("recent_mistakes", []),
            question=state["question"],
            selected_context=state.get("selected_context"),
            source_chunk_id=state.get("source_chunk_id"),
        )
        workflow_logger.info(
            "interact_prompt_built",
            message_count=len(messages),
            citation_count=len(state.get("contexts") or []),
        )
        return {
            **state,
            "messages": messages,
        }

    return build_prompt
