"""Workflow runtime helpers for LangGraph-based workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from time import perf_counter
from typing import Any, TypeVar

import structlog
from langsmith import tracing_context
from langsmith.run_helpers import get_current_run_tree

from app.shared.infra.observability.trace import (
    build_langsmith_metadata,
    build_langsmith_tags,
    get_langsmith_project_name,
    langsmith_trace,
    langsmith_child_runs_suppressed,
    langsmith_tracing_enabled,
    llm_trace_scope,
    sanitize_langsmith_input,
    sanitize_langsmith_output,
)
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.result import WorkflowResult, err_result, ok_result

logger = structlog.get_logger(__name__)

T = TypeVar("T")

_GRAPH_STATE_SCALAR_FIELDS = (
    "course_id",
    "course_name",
    "user_id",
    "build_session_id",
    "planner_session_id",
    "confirmed_plan_id",
    "digest_mode",
    "retrieval_profile",
    "teaching_action",
    "error",
)
_GRAPH_STATE_COUNT_FIELDS = (
    "file_ids",
    "raw_chunks",
    "chapter_assignments",
    "locked_titles",
    "file_summaries",
    "chapter_tasks",
    "chapter_drafts",
    "enhanced_chapter_drafts",
    "reviewed_chapter_drafts",
    "research_traces",
    "evidence_ledgers",
    "claim_ledgers",
    "conflict_reports",
    "asset_manifests",
    "chapter_metadatas",
    "doc_ids",
    "built_paths",
)
_GRAPH_STATE_TEXT_LENGTH_FIELDS = (
    "user_prompt",
    "merged_markdown",
    "enriched_markdown",
)


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
    """Disable LangGraph's automatic state dump while keeping explicit spans."""

    if langsmith_child_runs_suppressed() or not langsmith_tracing_enabled():
        return tracing_context(enabled=False)
    parent = get_current_run_tree()
    if parent is not None:
        return tracing_context(enabled=False, parent=parent)
    return tracing_context(enabled=False)


def _compact_graph_state(value: Any, *, phase: str, elapsed_ms: int | None = None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"phase": phase, "state_type": type(value).__name__}

    payload: dict[str, Any] = {
        "phase": phase,
        "state_key_count": len(value),
        "state_keys_preview": sorted(str(key) for key in value.keys())[:30],
    }
    if elapsed_ms is not None:
        payload["elapsed_ms"] = elapsed_ms

    for field_name in _GRAPH_STATE_SCALAR_FIELDS:
        field_value = value.get(field_name)
        if field_value not in (None, "", [], {}):
            payload[field_name] = field_value

    for field_name in _GRAPH_STATE_COUNT_FIELDS:
        field_value = value.get(field_name)
        if isinstance(field_value, (list, tuple, set)):
            payload[f"{field_name}_count"] = len(field_value)
        elif isinstance(field_value, dict):
            payload[f"{field_name}_key_count"] = len(field_value)

    for field_name in _GRAPH_STATE_TEXT_LENGTH_FIELDS:
        field_value = value.get(field_name)
        if isinstance(field_value, str) and field_value:
            payload[f"{field_name}_chars"] = len(field_value)

    for field_name in ("llm_calls_total", "llm_calls_skipped", "workflow_elapsed_ms"):
        field_value = value.get(field_name)
        if field_value not in (None, ""):
            payload[field_name] = field_value

    return payload


def _compact_graph_inputs(initial_state: Any) -> dict[str, Any]:
    return sanitize_langsmith_input(
        _compact_graph_state(initial_state, phase="input"),
        field_name="workflow_state",
    )


def _compact_graph_outputs(final_state: Any, *, elapsed_ms: int) -> dict[str, Any]:
    return sanitize_langsmith_output(
        _compact_graph_state(final_state, phase="output", elapsed_ms=elapsed_ms),
        field_name="workflow_state",
    )


def _end_graph_trace(trace_run: Any | None, final_state: Any, *, elapsed_ms: int) -> None:
    if trace_run is None:
        return
    outputs = _compact_graph_outputs(final_state, elapsed_ms=elapsed_ms)
    trace_error = outputs.get("error")
    if trace_error:
        trace_run.end(outputs=outputs, error=str(trace_error))
        return
    trace_run.end(outputs=outputs)


async def cancel_tasks_and_drain(tasks: list[asyncio.Task[Any]]) -> None:
    """Cancel spawned tasks and await their termination."""

    active_tasks = [task for task in tasks if task is not None and not task.done()]
    for task in active_tasks:
        task.cancel()
    if active_tasks:
        await asyncio.gather(*active_tasks, return_exceptions=True)


async def await_shielded_and_drain(awaitable: Awaitable[T]) -> T:
    """Finish an operation before propagating caller cancellation."""

    task = asyncio.ensure_future(awaitable)
    cancelled_error: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError as exc:
            cancelled_error = cancelled_error or exc
        except BaseException:
            break

    try:
        result = task.result()
    except BaseException:
        if cancelled_error is not None:
            raise cancelled_error
        raise
    if cancelled_error is not None:
        raise cancelled_error
    return result


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
    with llm_trace_scope(
        course_id=course_id,
        build_session_id=build_session_id,
        workflow=workflow_name,
        lane=lane,
    ):
        with langsmith_trace(
            name=str((extra_metadata or {}).get("langsmith_run_name") or workflow_name),
            run_type="chain",
            inputs=_compact_graph_inputs(initial_state),
            course_id=course_id,
            build_session_id=build_session_id,
            workflow=workflow_name,
            lane=lane,
            extra_metadata={
                "workflow_trace_kind": "compact_langgraph_root",
                **dict(extra_metadata or {}),
            },
        ) as trace_run:
            with _graph_tracing_context():
                graph = graph_builder()
                compiled = graph.compile()
                started_at = perf_counter()
                final_state = await compiled.ainvoke(initial_state, config=config)
            _end_graph_trace(
                trace_run,
                final_state,
                elapsed_ms=int((perf_counter() - started_at) * 1000),
            )
            return final_state


async def run_state_graph(
    *,
    workflow_name: str,
    graph_builder,
    initial_state: Any,
    context: WorkflowContext,
    trace_as_root: bool = True,
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
        with llm_trace_scope(
            course_id=context.course_id,
            build_session_id=build_session_id,
            workflow=workflow_name,
            lane=lane,
        ):
            if trace_as_root:
                with langsmith_trace(
                    name=str(context.metadata.get("langsmith_run_name") or workflow_name),
                    run_type="chain",
                    inputs=_compact_graph_inputs(initial_state),
                    course_id=context.course_id,
                    build_session_id=build_session_id,
                    workflow=workflow_name,
                    lane=lane,
                    extra_metadata={
                        "workflow_trace_kind": "compact_langgraph_root",
                        "context_metadata": dict(context.metadata),
                    },
                ) as trace_run:
                    with _graph_tracing_context():
                        graph = graph_builder()
                        compiled = graph.compile()
                        final_state = await compiled.ainvoke(initial_state, config=config)
                    elapsed_ms = int((perf_counter() - started_at) * 1000)
                    _end_graph_trace(trace_run, final_state, elapsed_ms=elapsed_ms)
            else:
                with _graph_tracing_context():
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
