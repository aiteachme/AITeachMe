"""Small workflow-facing LangSmith helpers.

Preferred public API:

- ``@traceable_run(...)`` for traced workflow functions
- ``wrap_traceable_run(...)`` for graph-builder style wiring
- ``tracked_step(...)`` for important substeps
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from time import perf_counter
from typing import Any

import structlog

from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.shared.infra.tracing import (
    LangSmithRunType,
    annotate_traceable,
    build_langsmith_extra,
    llm_trace_scope,
    normalize_langsmith_run_type,
)

logger = structlog.get_logger(__name__)

_DEFAULT_INPUT_KEYS = (
    "subject",
    "build_session_id",
    "planner_session_id",
    "confirmed_plan_id",
    "digest_mode",
    "course_type",
    "retrieval_profile",
    "teaching_action",
    "chapter_index",
    "file_id",
    "session_id",
    "user_id",
)

_DEFAULT_OUTPUT_KEYS = (
    "fallback_used",
    "planner_generation_mode",
    "generation_mode",
    "source_count",
    "query_count",
    "local_hits",
    "web_hits",
    "word_count",
    "coverage_score",
    "quality_score",
    "asset_count",
    "chapter_index",
)

_TRACE_METADATA_FIELDS = (
    "planner_session_id",
    "confirmed_plan_id",
    "digest_mode",
    "course_type",
    "retrieval_profile",
    "teaching_action",
    "asset_kind",
    "session_id",
    "user_id",
    "file_id",
)

_COUNT_FIELDS = {
    "file_ids": "file_count",
    "unit_ids": "unit_count",
    "chapter_assignments": "chapter_count",
    "chapter_materials": "chapter_material_count",
    "chapter_drafts": "chapter_draft_count",
    "chapter_metadatas": "chapter_metadata_count",
    "doc_ids": "doc_count",
    "review_tasks": "review_task_count",
    "review_task_ids": "review_task_count",
    "weaknesses": "weakness_count",
    "warnings": "warning_count",
    "runtime_steps": "step_count",
}


def trace_workflow_node(
    handler: Callable[[Any], Any],
    *,
    workflow: str,
    lane: str,
    name: str,
    input_keys: Sequence[str] | None = None,
    output_keys: Sequence[str] | None = None,
    timing_field: str | None = None,
) -> Callable[[Any], Awaitable[dict[str, Any]]]:
    """Wrap one LangGraph node with a thin ``@traceable``-style adapter."""

    trace_name = f"{lane}.{name}" if lane else name

    async def invoke_node(
        *,
        state: Any,
        langsmith_extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del langsmith_extra
        state_mapping = state if isinstance(state, Mapping) else {}
        subject = str(state_mapping.get("subject", "") or "")
        build_session_id = _resolve_build_session_id(state_mapping)
        started_at = perf_counter()

        try:
            with llm_trace_scope(
                subject=subject,
                build_session_id=build_session_id,
                workflow=workflow,
                lane=lane,
                node=trace_name,
            ):
                result = handler(state)
                if inspect.isawaitable(result):
                    result = await result

            result_mapping = _coerce_result_mapping(result)
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            if timing_field and timing_field not in result_mapping:
                result_mapping = {**result_mapping, timing_field: elapsed_ms}

            logger.bind(
                workflow=workflow,
                lane=lane,
                node=name,
                subject=subject,
                build_session_id=build_session_id,
            ).info(
                "workflow_node_completed",
                elapsed_ms=elapsed_ms,
                status="failed" if result_mapping.get("error") else "ok",
            )
            return result_mapping
        except Exception:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            logger.bind(
                workflow=workflow,
                lane=lane,
                node=name,
                subject=subject,
                build_session_id=build_session_id,
            ).exception("workflow_node_failed", elapsed_ms=elapsed_ms)
            raise

    traced_invoke = annotate_traceable(
        invoke_node,
        name=trace_name,
        run_type="chain",
        process_inputs=lambda inputs: _node_trace_inputs(
            _extract_traced_state(inputs),
            input_keys=input_keys,
        ),
        process_outputs=lambda outputs: _node_trace_outputs(
            _coerce_result_mapping(outputs),
            output_keys=output_keys,
        ),
    )

    async def wrapped(state: Any) -> dict[str, Any]:
        state_mapping = state if isinstance(state, Mapping) else {}
        trace_extra = build_langsmith_extra(
            subject=str(state_mapping.get("subject", "") or ""),
            build_session_id=_resolve_build_session_id(state_mapping),
            workflow=workflow,
            lane=lane,
            node=trace_name,
            extra_metadata=_node_trace_metadata(state_mapping),
            extra_tags=_node_trace_tags(state_mapping, lane=lane, node=name),
        )
        return await traced_invoke(state=state, langsmith_extra=trace_extra)

    return wrapped


def node(
    *,
    workflow: str,
    lane: str,
    name: str,
    input_keys: Sequence[str] | None = None,
    output_keys: Sequence[str] | None = None,
    timing_field: str | None = None,
) -> Callable[[Callable[[Any], Any]], Callable[[Any], Awaitable[dict[str, Any]]]]:
    """Short semantic alias for one traced LangGraph node."""

    return traceable_run(
        name=name,
        run_type="chain",
        workflow=workflow,
        lane=lane,
        input_keys=input_keys,
        output_keys=output_keys,
        timing_field=timing_field,
    )


def traced_workflow_node(
    *,
    workflow: str,
    lane: str,
    name: str,
    input_keys: Sequence[str] | None = None,
    output_keys: Sequence[str] | None = None,
    timing_field: str | None = None,
) -> Callable[[Callable[[Any], Any]], Callable[[Any], Awaitable[dict[str, Any]]]]:
    """Decorator form of :func:`trace_workflow_node`."""

    def decorator(handler: Callable[[Any], Any]) -> Callable[[Any], Awaitable[dict[str, Any]]]:
        return trace_workflow_node(
            handler,
            workflow=workflow,
            lane=lane,
            name=name,
            input_keys=input_keys,
            output_keys=output_keys,
            timing_field=timing_field,
        )

    return decorator


def workflow_node(
    *,
    workflow: str,
    lane: str,
    name: str,
    input_keys: Sequence[str] | None = None,
    output_keys: Sequence[str] | None = None,
    timing_field: str | None = None,
) -> Callable[[Callable[[Any], Any]], Callable[[Any], Awaitable[dict[str, Any]]]]:
    """Explicit alias for ``@node(...)`` when the longer name reads better."""

    return node(
        workflow=workflow,
        lane=lane,
        name=name,
        input_keys=input_keys,
        output_keys=output_keys,
        timing_field=timing_field,
    )


def wrap_node(
    handler: Callable[[Any], Any],
    *,
    workflow: str,
    lane: str,
    name: str,
    input_keys: Sequence[str] | None = None,
    output_keys: Sequence[str] | None = None,
    timing_field: str | None = None,
) -> Callable[[Any], Awaitable[dict[str, Any]]]:
    """Short semantic alias for graph-builder style node registration."""

    return wrap_traceable_run(
        handler,
        name=name,
        run_type="chain",
        workflow=workflow,
        lane=lane,
        input_keys=input_keys,
        output_keys=output_keys,
        timing_field=timing_field,
    )


def traceable_run(
    *,
    name: str,
    run_type: LangSmithRunType = "chain",
    workflow: str = "",
    lane: str = "",
    input_keys: Sequence[str] | None = None,
    output_keys: Sequence[str] | None = None,
    timing_field: str | None = None,
    process_inputs=None,
    process_outputs=None,
) -> Callable[[Callable[[Any], Any]], Callable[..., Any]]:
    """One unified decorator for node, prompt, tool, retriever, parser runs.

    - ``run_type="chain"`` + ``workflow=...`` uses the stateful workflow-node wrapper
    - other run types map to a thin repo-local ``@traceable`` wrapper
    """

    resolved_run_type = normalize_langsmith_run_type(run_type, default="chain")
    if resolved_run_type == "chain" and workflow:
        return traced_workflow_node(
            workflow=workflow,
            lane=lane,
            name=name,
            input_keys=input_keys,
            output_keys=output_keys,
            timing_field=timing_field,
        )

    def decorator(handler: Callable[[Any], Any]):
        return annotate_traceable(
            handler,
            name=name,
            run_type=resolved_run_type,
            process_inputs=process_inputs,
            process_outputs=process_outputs,
        )

    return decorator


def wrap_traceable_run(
    handler: Callable[[Any], Any],
    *,
    name: str,
    run_type: LangSmithRunType = "chain",
    workflow: str = "",
    lane: str = "",
    input_keys: Sequence[str] | None = None,
    output_keys: Sequence[str] | None = None,
    timing_field: str | None = None,
    process_inputs=None,
    process_outputs=None,
) -> Callable[..., Any]:
    """One unified wrapper for graph-builder style traced functions."""

    resolved_run_type = normalize_langsmith_run_type(run_type, default="chain")
    if resolved_run_type == "chain" and workflow:
        return trace_workflow_node(
            handler,
            workflow=workflow,
            lane=lane,
            name=name,
            input_keys=input_keys,
            output_keys=output_keys,
            timing_field=timing_field,
        )
    return annotate_traceable(
        handler,
        name=name,
        run_type=resolved_run_type,
        process_inputs=process_inputs,
        process_outputs=process_outputs,
    )


def wrap_workflow_node(
    handler: Callable[[Any], Any],
    *,
    workflow_name: str | None = None,
    node_name: str | None = None,
    workflow: str | None = None,
    name: str | None = None,
    lane: str,
    input_keys: Sequence[str] | None = None,
    output_keys: Sequence[str] | None = None,
    timing_field: str | None = None,
) -> Callable[[Any], Awaitable[dict[str, Any]]]:
    """Explicit compatibility alias for graph wiring.

    New code can prefer ``wrap_node(...)`` for the shortest common workflow API.
    """

    resolved_workflow = str(workflow or workflow_name or "").strip()
    resolved_name = str(name or node_name or "").strip()
    if not resolved_workflow:
        raise ValueError("wrap_workflow_node requires `workflow` or `workflow_name`.")
    if not resolved_name:
        raise ValueError("wrap_workflow_node requires `name` or `node_name`.")

    return wrap_node(
        handler,
        workflow=resolved_workflow,
        lane=lane,
        name=resolved_name,
        input_keys=input_keys,
        output_keys=output_keys,
        timing_field=timing_field,
    )


def _extract_traced_state(inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    state = inputs.get("state")
    return state if isinstance(state, Mapping) else {}


def _resolve_build_session_id(state: Mapping[str, Any]) -> str:
    for field_name in ("build_session_id", "job_id", "session_id", "planner_session_id"):
        value = state.get(field_name)
        if value not in (None, ""):
            return str(value)
    return ""


def _coerce_result_mapping(result: Any) -> dict[str, Any]:
    if isinstance(result, Mapping):
        return dict(result)
    return {"result": result}


def _node_trace_metadata(state: Mapping[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for field_name in _TRACE_METADATA_FIELDS:
        value = state.get(field_name)
        if value not in (None, "", [], {}):
            metadata[field_name] = value
    chapter_index = _extract_chapter_index(state)
    if chapter_index is not None:
        metadata["chapter_index"] = chapter_index
    return metadata


def _node_trace_inputs(
    state: Mapping[str, Any],
    *,
    input_keys: Sequence[str] | None,
) -> dict[str, Any]:
    inputs = _pick_fields(state, tuple(input_keys or _DEFAULT_INPUT_KEYS))
    for field_name, alias in _COUNT_FIELDS.items():
        value = state.get(field_name)
        if isinstance(value, list) and value:
            inputs[alias] = len(value)
    chapter_index = _extract_chapter_index(state)
    if chapter_index is not None:
        inputs.setdefault("chapter_index", chapter_index)
    return inputs


def _node_trace_outputs(
    result: Mapping[str, Any],
    *,
    output_keys: Sequence[str] | None,
) -> dict[str, Any]:
    outputs = {
        "status": "failed" if result.get("error") else "ok",
    }
    outputs.update(_pick_fields(result, tuple(output_keys or _DEFAULT_OUTPUT_KEYS)))

    for field_name, alias in _COUNT_FIELDS.items():
        value = result.get(field_name)
        if isinstance(value, list) and value:
            outputs[alias] = len(value)

    merged_markdown = str(
        result.get("enriched_markdown")
        or result.get("merged_markdown")
        or result.get("enhanced_markdown")
        or ""
    )
    if merged_markdown.strip() and "final_word_count" not in outputs:
        outputs["final_word_count"] = count_words(merged_markdown)

    if result.get("error"):
        outputs["error"] = str(result.get("error"))
    return outputs


def _pick_fields(payload: Mapping[str, Any], keys: Sequence[str]) -> dict[str, Any]:
    picked: dict[str, Any] = {}
    for field_name in keys:
        value = payload.get(field_name)
        if value not in (None, "", [], {}):
            picked[str(field_name)] = value
    return picked


def _node_trace_tags(
    state: Mapping[str, Any],
    *,
    lane: str,
    node: str,
) -> list[str]:
    tags: list[str] = []
    if lane:
        tags.append(f"lane:{lane}")
    if node:
        tags.append(f"node:{node}")
    for key, prefix in (
        ("digest_mode", "mode"),
        ("course_type", "course"),
        ("retrieval_profile", "retrieval"),
        ("teaching_action", "teaching"),
        ("asset_kind", "asset"),
    ):
        value = str(state.get(key, "") or "").strip()
        if value:
            tags.append(f"{prefix}:{value}")
    chapter_index = _extract_chapter_index(state)
    if chapter_index is not None:
        tags.append(f"chapter:{chapter_index}")
    return tags


def _extract_chapter_index(state: Mapping[str, Any]) -> int | None:
    value = state.get("chapter_index")
    if value not in (None, ""):
        return int(value)
    for key in ("chapter_assignment", "chapter_material", "chapter_plan"):
        payload = state.get(key) or {}
        if isinstance(payload, Mapping):
            nested = payload.get("chapter_index")
            if nested not in (None, ""):
                return int(nested)
    return None


__all__ = [
    "traceable_run",
    "wrap_traceable_run",
    "node",
    "trace_workflow_node",
    "traced_workflow_node",
    "workflow_node",
    "wrap_node",
    "wrap_workflow_node",
]
