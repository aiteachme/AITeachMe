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
from app.shared.infra.tracing import langsmith_trace, llm_trace_scope

logger = structlog.get_logger(__name__)


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
        tag_namespace = str(self.trace_namespace or "traced_execution").strip(". ")
        extra_tags = [f"{tag_namespace}:{self.trace_name}"]
        if self.context.digest_mode:
            extra_tags.append(f"mode:{self.context.digest_mode}")
        if self.context.course_type:
            extra_tags.append(f"course:{self.context.course_type}")
        if self.context.retrieval_profile:
            extra_tags.append(f"retrieval:{self.context.retrieval_profile}")
        if self.context.teaching_action:
            extra_tags.append(f"teaching:{self.context.teaching_action}")
        if self.context.asset_kind:
            extra_tags.append(f"asset:{self.context.asset_kind}")
        if self.context.chapter_index is not None:
            extra_tags.append(f"chapter:{self.context.chapter_index}")
        with langsmith_trace(
            name=node,
            run_type="chain",
            inputs=kwargs,
            subject=self.context.subject,
            build_session_id=self.context.build_session_id,
            workflow=workflow_name,
            lane=lane,
            node=node,
            extra_metadata=self.context.trace_metadata(
                traced_unit_name=self.name,
                trace_namespace=self.trace_namespace,
                trace_name=self.trace_name,
            ),
            extra_tags=extra_tags,
        ) as run:
            with llm_trace_scope(
                subject=self.context.subject,
                build_session_id=self.context.build_session_id,
                workflow=workflow_name,
                lane=lane,
                node=node,
            ):
                result = await self.execute(**kwargs)
            if run is not None:
                run.end(outputs=_traced_execution_outputs(result))
            return result

    @abstractmethod
    async def execute(self, **kwargs: Any) -> TracedExecutionResult:
        raise NotImplementedError


def _traced_execution_outputs(result: TracedExecutionResult) -> dict[str, Any]:
    outputs: dict[str, Any] = {
        "content_length": len(result.content),
        "source_count": len(result.sources),
        "image_count": len(result.images),
        "metadata_keys": sorted(result.metadata.keys()),
    }
    for field_name in (
        "local_hits",
        "web_hits",
        "query_count",
        "scraped_url_count",
        "document_count",
        "candidate_count",
        "filtered_count",
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
    for field_name in ("fallback_used", "purify_used"):
        value = result.metadata.get(field_name)
        if value is not None:
            outputs[field_name] = bool(value)
    compression_mode = str(result.metadata.get("compression_mode") or "").strip()
    if compression_mode:
        outputs["compression_mode"] = compression_mode
    applied_retrieval_profile = str(result.metadata.get("applied_retrieval_profile") or "").strip()
    if applied_retrieval_profile:
        outputs["applied_retrieval_profile"] = applied_retrieval_profile
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
    return outputs

__all__ = [
    "BaseTracedExecution",
    "TracedExecutionContext",
    "TracedExecutionResult",
]
