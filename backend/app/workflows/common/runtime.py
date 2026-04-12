"""LangGraph 运行时薄封装。"""

from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Any

from app.shared.infra.tracing import annotate_traceable, build_langsmith_extra, llm_trace_scope
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
    traced_invoke = annotate_traceable(
        _invoke_compiled_graph,
        name=workflow_name,
        run_type="chain",
        process_inputs=lambda inputs: _workflow_inputs(inputs.get("initial_state")),
        process_outputs=_workflow_outputs,
    )
    return await traced_invoke(
        initial_state=initial_state,
        graph_builder=graph_builder,
        subject=subject,
        build_session_id=build_session_id,
        workflow_name=workflow_name,
        lane=lane,
        langsmith_extra=build_langsmith_extra(
            subject=subject,
            build_session_id=build_session_id,
            workflow=workflow_name,
            lane=lane,
            node=workflow_name,
            extra_metadata=extra_metadata,
        ),
    )


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
        traced_invoke = annotate_traceable(
            _invoke_compiled_graph,
            name=workflow_name,
            run_type="chain",
            process_inputs=lambda inputs: _workflow_inputs(inputs.get("initial_state")),
            process_outputs=_workflow_outputs,
        )
        final_state = await traced_invoke(
            initial_state=initial_state,
            graph_builder=graph_builder,
            subject=context.subject,
            build_session_id=build_session_id,
            workflow_name=workflow_name,
            lane=str(context.metadata.get("lane", "") or ""),
            langsmith_extra=build_langsmith_extra(
                subject=context.subject,
                build_session_id=build_session_id,
                workflow=workflow_name,
                lane=str(context.metadata.get("lane", "") or ""),
                node=workflow_name,
                extra_metadata={"context_metadata": dict(context.metadata)},
            ),
        )
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


async def _invoke_compiled_graph(
    *,
    initial_state: Any,
    graph_builder,
    subject: str,
    build_session_id: str,
    workflow_name: str,
    lane: str = "",
    langsmith_extra: dict[str, Any] | None = None,
) -> Any:
    del langsmith_extra
    with llm_trace_scope(
        subject=subject,
        build_session_id=build_session_id,
        workflow=workflow_name,
        lane=lane,
    ):
        graph = graph_builder()
        compiled = graph.compile()
        return await compiled.ainvoke(initial_state)


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
