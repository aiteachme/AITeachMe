"""Shared LiteLLM call plumbing used by the completion helpers."""

from __future__ import annotations

import asyncio
import secrets
import time
import weakref
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, NoReturn

import structlog

from app.schemas.llm import ChatMessage
from app.shared.infra.settings import Settings, get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError, MissingLLMApiKeyError
from app.shared.infra.llm_support.defaults import (
    DEFAULT_LLM_CONCURRENCY_LIMIT,
    MAX_LLM_CONCURRENCY_LIMIT,
)
from app.shared.infra.llm_support.routing import LLMCallProfile, LLMCallPurpose, get_call_profile
from app.shared.infra.observability.trace import get_llm_trace_context
from app.shared.infra.observability.llm_stats import LLMCallRecord, get_tracker
from app.shared.infra.settings.support import (
    get_llm_api_version,
    llm_provider_requires_api_key,
    normalize_llm_provider_name,
    resolve_litellm_provider_name,
    resolve_runtime_llm_provider,
    split_provider_model_name,
)

logger = structlog.get_logger()

_REQUEST_TIMEOUT_GRACE_S = 2
_LLM_LIMITER: "LLMConcurrencyLimiter | None" = None
_LLM_RUNTIME_SNAPSHOT: ContextVar["LLMRuntimeSnapshot | None"] = ContextVar(
    "llm_runtime_snapshot",
    default=None,
)


@dataclass(frozen=True)
class LLMRuntimeSnapshot:
    """LLM-facing runtime config captured at the start of one long task."""

    settings: Settings
    base_url: str | None
    api_keys: tuple[str, ...]
    provider: str
    api_version: str | None

    def choose_api_key(self) -> str | None:
        return secrets.choice(self.api_keys) if self.api_keys else None


@dataclass(frozen=True)
class CompletionContext:
    """Resolved configuration shared by one LLM helper invocation."""

    call_purpose: LLMCallPurpose
    settings: Settings
    base_url: str | None
    provider: str | None
    api_version: str | None
    api_key: str | None
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


@dataclass(slots=True)
class _LimiterState:
    """Loop-local limiter state so tests and servers can use distinct loops."""

    changed: asyncio.Event
    active: int = 0


