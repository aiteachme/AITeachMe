"""Shared LiteLLM call plumbing used by the completion helpers."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

import structlog

from app.schemas.llm import ChatMessage
from app.shared.infra.settings import Settings, get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError, MissingLLMApiKeyError
from app.shared.infra.llm_support.routing import LLMCallProfile, LLMCallPurpose, get_call_profile
from app.shared.infra.observability.trace import get_llm_trace_context
from app.shared.infra.observability.llm_stats import LLMCallRecord, get_tracker

logger = structlog.get_logger()

_REQUEST_TIMEOUT_GRACE_S = 2
_LLM_SEMAPHORE: asyncio.Semaphore | None = None


@dataclass(frozen=True)
class CompletionContext:
    """Resolved configuration shared by one LLM helper invocation."""

    call_purpose: LLMCallPurpose
    settings: Settings
    api_key: str
    profile: LLMCallProfile
    model: str
    model_selector: str

    @property
    def task_type(self) -> LLMCallPurpose:
        """Backward-compatible alias for older logging code."""

        return self.call_purpose


@dataclass(frozen=True)
class CompletionAttempt:
    """Prepared provider call data for one retry attempt."""

    attempt: int
    started_at: float
    call_kwargs: dict[str, Any]
    call_model: str
    provider: str
    tracked_model: str


def normalize_model_selector(value: str | None) -> str | None:
    """Normalize one settings model key or concrete provider model name."""

    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def resolve_settings_model(settings: Settings, model: str | None = None) -> tuple[str, str]:
    """Resolve a provider model name from ``settings.models``."""

    selector = normalize_model_selector(model) or "primary"
    normalized = selector.lower()
    models = settings.models
    fallback_model = models.primary

    if normalized == "reason":
        return models.reason or fallback_model, "reason"
    if normalized == "primary":
        return fallback_model, "primary"
    if normalized == "light":
        return models.light or fallback_model, "light"
    if normalized == "extract":
        return models.extract or models.light or fallback_model, "extract"
    if normalized == "image_generation":
        return models.image_generation or fallback_model, "image_generation"
    return selector, selector


def resolve_call_purpose(
    *,
    call_purpose: LLMCallPurpose | None = None,
    task_type: LLMCallPurpose | None = None,
) -> LLMCallPurpose:
    """Resolve the new ``call_purpose`` name and legacy ``task_type`` name."""

    return call_purpose or task_type or LLMCallPurpose.DEFAULT


def build_completion_context(
    task_type: LLMCallPurpose | None = None,
    *,
    call_purpose: LLMCallPurpose | None = None,
    model: str | None = None,
) -> CompletionContext:
    """Resolve config and credentials for one task-scoped LLM call."""

    resolved_purpose = resolve_call_purpose(call_purpose=call_purpose, task_type=task_type)
    settings = get_settings()
    api_key = (get_env("LLM_API_KEY") or "").strip()
    if not api_key:
        raise MissingLLMApiKeyError()
    resolved_model, model_selector = resolve_settings_model(settings, model)
    return CompletionContext(
        call_purpose=resolved_purpose,
        settings=settings,
        api_key=api_key,
        profile=get_call_profile(resolved_purpose),
        model=resolved_model,
        model_selector=model_selector,
    )


def request_timeout_s(timeout_s: int) -> int:
    """Apply a small grace window around provider-side timeouts."""

    return int(timeout_s) + _REQUEST_TIMEOUT_GRACE_S


def get_semaphore() -> asyncio.Semaphore:
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        _LLM_SEMAPHORE = asyncio.Semaphore(get_settings().runtime.llm_concurrency_limit)
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
        "model": context.model,
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


def prepare_completion_attempt(
    *,
    context: CompletionContext,
    messages: list[ChatMessage],
    extra_kwargs: Mapping[str, Any],
    attempt: int,
    override_kwargs: Mapping[str, Any] | None = None,
) -> CompletionAttempt:
    """Build one attempt payload plus resolved trace model metadata."""

    from app.shared.infra.llm_support.observability import _resolved_trace_model

    call_kwargs = build_completion_kwargs(
        context=context,
        messages=messages,
        extra_kwargs=extra_kwargs,
    )
    if override_kwargs:
        call_kwargs.update(dict(override_kwargs))
    call_model, provider, tracked_model = _resolved_trace_model(
        call_kwargs,
        context.model,
    )
    return CompletionAttempt(
        attempt=attempt,
        started_at=time.monotonic(),
        call_kwargs=call_kwargs,
        call_model=call_model,
        provider=provider,
        tracked_model=tracked_model,
    )


def log_attempt_started(
    event: str,
    *,
    attempt: CompletionAttempt,
    context: CompletionContext,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Emit one standard attempt-start log line."""

    logger.info(
        event,
        attempt=attempt.attempt,
        model=attempt.tracked_model,
        task_type=context.task_type.value,
        timeout_s=context.profile.timeout_s,
        **dict(extra or {}),
    )


def log_attempt_timeout(
    event: str,
    *,
    attempt: CompletionAttempt,
    context: CompletionContext,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Emit one standard timeout log line."""

    logger.warning(
        event,
        attempt=attempt.attempt,
        elapsed_s=round(time.monotonic() - attempt.started_at, 2),
        model=attempt.tracked_model,
        task_type=context.task_type.value,
        timeout_s=context.profile.timeout_s,
        **dict(extra or {}),
        **trace_log_fields(),
    )


def log_attempt_cancelled(
    event: str,
    *,
    attempt: CompletionAttempt,
    context: CompletionContext,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Emit one standard cancelled log line."""

    logger.info(
        event,
        attempt=attempt.attempt,
        elapsed_s=round(time.monotonic() - attempt.started_at, 2),
        model=attempt.tracked_model,
        task_type=context.task_type.value,
        **dict(extra or {}),
        **trace_log_fields(),
    )


def log_attempt_failed(
    event: str,
    *,
    attempt: CompletionAttempt,
    context: CompletionContext,
    error: Exception,
    extra: Mapping[str, Any] | None = None,
    level: str = "warning",
) -> None:
    """Emit one standard failure log line."""

    log_method = getattr(logger, level, logger.warning)
    log_method(
        event,
        attempt=attempt.attempt,
        elapsed_s=round(time.monotonic() - attempt.started_at, 2),
        model=attempt.tracked_model,
        task_type=context.task_type.value,
        error=str(error),
        **dict(extra or {}),
        **trace_log_fields(),
    )


async def sleep_before_retry(attempt: int) -> None:
    """Apply the current linear retry backoff."""

    await asyncio.sleep(attempt * 2)


def track_call(
    *,
    task_type: LLMCallPurpose,
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
    if not settings.observability.llm_observability_enabled:
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
