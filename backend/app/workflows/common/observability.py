"""Workflow-facing LangSmith helpers — simplified.

LangGraph auto-traces each node when ``LANGSMITH_TRACING=true``.
This module only provides thin wrappers that:

1. Enrich the ambient ``tracing_context`` with workflow metadata
2. Set ``llm_trace_scope`` so infra-layer LLM calls inherit context
3. Optionally inject a ``timing_field`` into the node result

Preferred public API:

- ``workflow_tracer(...).node(...)`` for workflow node wiring
- ``@traceable_run(...)`` for traced prompt/helper functions
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

from app.shared.infra.tracing import (
    LangSmithRunType,
    llm_trace_scope,
    normalize_langsmith_run_type,
    traceable_with_context,
)
from app.workflows.common.context import WorkflowContext

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Resolve helpers
# ---------------------------------------------------------------------------

def _resolve_workflow_name(
    *,
    workflow: str | None = None,
    workflow_name: str | None = None,
    context: WorkflowContext | None = None,
) -> str:
    resolved_workflow = str(workflow or workflow_name or "").strip()
    if resolved_workflow:
        return resolved_workflow
    if context is not None:
        return str(context.workflow_name or "").strip()
    return ""


def _resolve_build_session_id(state: Mapping[str, Any]) -> str:
    for field_name in ("build_session_id", "job_id", "session_id", "planner_session_id"):
        value = state.get(field_name)
        if value not in (None, ""):
            return str(value)
    return ""


# ---------------------------------------------------------------------------
# WorkflowTraceBinding — the main node-wrapping API
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class WorkflowTraceBinding:
    """Bind workflow/lane metadata once and reuse it across a graph."""

    workflow: str
    lane: str = ""

    def node(
        self,
        handler: Any | None = None,
        *,
        name: str,
        timing_field: str | None = None,
        # Kept in signature for backward compat — no longer used.
        input_keys: Sequence[str] | None = None,
        output_keys: Sequence[str] | None = None,
    ):
        """Wrap or decorate one workflow node.

        LangGraph handles the LangSmith node span automatically.
        This wrapper only:
        1. Enriches ``tracing_context`` with workflow metadata
        2. Sets ``llm_trace_scope`` for infra-layer ambient context
        3. Injects an optional ``timing_field`` into the result
        """

        wf = self.workflow
        lane = self.lane
        tag_node_name = f"{lane}.{name}" if lane else name

        def decorator(fn):
            @functools.wraps(fn)
            async def wrapper(state):
                state_mapping = state if isinstance(state, Mapping) else {}
                subject = str(state_mapping.get("subject", "") or "")
                build_session_id = _resolve_build_session_id(state_mapping)
                started_at = perf_counter()

                # Enrich LangGraph's auto-created node span and
                # set ambient context for nested infra LLM calls.
                node_tags = [f"workflow:{wf}", f"node:{tag_node_name}"]
                if lane:
                    node_tags.append(f"lane:{lane}")
                with tracing_context(
                    metadata={
                        "workflow": wf,
                        "lane": lane,
                        "node": name,
                        "subject": subject,
                        "build_session_id": build_session_id,
                    },
                    tags=node_tags,
                ):
                    with llm_trace_scope(
                        subject=subject,
                        build_session_id=build_session_id,
                        workflow=wf,
                        lane=lane,
                        node=name,
                    ):
                        try:
                            result = fn(state)
                            if inspect.isawaitable(result):
                                result = await result
                        except Exception:
                            elapsed_ms = int((perf_counter() - started_at) * 1000)
                            logger.bind(
                                workflow=wf, lane=lane, node=name,
                                subject=subject, build_session_id=build_session_id,
                            ).exception("workflow_node_failed", elapsed_ms=elapsed_ms)
                            raise

                elapsed_ms = int((perf_counter() - started_at) * 1000)

                # Inject timing field if requested.
                result_mapping = result if isinstance(result, dict) else {}
                if timing_field and timing_field not in result_mapping:
                    result_mapping = {**result_mapping, timing_field: elapsed_ms}

                logger.bind(
                    workflow=wf, lane=lane, node=name,
                    subject=subject, build_session_id=build_session_id,
                ).info(
                    "workflow_node_completed",
                    elapsed_ms=elapsed_ms,
                    status="failed" if result_mapping.get("error") else "ok",
                )
                return result_mapping if timing_field else result

            return wrapper

        if handler is not None:
            return decorator(handler)
        return decorator


def workflow_tracer(
    *,
    workflow: str | None = None,
    workflow_name: str | None = None,
    context: WorkflowContext | None = None,
    lane: str = "",
) -> WorkflowTraceBinding:
    """Create one reusable binding for a workflow graph or node module."""

    resolved_workflow = _resolve_workflow_name(
        workflow=workflow,
        workflow_name=workflow_name,
        context=context,
    )
    if not resolved_workflow:
        raise ValueError("workflow_tracer requires `workflow`, `workflow_name`, or `context`.")
    return WorkflowTraceBinding(workflow=resolved_workflow, lane=str(lane or ""))


# ---------------------------------------------------------------------------
# traceable_run — repo-local @traceable wrapper
# ---------------------------------------------------------------------------

def traceable_run(
    *,
    name: str,
    run_type: LangSmithRunType = "chain",
    # Kept in signature for backward compat — ignored.
    workflow: str = "",
    workflow_name: str | None = None,
    context: WorkflowContext | None = None,
    lane: str = "",
    input_keys: Sequence[str] | None = None,
    output_keys: Sequence[str] | None = None,
    timing_field: str | None = None,
    process_inputs=None,
    process_outputs=None,
):
    """Decorator for traced prompt/helper/retriever functions.

    This is the workflow-facing wrapper around ``langsmith.traceable``.
    Usage is identical to the reference example::

        @traceable_run(name="digest.planner.build_prompt", run_type="prompt")
        def build_prompt(...):
            ...
    """

    resolved_run_type = normalize_langsmith_run_type(run_type, default="chain")
    return traceable_with_context(
        name=name,
        run_type=resolved_run_type,
        process_inputs=process_inputs,
        process_outputs=process_outputs,
    )


__all__ = [
    "WorkflowTraceBinding",
    "workflow_tracer",
    "traceable_run",
]
