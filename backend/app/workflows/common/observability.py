"""Thin workflow node tracing helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from time import perf_counter
from typing import Any

import structlog

from app.shared.infra.tracing import langsmith_trace, llm_trace_scope

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
    "asset_kind",
    "tone",
    "session_id",
    "job_id",
    "user_id",
    "file_id",
    "exam_paper_id",
    "chapter_index",
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
    "document_count",
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
    "job_id",
    "user_id",
    "file_id",
    "exam_paper_id",
)

_COUNT_FIELDS = {
    "file_ids": "file_count",
    "chapter_assignments": "chapter_count",
    "chapter_materials": "chapter_material_count",
    "chapter_drafts": "chapter_draft_count",
    "chapter_metadatas": "staged_chapter_count",
    "doc_ids": "doc_count",
    "review_tasks": "review_task_count",
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
    """Wrap one LangGraph node with a thin LangSmith span."""

    trace_name = f"{lane}.{name}" if lane else name

    async def wrapped(state: Any) -> dict[str, Any]:
        state_mapping = state if isinstance(state, Mapping) else {}
        subject = str(state_mapping.get("subject", "") or "")
        build_session_id = _resolve_build_session_id(state_mapping)
        metadata = _node_trace_metadata(state_mapping)
        started_at = perf_counter()
        run = None

        try:
            with langsmith_trace(
                name=trace_name,
                run_type="chain",
                inputs=_node_trace_inputs(state_mapping, input_keys=input_keys),
                subject=subject,
                build_session_id=build_session_id,
                workflow=workflow,
                lane=lane,
                node=trace_name,
                extra_metadata=metadata,
                extra_tags=_node_trace_tags(metadata, lane=lane, node=name),
            ) as run:
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
            if run is not None:
                run.end(
                    outputs=_node_trace_outputs(
                        result_mapping,
                        elapsed_ms=elapsed_ms,
                        output_keys=output_keys,
                    )
                )
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
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            if run is not None:
                run.end(outputs={"status": "failed", "elapsed_ms": elapsed_ms, "error": str(exc)})
            logger.bind(
                workflow=workflow,
                lane=lane,
                node=name,
                subject=subject,
                build_session_id=build_session_id,
            ).exception("workflow_node_failed", elapsed_ms=elapsed_ms)
            raise

    return wrapped


def traced_workflow_node(
    *,
    workflow: str,
    lane: str,
    name: str,
    input_keys: Sequence[str] | None = None,
    output_keys: Sequence[str] | None = None,
    timing_field: str | None = None,
) -> Callable[[Callable[[Any], Any]], Callable[[Any], Awaitable[dict[str, Any]]]]:
    """Decorator form of ``trace_workflow_node`` for LangGraph node handlers."""

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


def wrap_workflow_node(
    handler: Callable[[Any], Any],
    *,
    workflow_name: str,
    lane: str,
    node_name: str,
    input_keys: Sequence[str] | None = None,
    output_keys: Sequence[str] | None = None,
    timing_field: str | None = None,
) -> Callable[[Any], Awaitable[dict[str, Any]]]:
    """Backward-compatible alias for the thin workflow node tracer."""

    return trace_workflow_node(
        handler,
        workflow=workflow_name,
        lane=lane,
        name=node_name,
        input_keys=input_keys,
        output_keys=output_keys,
        timing_field=timing_field,
    )


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
    keys = tuple(input_keys or _DEFAULT_INPUT_KEYS)
    inputs = _pick_fields(state, keys)
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
    elapsed_ms: int,
    output_keys: Sequence[str] | None,
) -> dict[str, Any]:
    outputs = {
        "status": "failed" if result.get("error") else "ok",
        "elapsed_ms": int(elapsed_ms),
    }
    outputs.update(_pick_fields(result, tuple(output_keys or _DEFAULT_OUTPUT_KEYS)))

    for field_name, alias in _COUNT_FIELDS.items():
        value = result.get(field_name)
        if isinstance(value, list) and value:
            outputs[alias] = len(value)

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
    metadata: Mapping[str, Any],
    *,
    lane: str,
    node: str,
) -> list[str]:
    tags: list[str] = []
    if lane:
        tags.append(f"lane:{lane}")
    if node:
        tags.append(f"node:{node}")
    digest_mode = str(metadata.get("digest_mode", "") or "")
    course_type = str(metadata.get("course_type", "") or "")
    retrieval_profile = str(metadata.get("retrieval_profile", "") or "")
    teaching_action = str(metadata.get("teaching_action", "") or "")
    asset_kind = str(metadata.get("asset_kind", "") or "")
    chapter_index = metadata.get("chapter_index")
    if digest_mode:
        tags.append(f"mode:{digest_mode}")
    if course_type:
        tags.append(f"course:{course_type}")
    if retrieval_profile:
        tags.append(f"retrieval:{retrieval_profile}")
    if teaching_action:
        tags.append(f"teaching:{teaching_action}")
    if asset_kind:
        tags.append(f"asset:{asset_kind}")
    if chapter_index is not None:
        tags.append(f"chapter:{chapter_index}")
    return tags


def _extract_chapter_index(state: Mapping[str, Any]) -> int | None:
    value = state.get("chapter_index")
    if value not in (None, ""):
        return int(value)
    for key in ("chapter_assignment", "chapter_material"):
        payload = state.get(key) or {}
        if isinstance(payload, Mapping):
            nested = payload.get("chapter_index")
            if nested not in (None, ""):
                return int(nested)
    return None


__all__ = [
    "traced_workflow_node",
    "trace_workflow_node",
    "wrap_workflow_node",
]
