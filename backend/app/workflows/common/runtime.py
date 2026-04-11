"""LangGraph 运行时薄封装。"""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from app.shared.infra.tracing import langsmith_trace, langsmith_tracing_scope, llm_trace_scope
from app.workflows.common.context import WorkflowContext
from app.workflows.common.result import WorkflowResult, err_result, ok_result


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
    """Execute a StateGraph directly while preserving shared tracing context."""

    with llm_trace_scope(
        subject=subject,
        build_session_id=build_session_id,
        workflow=workflow_name,
        lane=lane,
    ):
        with langsmith_tracing_scope(
            subject=subject,
            build_session_id=build_session_id,
            workflow=workflow_name,
            lane=lane,
            extra_metadata=extra_metadata,
        ):
            with langsmith_trace(
                name=workflow_name,
                run_type="chain",
                inputs=_workflow_inputs(initial_state),
                subject=subject,
                build_session_id=build_session_id,
                workflow=workflow_name,
                lane=lane,
                node=workflow_name,
                extra_metadata=extra_metadata,
            ) as run:
                graph = graph_builder()
                compiled = graph.compile()
                result = await compiled.ainvoke(initial_state)
                if run is not None:
                    run.end(outputs=_workflow_outputs(result))
                return result


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
    build_session_id = str(context.metadata.get("build_session_id", ""))
    try:
        with llm_trace_scope(
            subject=context.subject,
            build_session_id=build_session_id,
            workflow=workflow_name,
        ):
            with langsmith_tracing_scope(
                subject=context.subject,
                build_session_id=build_session_id,
                workflow=workflow_name,
                extra_metadata={"context_metadata": dict(context.metadata)},
            ):
                with langsmith_trace(
                    name=workflow_name,
                    run_type="chain",
                    inputs=_workflow_inputs(initial_state),
                    subject=context.subject,
                    build_session_id=build_session_id,
                    workflow=workflow_name,
                    node=workflow_name,
                    extra_metadata={"context_metadata": dict(context.metadata)},
                ) as run:
                    graph = graph_builder()
                    compiled = graph.compile()
                    final_state = await compiled.ainvoke(initial_state)
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        workflow_logger.info("workflow_completed", workflow_name=workflow_name, elapsed_ms=elapsed_ms)
        if isinstance(final_state, dict):
            final_state.setdefault("workflow_elapsed_ms", elapsed_ms)
        if run is not None:
            run.end(outputs=_workflow_outputs(final_state, elapsed_ms=elapsed_ms))
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


def _workflow_inputs(initial_state: Any) -> dict[str, Any]:
    if not isinstance(initial_state, dict):
        return {}
    inputs: dict[str, Any] = {}
    for field_name in (
        "subject",
        "build_session_id",
        "planner_session_id",
        "confirmed_plan_id",
        "digest_mode",
        "course_type",
        "retrieval_profile",
        "teaching_action",
    ):
        value = initial_state.get(field_name)
        if value not in (None, "", [], {}):
            inputs[field_name] = value
    for field_name, alias in (
        ("file_ids", "file_count"),
        ("chunk_ids", "chunk_count"),
        ("message_history", "message_count"),
    ):
        value = initial_state.get(field_name)
        if isinstance(value, list) and value:
            inputs[alias] = len(value)
    return inputs


def _workflow_outputs(final_state: Any, *, elapsed_ms: int | None = None) -> dict[str, Any]:
    if not isinstance(final_state, dict):
        return {"status": "ok", "elapsed_ms": int(elapsed_ms or 0)}

    outputs: dict[str, Any] = {
        "status": "failed" if final_state.get("error") else "ok",
        "elapsed_ms": int(elapsed_ms or final_state.get("workflow_elapsed_ms", 0) or 0),
    }
    for field_name in ("fallback_used", "planner_generation_mode", "generation_mode"):
        value = final_state.get(field_name)
        if value not in (None, "", [], {}):
            outputs[field_name] = value
    runtime_steps = final_state.get("runtime_steps")
    if isinstance(runtime_steps, list) and runtime_steps:
        outputs["step_count"] = len(runtime_steps)
    return outputs
