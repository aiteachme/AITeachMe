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
    llm_trace_scope,
)
from app.shared.infra.workflow.context import WorkflowContext

logger = structlog.get_logger(__name__)


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
        tag_node_name = f"{lane}.{name}" if lane else name
        node_extra_metadata = {
            "node_display_name": name,
            "node_description": description,
            "state_inputs": list(input_keys or []),
            "state_outputs": list(output_keys or []),
            **dict(metadata or {}),
        }

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
                node=name,
                extra_metadata=node_extra_metadata,
            )
            node_tags = build_langsmith_tags(
                workflow=workflow_name,
                lane=lane,
                node=tag_node_name,
            )

            with tracing_context(
                metadata=node_metadata,
                tags=node_tags,
            ):
                with llm_trace_scope(
                    course_id=course_id,
                    build_session_id=build_session_id,
                    workflow=workflow_name,
                    lane=lane,
                    node=name,
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
                            node=name,
                            course_id=course_id,
                            build_session_id=build_session_id,
                        ).exception("workflow_node_failed", elapsed_ms=elapsed_ms)
                        raise

            elapsed_ms = int((perf_counter() - started_at) * 1000)
            result_mapping = result if isinstance(result, dict) else {}
            if timing_field and timing_field not in result_mapping:
                result_mapping = {**result_mapping, timing_field: elapsed_ms}

            logger.bind(
                workflow=workflow_name,
                lane=lane,
                node=name,
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
