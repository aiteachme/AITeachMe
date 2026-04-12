"""Tracing helpers for workflow-scoped LLM observability."""

from __future__ import annotations

import os

from collections import defaultdict
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Literal
from uuid import uuid4

import structlog
from langsmith import trace as langsmith_trace_run
from langsmith import traceable
from langsmith import tracing_context

from app.shared.infra.config import get_settings
from app.shared.infra.env_support import get_env, get_env_bool, get_env_int, get_env_optional_bool
from app.shared.infra.llm_support.routing import TaskType, get_task_profile
from app.shared.infra.runtime_mode import get_app_version, is_local_mode

logger = structlog.get_logger()

LangSmithRunType = Literal["tool", "chain", "llm", "retriever", "embedding", "prompt", "parser"]
LANGSMITH_RUN_TYPES: tuple[LangSmithRunType, ...] = (
    "tool",
    "chain",
    "llm",
    "retriever",
    "embedding",
    "prompt",
    "parser",
)


@dataclass
class LLMTraceContext:
    """Context automatically attached to nested LLM calls."""

    subject: str = ""
    build_session_id: str = ""
    workflow: str = ""
    lane: str = ""
    node: str = ""


_TRACE_CONTEXT: ContextVar[LLMTraceContext | None] = ContextVar("llm_trace_context", default=None)


def langsmith_tracing_requested() -> bool:
    return get_env_bool("LANGSMITH_TRACING", False)


def get_langsmith_project_name() -> str | None:
    value = (get_env("LANGSMITH_PROJECT", "AITeachMe") or "AITeachMe").strip()
    return value or None


def get_langsmith_max_text_chars() -> int:
    return max(32, get_env_int("LANGSMITH_MAX_TEXT_CHARS", 2000))


def langsmith_capture_inputs_enabled() -> bool:
    explicit_value = get_env_optional_bool("LANGSMITH_CAPTURE_INPUTS")
    if explicit_value is not None:
        return explicit_value
    return is_local_mode()


def langsmith_capture_outputs_enabled() -> bool:
    explicit_value = get_env_optional_bool("LANGSMITH_CAPTURE_OUTPUTS")
    if explicit_value is not None:
        return explicit_value
    return is_local_mode()


def _langsmith_api_key_present() -> bool:
    for env_key in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"):
        if os.getenv(env_key, "").strip():
            return True
    return False


def _sanitize_langsmith_metadata_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_langsmith_metadata_value(item)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
    if isinstance(value, (list, tuple, set)):
        return [
            _sanitize_langsmith_metadata_value(item)
            for item in value
            if item not in (None, "", [], {})
        ]
    if isinstance(value, str):
        if value.lower().startswith("data:"):
            return "[redacted:data-url]"
        limit = get_langsmith_max_text_chars()
        if len(value) <= limit:
            return value
        return f"{value[: max(1, limit - 3)]}..."
    return value


def langsmith_tracing_enabled() -> bool:
    """Whether LangSmith tracing should be enabled for the current process."""

    settings = get_settings()
    return settings.tracing_enabled and langsmith_tracing_requested() and _langsmith_api_key_present()


