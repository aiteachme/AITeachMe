"""Workflow runtime helpers for LangGraph-based workflows."""

from __future__ import annotations

import asyncio
from contextlib import nullcontext
from time import perf_counter
from typing import Any

import structlog
from langsmith import tracing_context

from app.shared.infra.observability.trace import (
    build_langsmith_metadata,
    build_langsmith_tags,
    get_langsmith_project_name,
    langsmith_child_runs_suppressed,
    langsmith_tracing_enabled,
    llm_trace_scope,
)
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.result import WorkflowResult, err_result, ok_result

logger = structlog.get_logger(__name__)


def _build_graph_config(
    *,
    workflow_name: str,
    run_name: str | None = None,
    course_id: str = "",
    build_session_id: str = "",
    lane: str = "",
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build LangGraph invoke config that propagates to LangSmith."""

    metadata = build_langsmith_metadata(
        course_id=course_id,
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
        "run_name": str(run_name or workflow_name),
        "tags": tags,
        "metadata": metadata,
    }
    if langsmith_tracing_enabled():
        project_name = get_langsmith_project_name()
        if project_name:
            config["project_name"] = project_name
    return config


def _apply_graph_runtime_limits(config: dict[str, Any], metadata: dict[str, Any]) -> None:
    """Apply optional LangGraph runtime limits carried by workflow metadata."""

    raw_max_concurrency = metadata.get("max_concurrency")
    if raw_max_concurrency in (None, "", 0):
        return
    try:
        max_concurrency = int(raw_max_concurrency)
    except (TypeError, ValueError):
        return
    if max_concurrency > 0:
        config["max_concurrency"] = max_concurrency


def _graph_tracing_context():
    """Disable LangGraph tracing when the shared runtime says tracing is off."""

    if langsmith_child_runs_suppressed() or not langsmith_tracing_enabled():
        return tracing_context(enabled=False)
    return nullcontext()


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
    course_id: str = "",
    build_session_id: str = "",
    lane: str = "",
    extra_metadata: dict[str, Any] | None = None,
) -> Any:
    """Execute a StateGraph directly while preserving shared trace context."""

    config = _build_graph_config(
        workflow_name=workflow_name,
        run_name=str((extra_metadata or {}).get("langsmith_run_name") or workflow_name),
        course_id=course_id,
        build_session_id=build_session_id,
        lane=lane,
        extra_metadata=extra_metadata,
    )
    _apply_graph_runtime_limits(config, extra_metadata or {})
    with _graph_tracing_context():
        with llm_trace_scope(
            course_id=course_id,
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
        run_name=str(context.metadata.get("langsmith_run_name") or workflow_name),
        course_id=context.course_id,
        build_session_id=build_session_id,
        lane=lane,
        extra_metadata={"context_metadata": dict(context.metadata)},
    )
    _apply_graph_runtime_limits(config, dict(context.metadata))

    try:
        with _graph_tracing_context():
            with llm_trace_scope(
                course_id=context.course_id,
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
