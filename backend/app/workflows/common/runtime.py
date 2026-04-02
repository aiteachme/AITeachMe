"""LangGraph 运行时薄封装。"""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from app.workflows.common.context import WorkflowContext
from app.workflows.common.result import WorkflowResult, err_result, ok_result


async def cancel_tasks_and_drain(tasks: list[asyncio.Task[Any]]) -> None:
    """Cancel spawned tasks and await their termination."""

    active_tasks = [task for task in tasks if task is not None and not task.done()]
    for task in active_tasks:
        task.cancel()
    if active_tasks:
        await asyncio.gather(*active_tasks, return_exceptions=True)


async def run_state_graph(
    *,
    workflow_name: str,
    graph_builder,
    initial_state: Any,
    context: WorkflowContext,
) -> WorkflowResult[Any]:
    """执行一次 LangGraph StateGraph。"""

    workflow_logger = context.get_logger()
    started_at = perf_counter()
    workflow_logger.info("workflow_started", workflow_name=workflow_name)
    try:
        graph = graph_builder()
        compiled = graph.compile()
        final_state = await compiled.ainvoke(initial_state)
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        workflow_logger.info("workflow_completed", workflow_name=workflow_name, elapsed_ms=elapsed_ms)
        if isinstance(final_state, dict):
            final_state.setdefault("workflow_elapsed_ms", elapsed_ms)
        return ok_result(final_state)
    except asyncio.CancelledError:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        workflow_logger.warning("workflow_cancelled", workflow_name=workflow_name, elapsed_ms=elapsed_ms)
        raise
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        workflow_logger.exception(
            "workflow_failed",
            workflow_name=workflow_name,
            elapsed_ms=elapsed_ms,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return err_result(
            "workflow_execution_failed",
            str(exc),
            metadata={"workflow_name": workflow_name},
        )
