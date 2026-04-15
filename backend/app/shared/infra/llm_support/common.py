"""Shared LiteLLM call plumbing used by the completion helpers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

import structlog

from app.schemas.llm import ChatMessage
from app.shared.infra.config import Settings, get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError, MissingLLMApiKeyError
from app.shared.infra.llm_support.routing import TaskProfile, TaskType, get_task_profile
from app.shared.infra.observability.trace import get_llm_trace_context
from app.shared.infra.observability.llm_stats import LLMCallRecord, get_tracker

logger = structlog.get_logger()

_REQUEST_TIMEOUT_GRACE_S = 2
_LLM_SEMAPHORE: asyncio.Semaphore | None = None


@dataclass(frozen=True)
class CompletionContext:
    """Resolved configuration shared by one LLM helper invocation."""

    task_type: TaskType
    settings: Settings
    api_key: str
    profile: TaskProfile


def build_completion_context(task_type: TaskType) -> CompletionContext:
    """Resolve config and credentials for one task-scoped LLM call."""

    settings = get_settings()
    api_key = (get_env("LLM_API_KEY") or "").strip()
    if not api_key:
        raise MissingLLMApiKeyError()
    return CompletionContext(
        task_type=task_type,
        settings=settings,
        api_key=api_key,
        profile=get_task_profile(task_type),
    )


def request_timeout_s(timeout_s: int) -> int:
    """Apply a small grace window around provider-side timeouts."""

    return int(timeout_s) + _REQUEST_TIMEOUT_GRACE_S


def get_semaphore() -> asyncio.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        _LLM_SEMAPHORE = asyncio.Semaphore(get_settings().llm_concurrency_limit)
    return _LLM_SEMAPHORE


def extract_usage(response: Any) -> tuple[int, int, int]:
    """Extract token usage from LiteLLM or Instructor responses."""

    candidates = [
        response,
        getattr(response, "_raw_response", None),
        getattr(response, "raw_response", None),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        usage = getattr(candidate, "usage", None)
        if usage is None and isinstance(candidate, Mapping):
            usage = candidate.get("usage") or candidate.get("usage_metadata")
        if usage is None:
            continue

        if isinstance(usage, Mapping):
            prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
            total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
        else:
            prompt_tokens = int(
                getattr(usage, "prompt_tokens", None)
                or getattr(usage, "input_tokens", None)
                or 0
            )
            completion_tokens = int(
                getattr(usage, "completion_tokens", None)
                or getattr(usage, "output_tokens", None)
                or 0
            )
            total_tokens = int(
                getattr(usage, "total_tokens", None)
                or (prompt_tokens + completion_tokens)
            )
        if prompt_tokens or completion_tokens or total_tokens:
            return prompt_tokens, completion_tokens, total_tokens
    return 0, 0, 0


def merge_usage(
    current: tuple[int, int, int],
    candidate: tuple[int, int, int],
) -> tuple[int, int, int]:
    """Prefer the most recent non-empty usage payload."""

    if any(candidate):
        prompt_tokens, completion_tokens, total_tokens = candidate
        return prompt_tokens, completion_tokens, total_tokens or (prompt_tokens + completion_tokens)
    return current


def trace_log_fields() -> dict[str, str]:
    """Attach the current trace context to structured logs."""

    trace = get_llm_trace_context()
    fields: dict[str, str] = {}
    if trace.subject:
        fields["subject"] = trace.subject
    if trace.build_session_id:
        fields["build_session_id"] = trace.build_session_id
    if trace.workflow:
        fields["workflow"] = trace.workflow
    if trace.lane:
        fields["lane"] = trace.lane
    if trace.node:
        fields["node"] = trace.node
    return fields


def build_completion_kwargs(
    *,
    context: CompletionContext,
    messages: list[ChatMessage],
    extra_kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the LiteLLM kwargs shared by all completion modes."""

    remaining_kwargs = dict(extra_kwargs)
    completion_kwargs = {
        "model": f"openai/{context.profile.model}",
        "messages": messages,
        "api_base": (
            get_env("LLM_BASE_URL")
        ),
        "api_key": context.api_key,
        "timeout": context.profile.timeout_s,
        "temperature": remaining_kwargs.pop("temperature", context.profile.temperature),
    }
    if context.profile.max_tokens is not None:
        completion_kwargs["max_tokens"] = context.profile.max_tokens
    completion_kwargs.update(remaining_kwargs)
    return completion_kwargs


def track_call(
    *,
    task_type: TaskType,
    model: str,
    start: float,
    success: bool,
    error: str | None = None,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
) -> None:
    """Record one LLM call in the in-memory observability tracker."""

    settings = get_settings()
    if not settings.llm_observability_enabled:
        return

    trace_context = get_llm_trace_context()
    record = LLMCallRecord(
        task_type=task_type.value,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        latency_s=round(time.monotonic() - start, 3),
        success=success,
        error=error,
        subject=trace_context.subject,
        build_session_id=trace_context.build_session_id,
        workflow=trace_context.workflow,
        lane=trace_context.lane,
        node=trace_context.node,
    )
    get_tracker().record(record)


def raise_last_error(last_error: Exception | None) -> NoReturn:
    """Raise a normalized LLM exception after retries are exhausted."""

    if isinstance(last_error, LLMTimeoutError):
        raise last_error
    reason = str(last_error or "unknown_error")
    raise LLMCallError(reason=reason) from last_error
