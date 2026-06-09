"""Shared LiteLLM call plumbing used by the completion helpers."""

from __future__ import annotations

import asyncio
import secrets
import threading
import time
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Literal, NoReturn

import structlog

from app.schemas.llm import ChatMessage
from app.shared.infra.settings import Settings, get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError, MissingLLMApiKeyError
from app.shared.infra.llm_support.defaults import (
    DEFAULT_LLM_CONCURRENCY_LIMIT,
    MAX_LLM_CONCURRENCY_LIMIT,
)
from app.shared.infra.llm_support.routing import (
    LLMCallProfile,
    get_task_profile,
    normalize_task_type,
)
from app.shared.infra.observability.trace import get_llm_trace_context
from app.shared.infra.observability.llm_stats import LLMCallRecord, get_tracker
from app.shared.infra.settings.support import (
    detect_llm_provider_from_base_url,
    get_llm_api_version,
    get_llm_provider_model_defaults,
    llm_provider_requires_api_key,
    normalize_llm_provider_name,
    resolve_litellm_provider_name,
    split_provider_model_name,
)

logger = structlog.get_logger()

_REQUEST_TIMEOUT_GRACE_S = 2
_LLM_LIMITER: "LLMConcurrencyLimiter | None" = None
_LLM_RUNTIME_SNAPSHOT: ContextVar["LLMRuntimeSnapshot | None"] = ContextVar(
    "llm_runtime_snapshot",
    default=None,
)
_PRIMARY_BASE_URL_ENV_NAME = "LLM_BASE_URL"
_PRIMARY_API_KEY_ENV_NAME = "LLM_API_KEY"
_PRIMARY_PROVIDER_ENV_NAME = "LLM_PROVIDER"
_FALLBACK_BASE_URL_ENV_NAME = "LLM_FALLBACK_BASE_URL"
_FALLBACK_API_KEY_ENV_NAME = "LLM_FALLBACK_API_KEY"
_SETTINGS_MODEL_SELECTORS = frozenset(
    {
        "reason",
        "primary",
        "light",
        "extract",
        "vision",
        "rerank",
        "ocr",
        "image_generation",
        "speech_to_text",
        "text_to_speech",
        "video_generation",
    }
)

EndpointRole = Literal["primary", "fallback"]


@dataclass(frozen=True)
class LLMEndpoint:
    """One resolved upstream endpoint candidate for text-generation calls."""

    role: EndpointRole
    base_url: str | None
    api_key: str | None
    provider: str
    api_version: str | None
    use_default_models: bool = False


@dataclass(frozen=True)
class LLMRuntimeSnapshot:
    """LLM-facing runtime config captured at the start of one long task."""

    settings: Settings
    base_url: str | None
    api_keys: tuple[str, ...]
    provider: str
    api_version: str | None
    primary_endpoints: tuple[LLMEndpoint, ...] = ()
    fallback_endpoints: tuple[LLMEndpoint, ...] = ()

    def choose_api_key(self) -> str | None:
        endpoint = self.choose_primary_endpoint()
        return endpoint.api_key if endpoint is not None else None

    def choose_primary_endpoint(self) -> LLMEndpoint | None:
        endpoints = self.primary_endpoints or _legacy_primary_endpoints(self)
        if not endpoints:
            return None
        first = endpoints[0]
        same_route = all(
            endpoint.base_url == first.base_url
            and endpoint.provider == first.provider
            and endpoint.api_version == first.api_version
            for endpoint in endpoints
        )
        return secrets.choice(endpoints) if same_route else first

    def completion_endpoints(self) -> tuple[LLMEndpoint, ...]:
        primary = self.primary_endpoints or _legacy_primary_endpoints(self)
        return (*primary, *self.fallback_endpoints)

    def has_usable_completion_endpoint(self) -> bool:
        for endpoint in self.completion_endpoints():
            if endpoint.api_key is not None or not llm_provider_requires_api_key(
                endpoint.provider,
                base_url=endpoint.base_url,
            ):
                return True
        return False


