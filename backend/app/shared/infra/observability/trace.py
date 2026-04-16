"""LangSmith tracing scope, trace context, and @traceable wrappers."""

from __future__ import annotations

import functools
import inspect
import json
import os
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Literal

import httpx
from langsmith import trace as langsmith_trace_run
from langsmith import traceable
from langsmith import tracing_context

from app.shared.infra.settings import get_settings
from app.shared.infra.env_support import get_env, get_env_bool, get_env_int, get_env_optional_bool
from app.shared.infra.runtime import get_app_version, is_local_mode

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

_SAFE_LANGSMITH_FIELDS = {
    "content_type",
    "finish_reason",
    "id",
    "model",
    "name",
    "reader_name",
    "retriever_name",
    "role",
    "source",
    "tool_call_id",
    "type",
    "url",
}


@dataclass
class LLMTraceContext:
    """Context automatically attached to nested LLM calls."""

    subject: str = ""
    build_session_id: str = ""
    workflow: str = ""
    lane: str = ""
    node: str = ""


_TRACE_CONTEXT: ContextVar[LLMTraceContext | None] = ContextVar("llm_trace_context", default=None)
_LANGSMITH_REACHABILITY_CACHE: dict[str, tuple[float, bool]] = {}


def get_llm_trace_context() -> LLMTraceContext:
    """Return the current ambient LLM trace context."""

    return _TRACE_CONTEXT.get() or LLMTraceContext()


def langsmith_tracing_requested() -> bool:
    return get_env_bool("LANGSMITH_TRACING", False)


def get_langsmith_project_name() -> str | None:
    value = (get_env("LANGSMITH_PROJECT", "AITeachMe") or "AITeachMe").strip()
    return value or None


def get_langsmith_max_text_chars() -> int:
    return max(32, get_env_int("LANGSMITH_MAX_TEXT_CHARS", 2000))


def get_langsmith_endpoint() -> str:
    value = (get_env("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com") or "").strip()
    return value.rstrip("/")


def get_langsmith_connect_timeout_s() -> float:
    try:
        value = float(get_env("LANGSMITH_CONNECT_TIMEOUT_S", "2") or "2")
    except ValueError:
        value = 2.0
    return max(0.2, value)


def get_langsmith_probe_ttl_s() -> float:
    try:
        value = float(get_env("LANGSMITH_PROBE_TTL_S", "60") or "60")
    except ValueError:
        value = 60.0
    return max(5.0, value)


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


def _langsmith_endpoint_reachable() -> bool:
    endpoint = get_langsmith_endpoint()
    if not endpoint:
        return False

    now = time.monotonic()
    cached = _LANGSMITH_REACHABILITY_CACHE.get(endpoint)
    ttl = get_langsmith_probe_ttl_s()
    if cached is not None and now - cached[0] < ttl:
        return cached[1]

    reachable = False
    try:
        with httpx.Client(timeout=get_langsmith_connect_timeout_s(), follow_redirects=True) as client:
            response = client.get(f"{endpoint}/info")
            reachable = response.is_success
    except Exception:
        reachable = False

    _LANGSMITH_REACHABILITY_CACHE[endpoint] = (now, reachable)
    return reachable


def langsmith_tracing_enabled() -> bool:
    """Whether LangSmith tracing should be enabled for the current process."""

    settings = get_settings()
    return (
        settings.observability.tracing_enabled
        and langsmith_tracing_requested()
        and _langsmith_api_key_present()
        and _langsmith_endpoint_reachable()
    )


def normalize_langsmith_run_type(
    value: str | None,
    *,
    default: LangSmithRunType = "tool",
) -> LangSmithRunType:
    normalized = str(value or "").strip().lower()
    if normalized in LANGSMITH_RUN_TYPES:
        return normalized  # type: ignore[return-value]
    return default