class LLMConcurrencyLimiter:
    """Async context manager enforcing the live global LLM concurrency limit."""

    def __init__(self) -> None:
        self._states: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, _LimiterState]" = (
            weakref.WeakKeyDictionary()
        )

    def _state(self) -> _LimiterState:
        loop = asyncio.get_running_loop()
        state = self._states.get(loop)
        if state is None:
            state = _LimiterState(changed=asyncio.Event())
            self._states[loop] = state
        return state

    async def __aenter__(self) -> "LLMConcurrencyLimiter":
        state = self._state()
        while state.active >= get_llm_concurrency_limit():
            try:
                await asyncio.wait_for(state.changed.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass
        state.active += 1
        return self

    def _release(self, state: _LimiterState) -> None:
        state.active = max(0, state.active - 1)
        state.changed.set()
        state.changed = asyncio.Event()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._release(self._state())


def normalize_model_selector(value: str | None) -> str | None:
    """Normalize one settings model key or concrete provider model name."""

    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def capture_llm_runtime_snapshot() -> LLMRuntimeSnapshot:
    """Capture current LLM runtime settings for a long-running workflow."""

    return get_llm_runtime_snapshot()


def _current_api_keys() -> tuple[str, ...]:
    raw_value = get_env("LLM_API_KEY") or ""
    values: list[str] = []
    seen: set[str] = set()
    for item in raw_value.split(","):
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return tuple(values)


def get_llm_runtime_snapshot() -> LLMRuntimeSnapshot:
    snapshot = _LLM_RUNTIME_SNAPSHOT.get()
    if snapshot is not None:
        return snapshot
    base_url = get_env("LLM_BASE_URL")
    explicit_provider = get_env("LLM_PROVIDER")
    return LLMRuntimeSnapshot(
        settings=get_settings(),
        base_url=base_url,
        api_keys=_current_api_keys(),
        provider=resolve_runtime_llm_provider(
            explicit_provider=explicit_provider,
            base_url=base_url,
        ),
        api_version=get_llm_api_version(),
    )


@contextmanager
def use_llm_runtime_snapshot(snapshot: LLMRuntimeSnapshot | None = None) -> Iterator[LLMRuntimeSnapshot]:
    """Freeze LLM-facing runtime config for work started inside the context."""

    resolved = snapshot or get_llm_runtime_snapshot()
    token = _LLM_RUNTIME_SNAPSHOT.set(resolved)
    try:
        yield resolved
    finally:
        _LLM_RUNTIME_SNAPSHOT.reset(token)


def build_litellm_provider_kwargs(
    model: str | None,
    *,
    runtime_provider: str | None = None,
    api_version: str | None = None,
) -> dict[str, str]:
    """Infer LiteLLM provider kwargs while keeping raw model names in app code.

    Current project convention: business code and settings store plain model
    names such as ``gpt-4o-mini`` or ``claude-3-5-sonnet-latest``. We infer
    the LiteLLM provider from either the model prefix or ``LLM_BASE_URL`` /
    ``LLM_PROVIDER`` so one shared connection entry can support Anthropic,
    Gemini, Azure, OpenAI-compatible gateways and other major providers.
    """

    normalized = normalize_model_selector(model)
    if not normalized:
        return {}
    explicit_provider, _model_name = split_provider_model_name(normalized)
    snapshot = get_llm_runtime_snapshot()
    resolved_runtime_provider = normalize_llm_provider_name(runtime_provider or snapshot.provider)
    routed_provider = resolved_runtime_provider
    if explicit_provider and resolved_runtime_provider != "openrouter":
        routed_provider = explicit_provider

    litellm_provider = resolve_litellm_provider_name(routed_provider)
    if not litellm_provider:
        return {}

    kwargs = {"custom_llm_provider": litellm_provider}
    if litellm_provider == "azure":
        resolved_api_version = api_version if api_version is not None else snapshot.api_version
        if resolved_api_version:
            kwargs["api_version"] = resolved_api_version
    return kwargs


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
        return models.light or fallback_model, "extract"
    if normalized == "vision":
        return models.vision or fallback_model, "vision"
    if normalized == "rerank":
        return models.rerank or fallback_model, "rerank"
    if normalized == "ocr":
        return models.ocr or fallback_model, "ocr"
    if normalized == "image_generation":
        return models.image_generation or fallback_model, "image_generation"
    if normalized == "speech_to_text":
        return models.speech_to_text or fallback_model, "speech_to_text"
    if normalized == "text_to_speech":
        return models.text_to_speech or fallback_model, "text_to_speech"
    if normalized == "video_generation":
        return models.video_generation or fallback_model, "video_generation"
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
    snapshot = get_llm_runtime_snapshot()
    settings = snapshot.settings
    base_url = snapshot.base_url
    provider = snapshot.provider
    api_key = snapshot.choose_api_key()
    if api_key is None and llm_provider_requires_api_key(provider, base_url=base_url):
        raise MissingLLMApiKeyError(
            provider=provider,
            base_url_configured=bool((base_url or "").strip()),
        )
    resolved_model, model_selector = resolve_settings_model(settings, model)
    return CompletionContext(
        call_purpose=resolved_purpose,
        settings=settings,
        base_url=base_url,
        provider=provider,
        api_version=snapshot.api_version,
        api_key=api_key,
        profile=get_call_profile(resolved_purpose),
        model=resolved_model,
        model_selector=model_selector,
    )


def request_timeout_s(timeout_s: int, *, enabled: bool = True) -> int | None:
    """Apply a small grace window around provider-side timeouts."""

    if not enabled:
        return None
    return int(timeout_s) + _REQUEST_TIMEOUT_GRACE_S


def should_enforce_request_timeout(context: CompletionContext) -> bool:
    return bool(context.settings.llm.enforce_request_timeout)


def effective_call_timeout_s(context: CompletionContext, call_kwargs: Mapping[str, Any] | None = None) -> int:
    raw_timeout = (call_kwargs or {}).get("timeout")
    if raw_timeout in (None, ""):
        return context.profile.timeout_s
    try:
        timeout_s = int(float(raw_timeout))
    except (TypeError, ValueError):
        return context.profile.timeout_s
    return timeout_s if timeout_s > 0 else context.profile.timeout_s


def context_request_timeout_s(
    context: CompletionContext,
    call_kwargs: Mapping[str, Any] | None = None,
) -> int | None:
    return request_timeout_s(
        effective_call_timeout_s(context, call_kwargs),
        enabled=should_enforce_request_timeout(context),
    )


def get_llm_concurrency_limit() -> int:
    """Return the process-wide LLM concurrency limit from runtime settings."""

    try:
        value = int(get_settings().llm.concurrency_limit or DEFAULT_LLM_CONCURRENCY_LIMIT)
    except Exception:
        value = DEFAULT_LLM_CONCURRENCY_LIMIT
    return max(1, min(MAX_LLM_CONCURRENCY_LIMIT, value))


def get_llm_concurrency_limiter() -> LLMConcurrencyLimiter:
    """Return the shared adaptive limiter for all LLM helper calls."""

    global _LLM_LIMITER
    if _LLM_LIMITER is None:
        _LLM_LIMITER = LLMConcurrencyLimiter()
    return _LLM_LIMITER


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
    if trace.course_id:
        fields["course_id"] = trace.course_id
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
    }
    temperature = remaining_kwargs.pop("temperature", None)
    if temperature is not None:
        completion_kwargs["temperature"] = temperature
    if should_enforce_request_timeout(context):
        completion_kwargs["timeout"] = context.profile.timeout_s
    api_base = context.base_url
    if api_base:
        completion_kwargs["api_base"] = api_base
    if context.api_key is not None:
        completion_kwargs["api_key"] = context.api_key
    completion_kwargs.update(
        build_litellm_provider_kwargs(
            context.model,
            runtime_provider=context.provider,
            api_version=context.api_version,
        )
    )
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
        timeout_s=effective_call_timeout_s(context, attempt.call_kwargs),
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
        timeout_s=effective_call_timeout_s(context, attempt.call_kwargs),
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

    settings = get_llm_runtime_snapshot().settings
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
        course_id=trace_context.course_id,
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
