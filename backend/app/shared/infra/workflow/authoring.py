"""Workflow authoring helpers.

This module is the workflow-facing adapter layer on top of
``app.shared.infra.observability``. It does not implement a second tracing
system; it only wires LangGraph node authoring to the shared observability
primitives.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any

import structlog
from langsmith import tracing_context

from app.shared.infra.observability.trace import (
    build_langsmith_metadata,
    build_langsmith_tags,
    langsmith_trace,
    llm_trace_scope,
    sanitize_langsmith_input,
    sanitize_langsmith_output,
)
from app.shared.infra.workflow.context import WorkflowContext

logger = structlog.get_logger(__name__)


def _state_value_summary(value: Any) -> Any:
    if isinstance(value, str):
        return {"type": "str", "chars": len(value)}
    if isinstance(value, Mapping):
        return {"type": "dict", "key_count": len(value)}
    if isinstance(value, (list, tuple, set)):
        return {"type": "list", "count": len(value)}
    return value


def _node_trace_inputs(
    state: Mapping[str, Any],
    *,
    input_keys: Sequence[str],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "available_input_keys": [key for key in input_keys if key in state],
        "state_key_count": len(state),
    }
    for key in ("course_id", "course_name", "build_session_id", "planner_session_id", "digest_mode"):
        value = state.get(key)
        if value not in (None, "", [], {}):
            payload[key] = value
    for key in input_keys:
        if key in payload or key not in state:
            continue
        payload[f"{key}_summary"] = _state_value_summary(state[key])
    return sanitize_langsmith_input(payload, field_name="workflow_node_inputs")


def _node_trace_outputs(
    result: Mapping[str, Any],
    *,
    output_keys: Sequence[str],
    elapsed_ms: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "elapsed_ms": elapsed_ms,
        "status": "failed" if result.get("error") else "ok",
        "available_output_keys": [key for key in output_keys if key in result],
    }
    error = result.get("error")
    if error:
        payload["error"] = str(error)
    for key in ("llm_calls_total", "llm_calls_skipped"):
        value = result.get(key)
        if value not in (None, ""):
            payload[key] = value
    for key in output_keys:
        if key in payload or key not in result:
            continue
        payload[f"{key}_summary"] = _state_value_summary(result[key])
    return sanitize_langsmith_output(payload, field_name="workflow_node_outputs")


def _resolve_workflow_name(
    *,
    workflow: str | None = None,
    workflow_name: str | None = None,
    context: WorkflowContext | None = None,
) -> str:
    resolved = str(workflow or workflow_name or "").strip()
    if resolved:
        return resolved
    if context is not None:
        return str(context.workflow_name or "").strip()
    return ""


def _resolve_build_session_id(state: Mapping[str, Any]) -> str:
    for field_name in ("build_session_id", "job_id", "session_id", "planner_session_id"):
        value = state.get(field_name)
        if value not in (None, ""):
            return str(value)
    return ""


@dataclass(frozen=True, slots=True)
class WorkflowTraceBinding:
    """Bind workflow metadata once and reuse it across node wiring."""

    workflow: str
    lane: str = ""

    def node(
        self,
        handler: Any,
        *,
        name: str,
        display_name: str | None = None,
        description: str | None = None,
        timing_field: str | None = None,
        input_keys: Sequence[str] | None = None,
        output_keys: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ):
        """Wrap one workflow node without creating duplicate LangSmith spans."""

        if handler is None:
            raise TypeError("workflow_tracer().node(...) requires a handler argument.")
        workflow_name = self.workflow
        lane = self.lane
        node_name = str(name or "").strip()
        if not node_name:
            raise ValueError("workflow_tracer().node(...) requires a non-empty `name`.")
        trace_metadata = dict(metadata or {})
        resolved_display_name = str(
            display_name or trace_metadata.get("node_display_name") or node_name
        )
        resolved_description = str(description or trace_metadata.get("node_description") or "")
        tag_node_name = f"{lane}.{node_name}" if lane else node_name
        node_extra_metadata = {
            "node_key": trace_metadata.get("node_key") or node_name,
            "node_display_name": resolved_display_name,
            "node_description": resolved_description,
            "state_inputs": list(input_keys or []),
            "state_outputs": list(output_keys or []),
            **trace_metadata,
        }
        compact_input_keys = tuple(input_keys or [])
        compact_output_keys = tuple(output_keys or [])

        @functools.wraps(handler)
        async def wrapper(state):
            state_mapping = state if isinstance(state, Mapping) else {}
            course_id = str(state_mapping.get("course_id", "") or "")
            build_session_id = _resolve_build_session_id(state_mapping)
            started_at = perf_counter()
            node_metadata = build_langsmith_metadata(
                course_id=course_id,
                build_session_id=build_session_id,
                workflow=workflow_name,
                lane=lane,
                node=node_name,
                extra_metadata=node_extra_metadata,
            )
            node_tags = build_langsmith_tags(
                workflow=workflow_name,
                lane=lane,
                node=tag_node_name,
            )

            with langsmith_trace(
                name=resolved_display_name,
                run_type="chain",
                inputs=_node_trace_inputs(state_mapping, input_keys=compact_input_keys),
                course_id=course_id,
                build_session_id=build_session_id,
                workflow=workflow_name,
                lane=lane,
                node=node_name,
                extra_metadata=node_extra_metadata,
                extra_tags=[f"node:{tag_node_name}"],
            ) as trace_run:
                with tracing_context(
                    metadata=node_metadata,
                    tags=node_tags,
                ):
                    with llm_trace_scope(
                        course_id=course_id,
                        build_session_id=build_session_id,
                        workflow=workflow_name,
                        lane=lane,
                        node=node_name,
                    ):
                        try:
                            result = handler(state)
                            if inspect.isawaitable(result):
                                result = await result
                        except Exception:
                            elapsed_ms = int((perf_counter() - started_at) * 1000)
                            logger.bind(
                                workflow=workflow_name,
                                lane=lane,
                                node=node_name,
                                course_id=course_id,
                                build_session_id=build_session_id,
                            ).exception("workflow_node_failed", elapsed_ms=elapsed_ms)
                            raise
                    elapsed_ms = int((perf_counter() - started_at) * 1000)
                    result_mapping = result if isinstance(result, dict) else {}
                    if timing_field and timing_field not in result_mapping:
                        result_mapping = {**result_mapping, timing_field: elapsed_ms}
                    if trace_run is not None:
                        trace_run.end(
                            outputs=_node_trace_outputs(
                                result_mapping,
                                output_keys=compact_output_keys,
                                elapsed_ms=elapsed_ms,
                            )
                        )

                    logger.bind(
                        workflow=workflow_name,
                        lane=lane,
                        node=node_name,
                        course_id=course_id,
                        build_session_id=build_session_id,
                    ).info(
                        "workflow_node_completed",
                        elapsed_ms=elapsed_ms,
                        status="failed" if result_mapping.get("error") else "ok",
                    )
                    return result_mapping if timing_field else result

        return wrapper


def workflow_tracer(
    *,
    workflow: str | None = None,
    workflow_name: str | None = None,
    context: WorkflowContext | None = None,
    lane: str = "",
) -> WorkflowTraceBinding:
    """Create one reusable workflow trace binding."""

    resolved_workflow = _resolve_workflow_name(
        workflow=workflow,
        workflow_name=workflow_name,
        context=context,
    )
    if not resolved_workflow:
        raise ValueError("workflow_tracer requires `workflow`, `workflow_name`, or `context`.")
    return WorkflowTraceBinding(workflow=resolved_workflow, lane=str(lane or ""))


__all__ = [
    "WorkflowTraceBinding",
    "workflow_tracer",
]
