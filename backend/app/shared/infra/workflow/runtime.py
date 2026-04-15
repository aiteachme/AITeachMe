"""Workflow runtime helpers for LangGraph-based workflows."""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

import structlog

from app.shared.infra.observability.trace import (
    build_langsmith_metadata,
    build_langsmith_tags,
    get_langsmith_project_name,
    langsmith_tracing_enabled,
    llm_trace_scope,
)
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.result import WorkflowResult, err_result, ok_result

logger = structlog.get_logger(__name__)


def _build_graph_config(
    *,
    workflow_name: str,
    subject: str = "",
    build_session_id: str = "",
    lane: str = "",
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build LangGraph invoke config that propagates to LangSmith."""

    metadata = build_langsmith_metadata(
        subject=subject,
        build_session_id=build_session_id,
        workflow=workflow_name,
        lane=lane,
        extra_metadata=extra_metadata,
    )
    tags = build_langsmith_tags(
        workflow=workflow_name,
        lane=lane,
    )

    config: dict[str, Any] = {
        "run_name": workflow_name,
        "tags": tags,
        "metadata": metadata,
    }
    if langsmith_tracing_enabled():
        project_name = get_langsmith_project_name()
        if project_name:
            config["project_name"] = project_name
    return config


async def cancel_tasks_and_drain(tasks: list[asyncio.Task[Any]]) -> None:
    """Cancel spawned tasks and await their termination."""

    active_tasks = [task for task in tasks if task is not None and not task.done()]
    for task in active_tasks:
        task.cancel()
    if active_tasks:
        await asyncio.gather(*active_tasks, return_exceptions=True)


async def invoke_state_graph(
    *,
    workflow_name: str,
    graph_builder,
    initial_state: Any,
    subject: str = "",
    build_session_id: str = "",
    lane: str = "",
    extra_metadata: dict[str, Any] | None = None,
) -> Any:
    """Execute a StateGraph directly while preserving shared trace context."""

    config = _build_graph_config(
        workflow_name=workflow_name,
        subject=subject,
        build_session_id=build_session_id,
        lane=lane,
        extra_metadata=extra_metadata,
    )
    with llm_trace_scope(
        subject=subject,
        build_session_id=build_session_id,
        workflow=workflow_name,
        lane=lane,
    ):
        graph = graph_builder()
        compiled = graph.compile()
        return await compiled.ainvoke(initial_state, config=config)


async def run_state_graph(
    *,
    workflow_name: str,
    graph_builder,
    initial_state: Any,
    context: WorkflowContext,
) -> WorkflowResult[Any]:
    """Run one LangGraph workflow and normalize result handling."""

    workflow_logger = context.get_logger()
    started_at = perf_counter()
    workflow_logger.info("workflow_started", workflow_name=workflow_name)

    build_session_id = str(context.metadata.get("build_session_id", ""))
    lane = str(context.metadata.get("lane", "") or "")
    config = _build_graph_config(
        workflow_name=workflow_name,
        subject=context.subject,
        build_session_id=build_session_id,
        lane=lane,
        extra_metadata={"context_metadata": dict(context.metadata)},
    )

    try:
        with llm_trace_scope(
            subject=context.subject,
            build_session_id=build_session_id,
            workflow=workflow_name,
            lane=lane,
        ):
            graph = graph_builder()
            compiled = graph.compile()
            final_state = await compiled.ainvoke(initial_state, config=config)

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