def _serialize_langsmith_value(value: Any) -> Any:
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump", None)):
        value = value.model_dump(mode="json")
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _redacted_data_url(text: str) -> str:
    prefix = str(text or "").split(";", 1)[0]
    mime_type = prefix[5:].strip().lower() if prefix.lower().startswith("data:") else "unknown"
    return f"[redacted:data-url:{mime_type or 'unknown'}]"


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


def sanitize_langsmith_text(
    text: str,
    *,
    capture_text: bool,
    field_name: str = "",
) -> str:
    normalized_field = str(field_name or "").strip().lower()
    if text.lower().startswith("data:"):
        return _redacted_data_url(text)
    if normalized_field in {"url", "urls", "image_url", "base64"} and not capture_text:
        return "[redacted:url]"
    if normalized_field in _SAFE_LANGSMITH_FIELDS:
        return _sanitize_langsmith_metadata_value(text)
    if not capture_text and text:
        return "[redacted]"
    return _sanitize_langsmith_metadata_value(text)


def sanitize_langsmith_value(
    value: Any,
    *,
    capture_text: bool,
    field_name: str = "",
) -> Any:
    if hasattr(value, "model_dump") and callable(getattr(value, "model_dump", None)):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {
            str(key): sanitize_langsmith_value(item, capture_text=capture_text, field_name=str(key))
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, (list, tuple, set)):
        return [
            sanitize_langsmith_value(item, capture_text=capture_text, field_name=field_name)
            for item in value
        ]
    if isinstance(value, str):
        return sanitize_langsmith_text(value, capture_text=capture_text, field_name=field_name)
    return _serialize_langsmith_value(value)


def sanitize_langsmith_input(
    value: Any,
    *,
    field_name: str = "",
) -> Any:
    return sanitize_langsmith_value(
        value,
        capture_text=langsmith_capture_inputs_enabled(),
        field_name=field_name,
    )


def sanitize_langsmith_output(
    value: Any,
    *,
    field_name: str = "",
) -> Any:
    return sanitize_langsmith_value(
        value,
        capture_text=langsmith_capture_outputs_enabled(),
        field_name=field_name,
    )


def build_langsmith_metadata(
    *,
    subject: str = "",
    build_session_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
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
    extra_tags: Sequence[str] | None = None,
) -> list[str]:
    """Build sparse LangSmith tags.

    Keep tags low-cardinality for filtering. Detailed dimensions such as
    subject, build_session_id, node, mode, retrieval profile, or chapter index
    belong in metadata.
    """

    tags = ["aiteachme"]
    if workflow:
        tags.append(f"workflow:{workflow}")
    if lane:
        tags.append(f"lane:{lane}")
    if extra_tags:
        tags.extend(str(tag) for tag in extra_tags if str(tag))
    return list(dict.fromkeys(tags))


def _build_langsmith_context(
    *,
    subject: str = "",
    build_session_id: str = "",
    workflow: str = "",
    lane: str = "",
    node: str = "",
    extra_metadata: Mapping[str, Any] | None = None,
    extra_tags: Sequence[str] | None = None,
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
    extra_tags: Sequence[str] | None = None,
) -> dict[str, Any] | None:
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
                if not langsmith_tracing_enabled():
                    return await func(*args, **kwargs)
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
            if not langsmith_tracing_enabled():
                return func(*args, **kwargs)
            return traced_func(*args, langsmith_extra=merged_extra, **kwargs)

        return sync_wrapper

    return decorator


__all__ = [
    "LANGSMITH_RUN_TYPES",
    "LLMTraceContext",
    "LangSmithRunType",
    "build_langsmith_extra",
    "build_langsmith_metadata",
    "build_langsmith_tags",
    "get_langsmith_max_text_chars",
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
    "sanitize_langsmith_input",
    "sanitize_langsmith_output",
    "sanitize_langsmith_text",
    "sanitize_langsmith_value",
    "trace_substep",
    "traceable_with_context",
]