@dataclass(frozen=True)
class CompletionContext:
    """Resolved configuration shared by one LLM helper invocation."""

    task_type: str
    settings: Settings
    base_url: str | None
    provider: str | None
    api_version: str | None
    api_key: str | None
    profile: LLMCallProfile
    model: str
    model_selector: str
    endpoint_role: EndpointRole


@dataclass(frozen=True)
class CompletionAttempt:
    """Prepared provider call data for one retry attempt."""

    attempt: int
    started_at: float
    call_kwargs: dict[str, Any]
    call_model: str
    provider: str
    tracked_model: str


@dataclass(frozen=True, slots=True)
class _LimiterWaiter:
    """One waiter from any event loop blocked on the process LLM budget."""

    loop: asyncio.AbstractEventLoop
    future: asyncio.Future[None]


class LLMConcurrencyLimiter:
    """Async context manager enforcing the live global LLM concurrency limit."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = 0
        self._waiters: list[_LimiterWaiter] = []

    async def __aenter__(self) -> "LLMConcurrencyLimiter":
        loop = asyncio.get_running_loop()
        while True:
            waiter: _LimiterWaiter | None = None
            with self._lock:
                if self._active < get_llm_concurrency_limit():
                    self._active += 1
                    return self
                future: asyncio.Future[None] = loop.create_future()
                waiter = _LimiterWaiter(loop=loop, future=future)
                self._waiters.append(waiter)
            try:
                await asyncio.wait_for(waiter.future, timeout=0.5)
            except asyncio.TimeoutError:
                self._remove_waiter(waiter)
            except asyncio.CancelledError:
                self._remove_waiter(waiter)
                raise

    def _remove_waiter(self, waiter: _LimiterWaiter) -> None:
        with self._lock:
            try:
                self._waiters.remove(waiter)
            except ValueError:
                return

    def _release(self) -> None:
        with self._lock:
            self._active = max(0, self._active - 1)
            waiters = self._waiters
            self._waiters = []
        for waiter in waiters:
            if waiter.future.done():
                continue
            try:
                waiter.loop.call_soon_threadsafe(_wake_limiter_waiter, waiter.future)
            except RuntimeError:
                continue

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._release()


def _wake_limiter_waiter(future: asyncio.Future[None]) -> None:
    if not future.done():
        future.set_result(None)


def normalize_model_selector(value: str | None) -> str | None:
    """Normalize one settings model key or concrete provider model name."""

    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def capture_llm_runtime_snapshot() -> LLMRuntimeSnapshot:
    """Capture current LLM runtime settings for a long-running workflow."""

    return get_llm_runtime_snapshot()


def _split_env_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in str(value).split(",") if item and item.strip())


def _unique_values(raw_values: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        if not value or value in seen:
            continue
        seen.add(value)
        values.append(value)
    return tuple(values)


def _env_csv(name: str) -> tuple[str, ...]:
    return _split_env_csv(get_env(name))


def _current_api_keys() -> tuple[str, ...]:
    return _unique_values(_env_csv(_PRIMARY_API_KEY_ENV_NAME))


def _paired_endpoint_values(
    *,
    role: EndpointRole,
    base_urls: tuple[str, ...],
    api_keys: tuple[str, ...],
) -> tuple[tuple[str | None, str | None], ...]:
    """Pair comma-separated base URLs and API keys conservatively."""

    base_values: tuple[str | None, ...] = tuple(base_urls) or (None,)
    key_values: tuple[str | None, ...] = tuple(api_keys) or (None,)

    if len(base_values) == len(key_values):
        raw_pairs = zip(base_values, key_values)
    elif len(base_values) == 1:
        raw_pairs = ((base_values[0], api_key) for api_key in key_values)
    elif len(key_values) == 1:
        raw_pairs = ((base_url, key_values[0]) for base_url in base_values)
    else:
        used_count = min(len(base_values), len(key_values))
        logger.warning(
            "llm_endpoint_pair_count_mismatch",
            role=role,
            base_url_count=len(base_values),
            api_key_count=len(key_values),
            used_count=used_count,
        )
        raw_pairs = zip(base_values[:used_count], key_values[:used_count])

    pairs: list[tuple[str | None, str | None]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for raw_base_url, raw_api_key in raw_pairs:
        base_url = str(raw_base_url).strip() if raw_base_url is not None else ""
        api_key = str(raw_api_key).strip() if raw_api_key is not None else ""
        pair = (base_url or None, api_key or None)
        if pair in seen:
            continue
        seen.add(pair)
        pairs.append(pair)
    return tuple(pairs)


def _resolve_endpoint_provider(
    *,
    explicit_provider: str | None,
    base_url: str | None,
) -> str:
    provider = normalize_llm_provider_name(explicit_provider)
    if provider:
        return provider
    return detect_llm_provider_from_base_url(base_url) or "openai_compatible"


def _build_endpoint_candidates(
    *,
    role: EndpointRole,
    base_url_env_name: str,
    api_key_env_name: str,
    explicit_provider: str | None,
    api_version: str | None,
    use_default_models: bool,
) -> tuple[LLMEndpoint, ...]:
    base_urls = _env_csv(base_url_env_name)
    api_keys = _env_csv(api_key_env_name)
    if role == "fallback" and not base_urls and not api_keys:
        return ()
    pairs = _paired_endpoint_values(
        role=role,
        base_urls=base_urls,
        api_keys=api_keys,
    )
    return tuple(
        LLMEndpoint(
            role=role,
            base_url=base_url,
            api_key=api_key,
            provider=_resolve_endpoint_provider(
                explicit_provider=explicit_provider,
                base_url=base_url,
            ),
            api_version=api_version,
            use_default_models=use_default_models,
        )
        for base_url, api_key in pairs
    )


def _legacy_primary_endpoints(snapshot: LLMRuntimeSnapshot) -> tuple[LLMEndpoint, ...]:
    api_keys: tuple[str | None, ...] = snapshot.api_keys or (None,)
    return tuple(
        LLMEndpoint(
            role="primary",
            base_url=snapshot.base_url,
            api_key=api_key,
            provider=snapshot.provider,
            api_version=snapshot.api_version,
        )
        for api_key in api_keys
    )


def _settings_with_provider_default_models(settings: Settings, provider: str | None) -> Settings:
    models = settings.models.model_copy(
        update=get_llm_provider_model_defaults(provider),
        deep=True,
    )
    return settings.model_copy(update={"models": models}, deep=True)


def get_llm_runtime_snapshot() -> LLMRuntimeSnapshot:
    snapshot = _LLM_RUNTIME_SNAPSHOT.get()
    if snapshot is not None:
        return snapshot
    primary_api_version = get_llm_api_version()
    primary_endpoints = _build_endpoint_candidates(
        role="primary",
        base_url_env_name=_PRIMARY_BASE_URL_ENV_NAME,
        api_key_env_name=_PRIMARY_API_KEY_ENV_NAME,
        explicit_provider=get_env(_PRIMARY_PROVIDER_ENV_NAME),
        api_version=primary_api_version,
        use_default_models=False,
    )
    fallback_endpoints = _build_endpoint_candidates(
        role="fallback",
        base_url_env_name=_FALLBACK_BASE_URL_ENV_NAME,
        api_key_env_name=_FALLBACK_API_KEY_ENV_NAME,
        explicit_provider=None,
        api_version=primary_api_version,
        use_default_models=True,
    )
    primary_endpoint = primary_endpoints[0]
    return LLMRuntimeSnapshot(
        settings=get_settings(),
        base_url=primary_endpoint.base_url,
        api_keys=_current_api_keys(),
        provider=primary_endpoint.provider,
        api_version=primary_endpoint.api_version,
        primary_endpoints=primary_endpoints,
        fallback_endpoints=fallback_endpoints,
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

    Current project convention: business code and settings store provider
    model names directly. We infer the LiteLLM provider from either the model
    prefix or ``LLM_BASE_URL`` / ``LLM_PROVIDER`` so one shared connection entry
    can support native providers, cloud adapters, compatible gateways, and
    other major providers.
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


def resolve_task_type(task_type: object | None = None) -> str:
    """Resolve the coarse LLM task label used for fallback profiles and stats."""

    return normalize_task_type(task_type)


def _build_completion_context_for_endpoint(
    *,
    task_type: str,
    profile: LLMCallProfile,
    snapshot: LLMRuntimeSnapshot,
    endpoint: LLMEndpoint,
    model: str | None,
) -> CompletionContext:
    settings = (
        _settings_with_provider_default_models(snapshot.settings, endpoint.provider)
        if endpoint.use_default_models
        else snapshot.settings
    )
    if endpoint.api_key is None and llm_provider_requires_api_key(
        endpoint.provider,
        base_url=endpoint.base_url,
    ):
        raise MissingLLMApiKeyError(
            provider=endpoint.provider,
            base_url_configured=bool((endpoint.base_url or "").strip()),
        )
    requested_selector = normalize_model_selector(model) or "primary"
    model_for_resolution = (
        requested_selector
        if (not endpoint.use_default_models or requested_selector.lower() in _SETTINGS_MODEL_SELECTORS)
        else "primary"
    )
    resolved_model, model_selector = resolve_settings_model(settings, model_for_resolution)
    return CompletionContext(
        task_type=task_type,
        settings=settings,
        base_url=endpoint.base_url,
        provider=endpoint.provider,
        api_version=endpoint.api_version,
        api_key=endpoint.api_key,
        profile=profile,
        model=resolved_model,
        model_selector=model_selector,
        endpoint_role=endpoint.role,
    )


def build_completion_contexts(
    task_type: object | None = None,
    *,
    model: str | None = None,
) -> tuple[CompletionContext, ...]:
    """Resolve all primary and fallback endpoint contexts for one LLM call."""

    resolved_task_type = resolve_task_type(task_type)
    profile = get_task_profile(resolved_task_type)
    snapshot = get_llm_runtime_snapshot()
    contexts: list[CompletionContext] = []
    missing_key_error: MissingLLMApiKeyError | None = None

    for endpoint in snapshot.completion_endpoints():
        try:
            contexts.append(
                _build_completion_context_for_endpoint(
                    task_type=resolved_task_type,
                    profile=profile,
                    snapshot=snapshot,
                    endpoint=endpoint,
                    model=model,
                )
            )
        except MissingLLMApiKeyError as exc:
            if missing_key_error is None:
                missing_key_error = exc
            logger.warning(
                "llm_endpoint_skipped_missing_api_key",
                role=endpoint.role,
                provider=endpoint.provider,
                base_url_configured=bool((endpoint.base_url or "").strip()),
            )

    if contexts:
        return tuple(contexts)
    if missing_key_error is not None:
        raise missing_key_error
    raise MissingLLMApiKeyError(
        provider=snapshot.provider,
        base_url_configured=bool((snapshot.base_url or "").strip()),
    )


def build_completion_context(
    task_type: object | None = None,
    *,
    model: str | None = None,
) -> CompletionContext:
    """Resolve the first usable primary/fallback context for one LLM call."""

    return build_completion_contexts(task_type=task_type, model=model)[0]


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


def effective_max_retries(context: CompletionContext, call_kwargs: Mapping[str, Any] | None = None) -> int:
    """Return explicit per-call retries, falling back to the purpose profile."""

    raw_retries = (call_kwargs or {}).get("max_retries")
    if raw_retries in (None, ""):
        return context.profile.max_retries
    try:
        max_retries = int(float(raw_retries))
    except (TypeError, ValueError):
        return context.profile.max_retries
    return max(1, min(10, max_retries))


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
    remaining_kwargs.pop("max_retries", None)
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
        runtime_provider=context.provider,
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
        task_type=context.task_type,
        endpoint_role=context.endpoint_role,
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
        task_type=context.task_type,
        endpoint_role=context.endpoint_role,
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
        task_type=context.task_type,
        endpoint_role=context.endpoint_role,
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
        task_type=context.task_type,
        endpoint_role=context.endpoint_role,
        error=str(error),
        **dict(extra or {}),
        **trace_log_fields(),
    )


async def sleep_before_retry(attempt: int) -> None:
    """Apply the current linear retry backoff."""

    await asyncio.sleep(attempt * 2)


def track_call(
    *,
    task_type: object,
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
    task_label = normalize_task_type(task_type)
    record = LLMCallRecord(
        task_type=task_label,
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
