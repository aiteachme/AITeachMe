"""Teaching strategy node builders for the interact workflow."""

from __future__ import annotations

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.interact.state import InteractWorkflowState
from app.workflows.interact.support.strategies import select_teaching_strategy


def build_select_teaching_strategy_node(*, context: WorkflowContext):
    """Build the node that chooses a lightweight teaching strategy."""

    workflow_logger = context.get_logger()

    def select_strategy(state: InteractWorkflowState) -> InteractWorkflowState:
        strategy_mode = select_teaching_strategy(
            question=state["question"],
            selected_context=state.get("selected_context"),
        )
        workflow_logger.info(
            "interact_strategy_selected",
            strategy_mode=strategy_mode.value,
        )
        return {
            **state,
            "strategy_mode": strategy_mode,
        }

    return select_strategy