def build_langsmith_metadata(
    *,
    subject: str = "",
    build_session_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a normalized LangSmith metadata payload."""

    metadata: dict[str, Any] = {
        "app": "aiteachme-backend",
        "app_version": get_app_version(),
    }
    if subject:
        metadata["subject"] = subject
    if build_session_id:
        metadata["build_session_id"] = build_session_id
    if workflow:
        metadata["workflow"] = workflow
    if lane:
        metadata["lane"] = lane
    if node:
        metadata["node"] = node
    if extra_metadata:
        metadata.update(
            {
                str(key): _sanitize_langsmith_metadata_value(value)
                for key, value in extra_metadata.items()
                if value not in (None, "", [], {})
            }
        )
    return metadata


def build_langsmith_tags(
    *,
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_tags: list[str] | None = None,
) -> list[str]:
    """Build a stable LangSmith tag list."""

    tags = ["aiteachme"]
    if workflow:
        tags.append(f"workflow:{workflow}")
    if lane:
        tags.append(f"lane:{lane}")
    if node:
        tags.append(f"node:{node}")
    if extra_tags:
        tags.extend(tag for tag in extra_tags if tag)
    return list(dict.fromkeys(tags))


def _build_langsmith_context(
    *,
    subject: str = "",
    build_session_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
    extra_tags: list[str] | None = None,
) -> tuple[str | None, dict[str, Any], list[str]]:
    project_name = get_langsmith_project_name()
    metadata = build_langsmith_metadata(
        subject=subject,
        build_session_id=build_session_id,
        workflow=workflow,
        lane=lane,
        node=node,
        extra_metadata=extra_metadata,
    )
    tags = build_langsmith_tags(
        workflow=workflow,
        lane=lane,
        node=node,
        extra_tags=extra_tags,
    )
    return project_name, metadata, tags


def build_langsmith_extra(
    *,
    subject: str = "",
    build_session_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
    extra_tags: list[str] | None = None,
) -> dict[str, Any] | None:
    """Build one ``langsmith_extra`` payload for ``@traceable`` calls."""

    if not langsmith_tracing_enabled():
        return None

    project_name, metadata, tags = _build_langsmith_context(
        subject=subject,
        build_session_id=build_session_id,
        workflow=workflow,
        lane=lane,
        node=node,
        extra_metadata=extra_metadata,
        extra_tags=extra_tags,
    )
    extra: dict[str, Any] = {
        "metadata": metadata,
        "tags": tags,
    }
    if project_name:
        extra["project_name"] = project_name
    return extra


def annotate_traceable(
    func,
    *,
    name: str,
    run_type: str = "chain",
    process_inputs=None,
    process_outputs=None,
):
    """Small wrapper around ``langsmith.traceable`` for repo-local helpers."""

    return traceable(
        name=name,
        run_type=run_type,
        process_inputs=process_inputs,
        process_outputs=process_outputs,
    )(func)



def normalize_langsmith_run_type(
    value: str | None,
    *,
    default: LangSmithRunType = "tool",
) -> LangSmithRunType:
    normalized = str(value or "").strip().lower()
    if normalized in LANGSMITH_RUN_TYPES:
        return normalized  # type: ignore[return-value]
    return default


@dataclass
class LLMCallRecord:
    """A single LLM call record."""

    task_type: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_s: float = 0.0
    success: bool = True
    error: str | None = None
    call_id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    subject: str = ""
    build_session_id: str = ""
    workflow: str = ""
    lane: str = ""
    node: str = ""


@dataclass
class Span:
    """A simple span primitive for future tracing expansion."""

    name: str
    span_id: str = field(default_factory=lambda: uuid4().hex[:12])
    parent_id: str | None = None
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    events: list[LLMCallRecord] = field(default_factory=list)

    @property
    def duration_s(self) -> float | None:
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds()

    def finish(self) -> None:
        self.end_time = datetime.now(timezone.utc)


class Tracer:
    """Keeps completed spans in memory."""

    def __init__(self) -> None:
        self._active: dict[str, Span] = {}
        self._completed: list[Span] = []

    def start_span(self, name: str, *, parent_id: str | None = None) -> Span:
        span = Span(name=name, parent_id=parent_id)
        self._active[span.span_id] = span
        return span

    def end_span(self, span_id: str) -> Span | None:
        span = self._active.pop(span_id, None)
        if span is not None:
            span.finish()
            self._completed.append(span)
        return span

    def get_completed(self, limit: int = 100) -> list[Span]:
        return self._completed[-limit:]


class LLMCallTracker:
    """In-memory tracker for workflow-scoped LLM calls."""

    def __init__(self) -> None:
        self._records: list[LLMCallRecord] = []

    def record(self, rec: LLMCallRecord) -> None:
        self._records.append(rec)
        max_records = max(1, int(get_settings().llm_observability_max_records))
        overflow = len(self._records) - max_records
        if overflow > 0:
            del self._records[:overflow]
        logger.info(
            "llm_call",
            call_id=rec.call_id,
            task_type=rec.task_type,
            model=rec.model,
            tokens=rec.total_tokens,
            latency=round(rec.latency_s, 2),
            ok=rec.success,
            subject=rec.subject,
            build_session_id=rec.build_session_id,
            workflow=rec.workflow,
            lane=rec.lane,
            node=rec.node,
        )

    def get_summary(
        self,
        *,
        build_session_id: str | None = None,
        subject: str | None = None,
        workflow: str | None = None,
        lane: str | None = None,
        node: str | None = None,
    ) -> dict[str, Any]:
        records = self._filter_records(
            build_session_id=build_session_id,
            subject=subject,
            workflow=workflow,
            lane=lane,
            node=node,
        )
        if not records:
            return self._empty_summary()

        settings = get_settings()
        light_model = ""
        if settings.llm_model_light:
            light_model = get_task_profile(TaskType.DOCGEN_LIGHT).model

        total_latency_ms = int(round(sum(record.latency_s for record in records) * 1000))
        total_calls = len(records)
        failed_call_count = sum(1 for record in records if not record.success)
        prompt_tokens = sum(record.prompt_tokens for record in records)
        completion_tokens = sum(record.completion_tokens for record in records)
        total_tokens = sum(record.total_tokens for record in records)
        tokens_by_model: dict[str, int] = defaultdict(int)
        tokens_by_task_type: dict[str, int] = defaultdict(int)
        tokens_by_lane: dict[str, int] = defaultdict(int)
        tokens_by_node: dict[str, int] = defaultdict(int)
        call_count_by_model: dict[str, int] = defaultdict(int)
        call_count_by_task_type: dict[str, int] = defaultdict(int)
        call_count_by_lane: dict[str, int] = defaultdict(int)
        call_count_by_node: dict[str, int] = defaultdict(int)
        model_usage: dict[str, dict[str, int]] = defaultdict(
            lambda: {
                "call_count": 0,
                "failed_call_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "total_latency_ms": 0,
            }
        )

        light_model_call_count = 0
        light_model_total_tokens = 0
        light_task_call_count = 0
        light_task_total_tokens = 0

        for record in records:
            model_key = record.model or "(unknown_model)"
            task_key = record.task_type or "(unknown_task)"
            lane_key = record.lane or "(unknown_lane)"
            node_key = record.node or "(unknown_node)"
            latency_ms = int(round(record.latency_s * 1000))

            tokens_by_model[model_key] += record.total_tokens
            tokens_by_task_type[task_key] += record.total_tokens
            tokens_by_lane[lane_key] += record.total_tokens
            tokens_by_node[node_key] += record.total_tokens

            call_count_by_model[model_key] += 1
            call_count_by_task_type[task_key] += 1
            call_count_by_lane[lane_key] += 1
            call_count_by_node[node_key] += 1

            model_usage_row = model_usage[model_key]
            model_usage_row["call_count"] += 1
            model_usage_row["failed_call_count"] += 0 if record.success else 1
            model_usage_row["prompt_tokens"] += record.prompt_tokens
            model_usage_row["completion_tokens"] += record.completion_tokens
            model_usage_row["total_tokens"] += record.total_tokens
            model_usage_row["total_latency_ms"] += latency_ms

            if light_model and record.model == light_model:
                light_model_call_count += 1
                light_model_total_tokens += record.total_tokens
            if record.task_type == TaskType.DOCGEN_LIGHT.value:
                light_task_call_count += 1
                light_task_total_tokens += record.total_tokens

        return {
            "total_calls": total_calls,
            "failed_call_count": failed_call_count,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "total_latency_ms": total_latency_ms,
            "avg_latency_ms": round(total_latency_ms / total_calls, 2) if total_calls else 0.0,
            "tokens_by_model": dict(sorted(tokens_by_model.items())),
            "tokens_by_task_type": dict(sorted(tokens_by_task_type.items())),
            "tokens_by_lane": dict(sorted(tokens_by_lane.items())),
            "tokens_by_node": dict(sorted(tokens_by_node.items())),
            "call_count_by_model": dict(sorted(call_count_by_model.items())),
            "call_count_by_task_type": dict(sorted(call_count_by_task_type.items())),
            "call_count_by_lane": dict(sorted(call_count_by_lane.items())),
            "call_count_by_node": dict(sorted(call_count_by_node.items())),
            "model_usage": dict(sorted(model_usage.items())),
            "light_model_call_count": light_model_call_count,
            "light_model_total_tokens": light_model_total_tokens,
            "heavy_model_call_count": total_calls - light_model_call_count,
            "heavy_model_total_tokens": total_tokens - light_model_total_tokens,
            "light_task_call_count": light_task_call_count,
            "light_task_total_tokens": light_task_total_tokens,
            "heavy_task_call_count": total_calls - light_task_call_count,
            "heavy_task_total_tokens": total_tokens - light_task_total_tokens,
            "model_mix_ratio": self._ratio_map(tokens_by_model, total_tokens),
            "task_type_mix_ratio": self._ratio_map(tokens_by_task_type, total_tokens),
        }

    def _filter_records(
        self,
        *,
        build_session_id: str | None,
        subject: str | None,
        workflow: str | None,
        lane: str | None,
        node: str | None,
    ) -> list[LLMCallRecord]:
        return [
            record
            for record in self._records
            if (build_session_id is None or record.build_session_id == build_session_id)
            and (subject is None or record.subject == subject)
            and (workflow is None or record.workflow == workflow)
            and (lane is None or record.lane == lane)
            and (node is None or record.node == node)
        ]

    @staticmethod
    def _ratio_map(values: dict[str, int], total: int) -> dict[str, float]:
        if total <= 0:
            return {}
        return {
            key: round((value / total), 4)
            for key, value in sorted(values.items(), key=lambda item: (-item[1], item[0]))
            if value > 0
        }

    @staticmethod
    def _empty_summary() -> dict[str, Any]:
        return {
            "total_calls": 0,
            "failed_call_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "total_latency_ms": 0,
            "avg_latency_ms": 0.0,
            "tokens_by_model": {},
            "tokens_by_task_type": {},
            "tokens_by_lane": {},
            "tokens_by_node": {},
            "call_count_by_model": {},
            "call_count_by_task_type": {},
            "call_count_by_lane": {},
            "call_count_by_node": {},
            "model_usage": {},
            "light_model_call_count": 0,
            "light_model_total_tokens": 0,
            "heavy_model_call_count": 0,
            "heavy_model_total_tokens": 0,
            "light_task_call_count": 0,
            "light_task_total_tokens": 0,
            "heavy_task_call_count": 0,
            "heavy_task_total_tokens": 0,
            "model_mix_ratio": {},
            "task_type_mix_ratio": {},
        }


@contextmanager
def llm_trace_scope(
    *,
    subject: str = "",
    build_session_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
) -> Iterator[LLMTraceContext]:
    """Temporarily override the ambient LLM trace context."""

    current = _TRACE_CONTEXT.get() or LLMTraceContext()
    merged = LLMTraceContext(
        subject=subject or current.subject,
        build_session_id=build_session_id or current.build_session_id,
        workflow=workflow or current.workflow,
        lane=lane or current.lane,
        node=node or current.node,
    )
    token = _TRACE_CONTEXT.set(merged)
    try:
        yield merged
    finally:
        _TRACE_CONTEXT.reset(token)


@contextmanager
def langsmith_tracing_scope(
    *,
    subject: str = "",
    build_session_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
    extra_tags: list[str] | None = None,
) -> Iterator[None]:
    """Temporarily enable and enrich LangSmith tracing for nested runs."""

    if not langsmith_tracing_enabled():
        yield
        return

    project_name, metadata, tags = _build_langsmith_context(
        subject=subject,
        build_session_id=build_session_id,
        workflow=workflow,
        lane=lane,
        node=node,
        extra_metadata=extra_metadata,
        extra_tags=extra_tags,
    )
    with tracing_context(
        enabled=True,
        project_name=project_name,
        metadata=metadata,
        tags=tags,
    ):
        yield


@contextmanager
def langsmith_trace(
    *,
    name: str,
    run_type: str,
    inputs: dict[str, Any] | None = None,
    subject: str = "",
    build_session_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
    extra_tags: list[str] | None = None,
) -> Iterator[Any | None]:
    """Create a LangSmith run when tracing is enabled."""

    if not langsmith_tracing_enabled():
        yield None
        return

    project_name, metadata, tags = _build_langsmith_context(
        subject=subject,
        build_session_id=build_session_id,
        workflow=workflow,
        lane=lane,
        node=node,
        extra_metadata=extra_metadata,
        extra_tags=extra_tags,
    )
    with tracing_context(
        enabled=True,
        project_name=project_name,
        metadata=metadata,
        tags=tags,
    ):
        with langsmith_trace_run(
            name=name,
            run_type=run_type,
            inputs=inputs,
            project_name=project_name,
            metadata=metadata,
            tags=tags,
        ) as run:
            yield run


@contextmanager
def trace_substep(
    name: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    tags: list[str] | None = None,
    run_type: str = "tool",
    inputs: Mapping[str, Any] | None = None,
) -> Iterator[Any | None]:
    """Create one nested substep span from the ambient workflow trace context."""

    context = get_llm_trace_context()
    with langsmith_trace(
        name=name,
        run_type=run_type,
        inputs=dict(inputs or {}),
        subject=context.subject,
        build_session_id=context.build_session_id,
        workflow=context.workflow,
        lane=context.lane,
        node=context.node,
        extra_metadata={"substep": name, **dict(metadata or {})},
        extra_tags=[f"substep:{name}", *(tags or [])],
    ) as run:
        yield run


def get_llm_trace_context() -> LLMTraceContext:
    """Return the current ambient LLM trace context."""

    return _TRACE_CONTEXT.get() or LLMTraceContext()


_tracer: Tracer | None = None
_tracker: LLMCallTracker | None = None


def get_tracer() -> Tracer:
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def get_tracker() -> LLMCallTracker:
    global _tracker
    if _tracker is None:
        _tracker = LLMCallTracker()
    return _tracker

