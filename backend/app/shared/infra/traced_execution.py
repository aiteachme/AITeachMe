"""Shared traced execution contract for workflow-owned run units.

This module is infrastructure because it only standardizes tracing, metadata,
and LLM caller resolution. It is not a workflow runtime module. Business steps
such as DocGen research or writing must still live in `workflows/.../runtime`
or a LangGraph subgraph.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.tracing import (
    llm_trace_scope,
    sanitize_langsmith_input,
    sanitize_langsmith_output,
    traceable_with_context,
)

logger = structlog.get_logger(__name__)


def _preview_list(values: list[Any], *, limit: int = 3) -> list[Any]:
    return list(values[: max(1, limit)])


def _preview_source_details(source_details: list[Any], *, limit: int = 3) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for item in source_details[: max(1, limit)]:
        if not isinstance(item, Mapping):
            continue
        preview.append(
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": item.get("snippet"),
                "source": item.get("source"),
            }
        )
    return preview


def _preview_research_rounds(rounds: list[Any], *, limit: int = 2) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for item in rounds[: max(1, limit)]:
        if not isinstance(item, Mapping):
            continue
        preview.append(
            {
                "round_index": item.get("round_index"),
                "executed_queries": _preview_list(list(item.get("executed_queries") or []), limit=3),
                "coverage_score": item.get("coverage_score"),
                "local_hits": item.get("local_hits"),
                "web_hits": item.get("web_hits"),
            }
        )
    return preview


class WorkflowTraceContext(Protocol):
    workflow_name: str
    metadata: Mapping[str, Any]


@dataclass(slots=True)
class TracedExecutionContext:
    subject: str
    build_session_id: str = ""
    workflow_context: WorkflowTraceContext | None = None
    planner_session_id: str = ""
    confirmed_plan_id: str = ""
    digest_mode: str = ""
    course_type: str = ""
    retrieval_profile: str = ""
    teaching_action: str = ""
    asset_kind: str = ""
    chapter_index: int | None = None
    llm_caller: Callable[..., Awaitable[Any]] | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def resolve_llm_caller(self) -> Callable[..., Awaitable[Any]]:
        return self.llm_caller or acompletion_with_fallback

    def trace_metadata(self, **extra: Any) -> dict[str, Any]:
        metadata = dict(self.extra_metadata)
        if self.planner_session_id:
            metadata.setdefault("planner_session_id", self.planner_session_id)
        if self.confirmed_plan_id:
            metadata.setdefault("confirmed_plan_id", self.confirmed_plan_id)
        if self.digest_mode:
            metadata.setdefault("digest_mode", self.digest_mode)
        if self.course_type:
            metadata.setdefault("course_type", self.course_type)
        if self.retrieval_profile:
            metadata.setdefault("retrieval_profile", self.retrieval_profile)
        if self.teaching_action:
            metadata.setdefault("teaching_action", self.teaching_action)
        if self.asset_kind:
            metadata.setdefault("asset_kind", self.asset_kind)
        if self.chapter_index is not None:
            metadata.setdefault("chapter_index", self.chapter_index)
        metadata.update({key: value for key, value in extra.items() if value not in (None, "", [], {})})
        return metadata


@dataclass(slots=True)
class TracedExecutionResult:
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    images: list[dict[str, Any]] = field(default_factory=list)
    cost_tokens: int = 0


class BaseTracedExecution(ABC):
    def __init__(self, context: TracedExecutionContext) -> None:
        self.context = context
        self.logger = structlog.get_logger(__name__).bind(
            traced_unit=self.trace_node,
            subject=context.subject,
            build_session_id=context.build_session_id,
        )

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @property
    def trace_namespace(self) -> str:
        return "traced_execution"

    @property
    def trace_name(self) -> str:
        return self.name

    @property
    def trace_node(self) -> str:
        namespace = str(self.trace_namespace or "").strip(". ")
        name = str(self.trace_name or self.name).strip(". ")
        return f"{namespace}.{name}" if namespace else name

    async def run(self, **kwargs: Any) -> TracedExecutionResult:
        workflow_context = self.context.workflow_context
        workflow_name = getattr(workflow_context, "workflow_name", "") if workflow_context is not None else ""
        metadata = getattr(workflow_context, "metadata", {}) if workflow_context is not None else {}
        lane = str(metadata.get("lane", "")) if isinstance(metadata, Mapping) else ""
        node = self.trace_node
        with llm_trace_scope(
            subject=self.context.subject,
            build_session_id=self.context.build_session_id,
            workflow=workflow_name,
            lane=lane,
            node=node,
        ):
            payload = await _invoke_traced_execution(
                payload=kwargs,
                runner=self,
                workflow_name=workflow_name,
                lane=lane,
                node=node,
            )
        return payload["result"]

    @abstractmethod
    async def execute(self, **kwargs: Any) -> TracedExecutionResult:
        raise NotImplementedError


def _traced_execution_outputs(result: TracedExecutionResult) -> dict[str, Any]:
    outputs: dict[str, Any] = {
        "status": "ok",
        "content_length": len(result.content),
        "source_count": len(result.sources),
        "image_count": len(result.images),
    }
    for field_name in (
        "local_hits",
        "web_hits",
        "query_count",
        "read_url_count",
        "research_round_count",
        "document_count",
        "candidate_count",
        "selected_count",
        "curated_source_count",
        "trusted_source_count",
        "local_source_count",
        "web_source_count",
        "unique_domain_count",
    ):
        value = result.metadata.get(field_name)
        if value not in (None, "", [], {}):
            outputs[field_name] = value
    for field_name in ("fallback_used", "purify_used", "repair_applied", "cache_hit"):
        value = result.metadata.get(field_name)
        if value is not None:
            outputs[field_name] = bool(value)
    for field_name in (
        "compression_mode",
        "cache_status",
        "stop_reason",
        "requested_profile",
        "applied_profile",
        "requested_retrieval_profile",
        "applied_retrieval_profile",
        "template_kind",
    ):
        value = str(result.metadata.get(field_name) or "").strip()
        if value:
            outputs[field_name] = value
    coverage_score = result.metadata.get("coverage_score")
    if coverage_score not in (None, ""):
        outputs["coverage_score"] = float(coverage_score)
    quality_score = result.metadata.get("quality_score")
    if quality_score not in (None, ""):
        outputs["quality_score"] = float(quality_score)
    gaps_remaining = result.metadata.get("gaps_remaining")
    if isinstance(gaps_remaining, list):
        outputs["gap_count"] = len([item for item in gaps_remaining if str(item).strip()])
    source_class_breakdown = result.metadata.get("source_class_breakdown")
    if isinstance(source_class_breakdown, Mapping) and source_class_breakdown:
        outputs["source_class_breakdown"] = dict(source_class_breakdown)
    retriever_stats = result.metadata.get("retriever_stats")
    if isinstance(retriever_stats, Mapping) and retriever_stats:
        outputs["retriever_names"] = sorted(str(name) for name in retriever_stats.keys())
        outputs["retriever_call_count"] = sum(
            int((stats or {}).get("query_count", 0) or 0)
            for stats in retriever_stats.values()
            if isinstance(stats, Mapping)
        )
    configured_retrievers = result.metadata.get("configured_retrievers")
    if isinstance(configured_retrievers, list):
        outputs["configured_retriever_count"] = len(
            [name for name in configured_retrievers if str(name).strip()]
        )
    active_retrievers = result.metadata.get("active_retrievers")
    if isinstance(active_retrievers, list):
        outputs["active_retriever_count"] = len(
            [name for name in active_retrievers if str(name).strip()]
        )
    executed_queries = result.metadata.get("executed_queries")
    if isinstance(executed_queries, list) and executed_queries:
        outputs["executed_queries_preview"] = sanitize_langsmith_output(
            _preview_list(list(executed_queries)),
            field_name="executed_queries",
        )
    source_details = result.metadata.get("source_details")
    if isinstance(source_details, list) and source_details:
        outputs["source_details_preview"] = sanitize_langsmith_output(
            _preview_source_details(source_details, limit=2),
            field_name="source_details",
        )
    research_rounds = result.metadata.get("research_rounds")
    if isinstance(research_rounds, list) and research_rounds:
        outputs["research_rounds_preview"] = sanitize_langsmith_output(
            _preview_research_rounds(research_rounds),
            field_name="research_rounds",
        )
    return outputs


def _traced_execution_trace_outputs(payload: Any) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        trace_outputs = payload.get("trace")
        if isinstance(trace_outputs, Mapping):
            return dict(trace_outputs)
    return {}


def _traced_execution_metadata(
    *,
    runner: BaseTracedExecution,
    **_: Any,
) -> dict[str, Any]:
    return runner.context.trace_metadata(
        traced_unit_name=runner.name,
        trace_namespace=runner.trace_namespace,
        trace_name=runner.trace_name,
    )


def _traced_execution_tags(
    *,
    runner: BaseTracedExecution,
    **_: Any,
) -> list[str]:
    tag_namespace = str(runner.trace_namespace or "traced_execution").strip(". ")
    tags = [f"{tag_namespace}:{runner.trace_name}"]
    if runner.context.digest_mode:
        tags.append(f"mode:{runner.context.digest_mode}")
    if runner.context.course_type:
        tags.append(f"course:{runner.context.course_type}")
    if runner.context.retrieval_profile:
        tags.append(f"retrieval:{runner.context.retrieval_profile}")
    if runner.context.teaching_action:
        tags.append(f"teaching:{runner.context.teaching_action}")
    if runner.context.asset_kind:
        tags.append(f"asset:{runner.context.asset_kind}")
    if runner.context.chapter_index is not None:
        tags.append(f"chapter:{runner.context.chapter_index}")
    return tags


def _traced_execution_inputs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "input_keys": sorted(str(key) for key in kwargs.keys()),
    }

    chapter_plan = kwargs.get("chapter_plan")
    if isinstance(chapter_plan, Mapping):
        chapter_index = chapter_plan.get("chapter_index")
        title = str(chapter_plan.get("title") or "").strip()
        if chapter_index not in (None, ""):
            inputs["chapter_index"] = int(chapter_index)
        if title:
            inputs["chapter_title"] = title

    for field_name in ("digest_mode", "tone", "template_kind", "asset_kind"):
        value = kwargs.get(field_name)
        if value not in (None, "", [], {}):
            inputs[field_name] = value
    for field_name in ("query", "chapter_title", "objective"):
        value = kwargs.get(field_name)
        if value not in (None, "", [], {}):
            inputs[field_name] = sanitize_langsmith_input(value, field_name=field_name)
    for field_name in ("queries",):
        value = kwargs.get(field_name)
        if isinstance(value, list) and value:
            inputs[f"{field_name}_preview"] = sanitize_langsmith_input(
                _preview_list(list(value)),
                field_name=field_name,
            )

    for field_name, alias in (
        ("sources", "source_count"),
        ("images", "image_count"),
        ("gaps_remaining", "gap_count"),
    ):
        value = kwargs.get(field_name)
        if isinstance(value, list) and value:
            inputs[alias] = len(value)

    return inputs


@traceable_with_context(
    name="traced_execution.run",
    run_type="chain",
    process_inputs=lambda inputs: _traced_execution_inputs(inputs.get("payload") or {}),
    process_outputs=_traced_execution_trace_outputs,
    name_factory=lambda *, node, **_: node,
    metadata_factory=_traced_execution_metadata,
    tags_factory=_traced_execution_tags,
)
async def _invoke_traced_execution(
    *,
    payload: Mapping[str, Any],
    runner: BaseTracedExecution,
    workflow_name: str,
    lane: str,
    node: str,
    langsmith_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    del workflow_name, lane, node, langsmith_extra
    result = await runner.execute(**dict(payload))
    return {
        "result": result,
        "trace": _traced_execution_outputs(result),
    }

__all__ = [
    "BaseTracedExecution",
    "TracedExecutionContext",
    "TracedExecutionResult",
]
