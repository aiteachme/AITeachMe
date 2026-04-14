"""LangSmith tracing scope, trace context, and @traceable wrappers."""

from __future__ import annotations

import functools
import inspect
import os

from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Literal

from langsmith import trace as langsmith_trace_run
from langsmith import traceable
from langsmith import tracing_context

from app.shared.infra.config import get_settings
from app.shared.infra.env_support import get_env, get_env_bool, get_env_optional_bool
from app.shared.infra.runtime import is_local_mode

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


def get_llm_trace_context() -> LLMTraceContext:
    """Return the current ambient LLM trace context."""

    return _TRACE_CONTEXT.get() or LLMTraceContext()


# ── Environment and config helpers ────────────────────────────────────


def langsmith_tracing_requested() -> bool:
    return get_env_bool("LANGSMITH_TRACING", False)


def get_langsmith_project_name() -> str | None:
    value = (get_env("LANGSMITH_PROJECT", "AITeachMe") or "AITeachMe").strip()
    return value or None


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


def langsmith_tracing_enabled() -> bool:
    """Whether LangSmith tracing should be enabled for the current process."""

    settings = get_settings()
    return settings.tracing_enabled and langsmith_tracing_requested() and _langsmith_api_key_present()


def normalize_langsmith_run_type(
    value: str | None,
    *,
    default: LangSmithRunType = "tool",
) -> LangSmithRunType:
    normalized = str(value or "").strip().lower()
    if normalized in LANGSMITH_RUN_TYPES:
        return normalized  # type: ignore[return-value]
    return default


# ── Trace context scopes ──────────────────────────────────────────────


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

    from app.shared.infra.observability.builder import _build_langsmith_context

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

    from app.shared.infra.observability.builder import _build_langsmith_context

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


# ── @traceable wrappers ───────────────────────────────────────────────


def _merge_langsmith_extras(
    base: dict[str, Any] | None,
    override: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not base:
        return dict(override or {}) or None
    if not override:
        return dict(base)

    merged = dict(base)
    for key, value in override.items():
        if value in (None, "", [], {}):
            continue
        if key == "metadata":
            merged[key] = {
                **dict(merged.get(key) or {}),
                **dict(value or {}),
            }
            continue
        if key == "tags":
            merged[key] = list(dict.fromkeys([*(merged.get(key) or []), *(value or [])]))
            continue
        if key == "run_extra":
            merged[key] = {
                **dict(merged.get(key) or {}),
                **dict(value or {}),
            }
            continue
        merged[key] = value
    return merged


def _build_dynamic_langsmith_extra(
    *,
    name_factory: Callable[..., str | None] | None,
    metadata_factory: Callable[..., Mapping[str, Any] | None] | None,
    tags_factory: Callable[..., Sequence[str] | None] | None,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> dict[str, Any] | None:
    if not langsmith_tracing_enabled():
        return None

    from app.shared.infra.observability.builder import build_langsmith_extra

    context = get_llm_trace_context()
    extra_metadata = metadata_factory(*args, **kwargs) if metadata_factory is not None else None
    extra_tags = list(tags_factory(*args, **kwargs) or []) if tags_factory is not None else None
    extra = build_langsmith_extra(
        subject=context.subject,
        build_session_id=context.build_session_id,
        workflow=context.workflow,
        lane=context.lane,
        node=context.node,
        extra_metadata=extra_metadata,
        extra_tags=extra_tags,
    ) or {}
    if name_factory is not None:
        dynamic_name = str(name_factory(*args, **kwargs) or "").strip()
        if dynamic_name:
            extra["name"] = dynamic_name
    return extra or None


def traceable_with_context(
    *,
    name: str,
    run_type: str = "chain",
    process_inputs=None,
    process_outputs=None,
    name_factory: Callable[..., str | None] | None = None,
    metadata_factory: Callable[..., Mapping[str, Any] | None] | None = None,
    tags_factory: Callable[..., Sequence[str] | None] | None = None,
):
    """Decorator around ``@traceable`` that auto-injects ambient workflow context."""

    traced = traceable(
        name=name,
        run_type=run_type,
        process_inputs=process_inputs,
        process_outputs=process_outputs,
    )

    def decorator(func):
        traced_func = traced(func)

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, langsmith_extra: dict[str, Any] | None = None, **kwargs: Any):
                dynamic_extra = _build_dynamic_langsmith_extra(
                    name_factory=name_factory,
                    metadata_factory=metadata_factory,
                    tags_factory=tags_factory,
                    args=args,
                    kwargs=kwargs,
                )
                merged_extra = _merge_langsmith_extras(dynamic_extra, langsmith_extra)
                return await traced_func(*args, langsmith_extra=merged_extra, **kwargs)

            return async_wrapper

        @functools.wraps(func)
        def sync_wrapper(*args: Any, langsmith_extra: dict[str, Any] | None = None, **kwargs: Any):
            dynamic_extra = _build_dynamic_langsmith_extra(
                name_factory=name_factory,
                metadata_factory=metadata_factory,
                tags_factory=tags_factory,
                args=args,
                kwargs=kwargs,
            )
            merged_extra = _merge_langsmith_extras(dynamic_extra, langsmith_extra)
            return traced_func(*args, langsmith_extra=merged_extra, **kwargs)

        return sync_wrapper

    return decorator


def annotate_traceable(
    func=None,
    *,
    name: str,
    run_type: str = "chain",
    process_inputs=None,
    process_outputs=None,
    name_factory: Callable[..., str | None] | None = None,
    metadata_factory: Callable[..., Mapping[str, Any] | None] | None = None,
    tags_factory: Callable[..., Sequence[str] | None] | None = None,
):
    """Repo-local ``@traceable`` wrapper with ambient trace-context injection."""

    decorator = traceable_with_context(
        name=name,
        run_type=run_type,
        process_inputs=process_inputs,
        process_outputs=process_outputs,
        name_factory=name_factory,
        metadata_factory=metadata_factory,
        tags_factory=tags_factory,
    )
    if func is not None:
        return decorator(func)
    return decorator


__all__ = [
    "LANGSMITH_RUN_TYPES",
    "LLMTraceContext",
    "LangSmithRunType",
    "annotate_traceable",
    "get_langsmith_project_name",
    "get_llm_trace_context",
    "langsmith_capture_inputs_enabled",
    "langsmith_capture_outputs_enabled",
    "langsmith_trace",
    "langsmith_tracing_enabled",
    "langsmith_tracing_requested",
    "langsmith_tracing_scope",
    "llm_trace_scope",
    "normalize_langsmith_run_type",
    "trace_substep",
    "traceable_with_context",
]
