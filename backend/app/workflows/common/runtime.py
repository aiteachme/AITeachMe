"""LangGraph 运行时薄封装。"""

from __future__ import annotations

from typing import Any

from app.workflows.common.context import WorkflowContext
from app.workflows.common.result import WorkflowResult, err_result, ok_result


async def run_state_graph(
    *,
    workflow_name: str,
    graph_builder,
    initial_state: Any,
    context: WorkflowContext,
) -> WorkflowResult[Any]:
    """执行一次 LangGraph StateGraph。"""

    workflow_logger = context.get_logger()
    workflow_logger.info("workflow_started", workflow_name=workflow_name)
    try:
        graph = graph_builder()
        compiled = graph.compile()
        final_state = await compiled.ainvoke(initial_state)
        workflow_logger.info("workflow_completed", workflow_name=workflow_name)
        return ok_result(final_state)
    except Exception as exc:
        workflow_logger.exception(
            "workflow_failed",
            workflow_name=workflow_name,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return err_result(
            "workflow_execution_failed",
            str(exc),
            metadata={"workflow_name": workflow_name},
        )
