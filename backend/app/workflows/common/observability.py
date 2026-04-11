"""Lightweight workflow node observability helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from time import perf_counter
from typing import Any

import structlog

from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.shared.infra.tracing import langsmith_trace, llm_trace_scope

logger = structlog.get_logger(__name__)

_TRACE_INPUT_FIELDS = (
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
    "unit_ids": "unit_count",
    "chapter_assignments": "chapter_count",
    "chapter_materials": "chapter_material_count",
    "chapter_drafts": "chapter_draft_count",
    "chapter_metadatas": "staged_chapter_count",
    "doc_ids": "doc_count",
    "created_template_ids": "created_template_count",
    "review_tasks": "review_task_count",
    "review_task_ids": "review_task_count",
    "updated_state_ids": "updated_state_count",
    "weaknesses": "weakness_count",
    "warnings": "warning_count",
}


def wrap_workflow_node(
    handler: Callable[[Any], Any],
    *,
    workflow_name: str,
    lane: str,
    node_name: str,
    timing_field: str | None = None,
) -> Callable[[Any], Awaitable[dict[str, Any]]]:
    """Wrap a workflow node with a single lightweight LangSmith span."""

    async def wrapped(state: Any) -> dict[str, Any]:
        state_mapping = state if isinstance(state, Mapping) else {}
        subject = str(state_mapping.get("subject", "") or "")
        build_session_id = _resolve_build_session_id(state_mapping)
        trace_metadata = _node_trace_metadata(state_mapping)
        node_logger = logger.bind(
            workflow=workflow_name,
            lane=lane,
            node=node_name,
            subject=subject,
            build_session_id=build_session_id,
            **trace_metadata,
        )
        started_at = perf_counter()
        run = None
        try:
            with langsmith_trace(
                name=f"{lane}.{node_name}",
                run_type="chain",
                inputs=_node_trace_inputs(state_mapping),
                subject=subject,
                build_session_id=build_session_id,
                workflow=workflow_name,
                lane=lane,
                node=node_name,
                extra_metadata=trace_metadata,
                extra_tags=_node_trace_tags(trace_metadata),
            ) as run:
                with llm_trace_scope(
                    subject=subject,
                    build_session_id=build_session_id,
                    workflow=workflow_name,
                    lane=lane,
                    node=node_name,
                ):
                    result = handler(state)
                    if inspect.isawaitable(result):
                        result = await result
                result_mapping = _coerce_result_mapping(result)
                elapsed_ms = int((perf_counter() - started_at) * 1000)
                if timing_field and timing_field not in result_mapping:
                    result_mapping = {**result_mapping, timing_field: elapsed_ms}
                result_mapping = _merge_runtime_stats(
                    state_mapping,
                    result_mapping,
                    node_name=node_name,
                    lane=lane,
                    workflow_name=workflow_name,
                    elapsed_ms=elapsed_ms,
                    status="failed" if result_mapping.get("error") else "ok",
                )
                if run is not None:
                    run.end(outputs=_node_trace_outputs(result_mapping, elapsed_ms=elapsed_ms))
                await _emit_progress_event(
                    state_mapping,
                    node_name=node_name,
                    lane=lane,
                    workflow_name=workflow_name,
                    elapsed_ms=elapsed_ms,
                    status="failed" if result_mapping.get("error") else "ok",
                )
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            if run is not None:
                run.end(
                    outputs={
                        "elapsed_ms": elapsed_ms,
                        "status": "failed",
                        "error": str(exc),
                    }
                )
            await _emit_progress_event(
                state_mapping,
                node_name=node_name,
                lane=lane,
                workflow_name=workflow_name,
                elapsed_ms=elapsed_ms,
                status="failed",
                error=str(exc),
            )
            node_logger.exception("workflow_node_failed", elapsed_ms=elapsed_ms)
            raise

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "workflow_node_completed",
            elapsed_ms=elapsed_ms,
            status="failed" if result_mapping.get("error") else "ok",
        )
        return result_mapping

    return wrapped


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


def _merge_runtime_stats(
    state: Mapping[str, Any],
    result: Mapping[str, Any],
    *,
    node_name: str,
    lane: str,
    workflow_name: str,
    elapsed_ms: int,
    status: str,
) -> dict[str, Any]:
    merged = dict(result)

    existing_timings: dict[str, int] = {}
    for candidate in (state.get("node_timings_ms"), result.get("node_timings_ms")):
        if isinstance(candidate, Mapping):
            for key, value in candidate.items():
                if value in (None, ""):
                    continue
                existing_timings[str(key)] = int(value)
    existing_timings[node_name] = int(elapsed_ms)
    merged["node_timings_ms"] = existing_timings

    existing_events: list[dict[str, Any]] = []
    for candidate in (state.get("node_events"), result.get("node_events")):
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, Mapping):
                    existing_events.append(dict(item))
    existing_events.append(
        {
            "node_name": node_name,
            "lane": lane,
            "workflow": workflow_name,
            "elapsed_ms": int(elapsed_ms),
            "status": status,
        }
    )
    merged["node_events"] = existing_events[-64:]
    return merged


async def _emit_progress_event(
    state: Mapping[str, Any],
    *,
    node_name: str,
    lane: str,
    workflow_name: str,
    elapsed_ms: int,
    status: str,
    error: str | None = None,
) -> None:
    callback = state.get("progress_callback")
    if callback is None or not callable(callback):
        return

    payload = {
        "node_name": node_name,
        "lane": lane,
        "workflow": workflow_name,
        "elapsed_ms": int(elapsed_ms),
        "status": status,
    }
    chapter_index = _extract_chapter_index(state)
    if chapter_index is not None:
        payload["chapter_index"] = chapter_index
    if error:
        payload["error"] = error

    maybe_awaitable = callback(payload)
    if inspect.isawaitable(maybe_awaitable):
        await maybe_awaitable


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


def _node_trace_inputs(state: Mapping[str, Any]) -> dict[str, Any]:
    inputs: dict[str, Any] = {}
    for field_name in _TRACE_INPUT_FIELDS:
        value = state.get(field_name)
        if value not in (None, "", [], {}):
            inputs[field_name] = value
    for field_name, alias in _COUNT_FIELDS.items():
        value = state.get(field_name)
        if isinstance(value, list) and value:
            inputs[alias] = len(value)
    chapter_index = _extract_chapter_index(state)
    if chapter_index is not None:
        inputs["chapter_index"] = chapter_index
    return inputs


def _node_trace_outputs(result: Mapping[str, Any], *, elapsed_ms: int) -> dict[str, Any]:
    outputs: dict[str, Any] = {
        "elapsed_ms": elapsed_ms,
        "status": "failed" if result.get("error") else "ok",
        "output_keys": sorted(str(key) for key in result.keys()),
    }

    for field_name, value in result.items():
        if field_name.endswith("_ms") and isinstance(value, (int, float)) and value:
            outputs[field_name] = int(value)

    for field_name, alias in _COUNT_FIELDS.items():
        value = result.get(field_name)
        if isinstance(value, list):
            outputs[alias] = len(value)

    if result.get("chapter_materials"):
        chapter_materials = list(result.get("chapter_materials", []))
        outputs["source_count"] = sum(len(item.get("sources", []) or []) for item in chapter_materials)
        outputs["local_hits"] = sum(int(item.get("local_hits", 0) or 0) for item in chapter_materials)
        outputs["web_hits"] = sum(int(item.get("web_hits", 0) or 0) for item in chapter_materials)
        outputs["fallback_used"] = any(bool(item.get("fallback_used", False)) for item in chapter_materials)
        outputs["trusted_source_count"] = sum(int(item.get("trusted_source_count", 0) or 0) for item in chapter_materials)
        outputs["planned_query_count"] = sum(len(item.get("planned_queries", []) or []) for item in chapter_materials)
        outputs["executed_query_count"] = sum(len(item.get("executed_queries", []) or []) for item in chapter_materials)
        outputs["read_url_count"] = sum(int(item.get("read_url_count", 0) or 0) for item in chapter_materials)
        outputs["document_count"] = sum(int(item.get("document_count", 0) or 0) for item in chapter_materials)
        retriever_names = sorted(
            {
                str(retriever_name)
                for item in chapter_materials
                for retriever_name in dict(item.get("retriever_stats", {}) or {}).keys()
                if str(retriever_name).strip()
            }
        )
        if retriever_names:
            outputs["retriever_names"] = retriever_names
            outputs["retriever_count"] = len(retriever_names)
        compression_modes = sorted(
            {
                str(item.get("compression_mode") or "").strip()
                for item in chapter_materials
                if str(item.get("compression_mode") or "").strip()
            }
        )
        if compression_modes:
            outputs["compression_mode"] = ",".join(compression_modes)

    if result.get("chapter_drafts"):
        chapter_drafts = list(result.get("chapter_drafts", []))
        outputs["word_count"] = sum(int(item.get("word_count", 0) or 0) for item in chapter_drafts)
        outputs["placeholder_count"] = sum(int(item.get("placeholder_count", 0) or 0) for item in chapter_drafts)

    if result.get("chapter_metadatas"):
        chapter_metadatas = list(result.get("chapter_metadatas", []))
        outputs["source_count"] = sum(len(item.get("sources", []) or []) for item in chapter_metadatas)
        outputs["final_word_count"] = sum(count_words(str(item.get("markdown") or "")) for item in chapter_metadatas)

    merged_markdown = str(
        result.get("enriched_markdown")
        or result.get("merged_markdown")
        or result.get("enhanced_markdown")
        or ""
    )
    if merged_markdown.strip():
        outputs["final_word_count"] = count_words(merged_markdown)

    assistant_response = str(result.get("assistant_response") or "")
    if assistant_response:
        outputs["response_chars"] = len(assistant_response)

    for field_name in (
        "asset_ocr_images",
        "asset_ocr_replacements",
        "templates_created",
        "stream_interrupted",
        "mastery_updated",
        "review_scheduled",
        "weaknesses_ranked",
        "report_generated",
    ):
        value = result.get(field_name)
        if value not in (None, "", [], {}):
            outputs[field_name] = value

    grade_result = result.get("grade_result")
    if grade_result is not None:
        for attr_name in ("correct_items", "total_items", "score"):
            value = _read_attr_or_key(grade_result, attr_name)
            if value not in (None, ""):
                outputs[attr_name] = value

    mastery_result = result.get("mastery_result")
    if mastery_result is not None:
        for attr_name in ("states_updated", "already_consumed"):
            value = _read_attr_or_key(mastery_result, attr_name)
            if value not in (None, ""):
                outputs[attr_name] = value

    if result.get("error"):
        outputs["error"] = str(result.get("error"))
    return outputs


def _node_trace_tags(metadata: Mapping[str, Any]) -> list[str]:
    tags: list[str] = []
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


def _read_attr_or_key(payload: Any, field_name: str) -> Any:
    if isinstance(payload, Mapping):
        return payload.get(field_name)
    return getattr(payload, field_name, None)
