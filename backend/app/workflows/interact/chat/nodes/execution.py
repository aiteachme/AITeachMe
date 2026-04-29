"""Execution mode node builders for the interact workflow."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.interact.chat.state import InteractWorkflowState
from app.workflows.interact.chat.lib.execution import select_execution_mode
from app.workflows.interact.chat.lib.intent import has_entry_context, should_use_course_grounding


def build_select_execution_mode_node(*, context: WorkflowContext):
    """Build the node that chooses one bounded execution mode."""

    workflow_logger = context.get_logger()

    def select_mode(state: InteractWorkflowState) -> InteractWorkflowState:
        has_primary_context = has_entry_context(
            selected_context=state.get("selected_context"),
            selection_context=state.get("selection_context"),
        )
        execution_mode = select_execution_mode(
            question=state["question"],
            selected_context=(
                state.get("selected_context")
                or _selection_text(state.get("selection_context"))
            ),
            strategy_mode=state["strategy_mode"],
            retrieval_results=state.get("retrieval_results", []),
            allow_course_tools=should_use_course_grounding(
                question=state["question"],
                source=state.get("source"),
                has_primary_context=has_primary_context,
            ),
        )
        workflow_logger.info(
            "interact_execution_mode_selected",
            execution_mode=execution_mode.value,
            retrieval_count=len(state.get("retrieval_results", [])),
        )
        return {
            **state,
            "execution_mode": execution_mode,
        }

    return select_mode


def _selection_text(selection_context: object | None) -> str:
    if selection_context is None:
        return ""
    return str(getattr(selection_context, "selected_text", "") or "")


__all__ = ["build_select_execution_mode_node"]
