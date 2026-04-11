"""Thin workflow node tracing helpers."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from time import perf_counter
from typing import Any

import structlog

from app.shared.infra.tools.builtin.markdown_processing import count_words
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
    "selected_skillpacks",
    "requested_profile",
    "applied_profile",
    "coverage_score",
    "quality_score",
    "interactive_block_count",
    "practice_count",
    "asset_count",
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
    "read_url_count",
    "trusted_source_count",
    "word_count",
    "document_count",
    "chapter_index",
    "coverage_score",
    "quality_score",
    "interactive_block_count",
    "practice_count",
    "asset_count",
    "final_word_count",
)

_TRACE_METADATA_FIELDS = (
    "planner_session_id",
    "confirmed_plan_id",
    "digest_mode",
    "course_type",
    "retrieval_profile",
    "teaching_action",
    "asset_kind",
    "selected_skillpacks",
    "requested_profile",
    "applied_profile",
    "coverage_score",
    "quality_score",
    "interactive_block_count",
    "practice_count",
    "asset_count",
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
        requested_profiles = sorted(
            {
                str(item.get("requested_profile") or item.get("requested_retrieval_profile") or "").strip()
                for item in chapter_materials
                if str(item.get("requested_profile") or item.get("requested_retrieval_profile") or "").strip()
            }
        )
        applied_profiles = sorted(
            {
                str(item.get("applied_profile") or item.get("applied_retrieval_profile") or "").strip()
                for item in chapter_materials
                if str(item.get("applied_profile") or item.get("applied_retrieval_profile") or "").strip()
            }
        )
        if requested_profiles:
            outputs["requested_profiles"] = requested_profiles
        if applied_profiles:
            outputs["applied_profiles"] = applied_profiles
        outputs["research_round_count_total"] = sum(
            int(item.get("research_round_count", 0) or len(item.get("research_rounds", []) or []))
            for item in chapter_materials
        )
        outputs["gap_count"] = sum(
            len([gap for gap in list(item.get("gaps_remaining", []) or []) if str(gap).strip()])
            for item in chapter_materials
        )

    if result.get("chapter_drafts"):
        chapter_drafts = list(result.get("chapter_drafts", []))
        outputs["word_count"] = sum(int(item.get("word_count", 0) or 0) for item in chapter_drafts)
        outputs["placeholder_count"] = sum(int(item.get("placeholder_count", 0) or 0) for item in chapter_drafts)
        outputs["interactive_block_count"] = sum(int(item.get("interactive_block_count", 0) or 0) for item in chapter_drafts)
        coverage_scores = [
            float(item.get("coverage_score", 0.0) or 0.0)
            for item in chapter_drafts
            if float(item.get("coverage_score", 0.0) or 0.0) > 0
        ]
        quality_scores = [
            float(item.get("quality_score", 0.0) or 0.0)
            for item in chapter_drafts
            if float(item.get("quality_score", 0.0) or 0.0) > 0
        ]
        if coverage_scores:
            outputs["coverage_score"] = round(sum(coverage_scores) / len(coverage_scores), 4)
        if quality_scores:
            outputs["quality_score"] = round(sum(quality_scores) / len(quality_scores), 4)

    if result.get("chapter_metadatas"):
        chapter_metadatas = list(result.get("chapter_metadatas", []))
        outputs["source_count"] = sum(len(item.get("sources", []) or []) for item in chapter_metadatas)
        outputs["final_word_count"] = sum(count_words(str(item.get("markdown") or "")) for item in chapter_metadatas)
        outputs["practice_count"] = sum(int(item.get("practice_count", 0) or 0) for item in chapter_metadatas)
        outputs["interactive_block_count"] = max(
            int(outputs.get("interactive_block_count", 0) or 0),
            sum(int(item.get("interactive_block_count", 0) or 0) for item in chapter_metadatas),
        )

    for field_name in ("mermaid_block_count", "image_block_count", "interactive_block_count", "practice_count", "asset_count"):
        value = result.get(field_name)
        if value not in (None, "", [], {}):
            outputs[field_name] = int(value)

    asset_summary = result.get("asset_summary")
    if isinstance(asset_summary, Mapping) and asset_summary:
        outputs["asset_summary"] = {
            str(key): int(value or 0)
            for key, value in asset_summary.items()
            if str(key).strip()
        }

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


def _read_attr_or_key(payload: Any, field_name: str) -> Any:
    if isinstance(payload, Mapping):
        return payload.get(field_name)
    return getattr(payload, field_name, None)


__all__ = [
    "traced_workflow_node",
    "trace_workflow_node",
    "wrap_workflow_node",
]
