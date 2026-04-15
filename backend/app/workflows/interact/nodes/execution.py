"""Execution mode node builders for the interact workflow."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.interact.state import InteractWorkflowState
from app.workflows.interact.support.execution import select_execution_mode


def build_select_execution_mode_node(*, context: WorkflowContext):
    """Build the node that chooses one bounded execution mode."""

    workflow_logger = context.get_logger()

    def select_mode(state: InteractWorkflowState) -> InteractWorkflowState:
        execution_mode = select_execution_mode(
            question=state["question"],
            selected_context=state.get("selected_context"),
            strategy_mode=state["strategy_mode"],
            retrieval_results=state.get("retrieval_results", []),
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


__all__ = ["build_select_execution_mode_node"]


