"""Shared LiteLLM call plumbing used by the completion helpers."""

from __future__ import annotations

import asyncio
import re
import secrets
import threading
import time
import weakref
from collections.abc import AsyncGenerator, Awaitable, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Iterator, Literal, NoReturn
from urllib.parse import urlparse

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
from app.shared.infra.observability.trace import get_llm_trace_context, trace_substep
from app.shared.infra.observability.llm_stats import LLMCallRecord, get_tracker
from app.shared.infra.settings.support import (
    detect_llm_provider_from_base_url,
    get_llm_api_version,
    llm_provider_requires_api_key,
    normalize_llm_provider_name,
    resolve_litellm_provider_name,
    split_provider_model_name,
)

logger = structlog.get_logger()

_REQUEST_TIMEOUT_GRACE_S = 2
_LLM_LIMITER: "LLMConcurrencyLimiter | None" = None
_LLM_LIMITER_LOCK = threading.Lock()
_LLM_RUNTIME_SNAPSHOT: ContextVar["LLMRuntimeSnapshot | None"] = ContextVar(
    "llm_runtime_snapshot",
    default=None,
)
_PRIMARY_BASE_URL_ENV_NAME = "LLM_BASE_URL"
_PRIMARY_API_KEY_ENV_NAME = "LLM_API_KEY"
_PRIMARY_PROVIDER_ENV_NAME = "LLM_PROVIDER"
_FALLBACK_BASE_URL_ENV_NAME = "LLM_FALLBACK_BASE_URL"
_FALLBACK_API_KEY_ENV_NAME = "LLM_FALLBACK_API_KEY"
_AIHUBMIX_APP_CODE_ENV_NAMES = ("AIHUBMIX_APP_CODE", "LLM_AIHUBMIX_APP_CODE")
_OPENAI_DEFAULT_SAMPLING_MODEL_PATTERN = re.compile(r"^(?:gpt-5(?:$|[.-])|o\d(?:$|[.-]))")
_OPENAI_DEFAULT_SAMPLING_PARAMS = frozenset({"temperature"})
_RESPONSES_ROUTE_MARKERS = frozenset({"responses"})
EndpointRole = Literal["primary", "fallback"]


@dataclass(frozen=True)
class LLMEndpoint:
    """One resolved upstream endpoint candidate for text-generation calls."""

    role: EndpointRole
    base_url: str | None
    api_key: str | None
    provider: str
    api_version: str | None


@dataclass(frozen=True)
class LLMRuntimeSnapshot:
    """LLM-facing runtime config captured at the start of one long task."""

    settings: Settings
    primary_endpoints: tuple[LLMEndpoint, ...]
    fallback_endpoints: tuple[LLMEndpoint, ...] = ()

    def choose_primary_endpoint(self) -> LLMEndpoint | None:
        if not self.primary_endpoints:
            return None
        return secrets.choice(self.primary_endpoints)

    def completion_endpoints(self) -> tuple[LLMEndpoint, ...]:
        primary = self.choose_primary_endpoint()
        primary_endpoints = (primary,) if primary is not None else ()
        return (*primary_endpoints, *self.fallback_endpoints)

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

    _RATE_LIMIT_COOLDOWN_S = 60.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = 0
        self._waiters: list[_LimiterWaiter] = []
        self._holders: weakref.WeakKeyDictionary[asyncio.Task[Any], int] = (
            weakref.WeakKeyDictionary()
        )
        self._rate_limit_cap: int | None = None
        self._rate_limit_until = 0.0

    async def __aenter__(self) -> "LLMConcurrencyLimiter":
        loop = asyncio.get_running_loop()
        wait_started_at = 0.0
        wait_trace_cm: Any | None = None
        wait_trace_run: Any | None = None
        while True:
            waiter: _LimiterWaiter | None = None
            acquired = False
            acquired_snapshot: dict[str, Any] | None = None
            wait_trace_snapshot: dict[str, Any] | None = None
            with self._lock:
                effective_limit = self._effective_limit_locked()
                if self._active < effective_limit:
                    self._active += 1
                    self._record_current_holder_locked()
                    acquired = True
                    if wait_trace_cm is not None:
                        acquired_snapshot = self._trace_snapshot_locked(
                            effective_limit=effective_limit,
                        )
                else:
                    if wait_trace_cm is None:
                        wait_started_at = time.monotonic()
                        wait_trace_snapshot = self._trace_snapshot_locked(
                            effective_limit=effective_limit,
                            queued_waiter=True,
                        )
                    future: asyncio.Future[None] = loop.create_future()
                    waiter = _LimiterWaiter(loop=loop, future=future)
                    self._waiters.append(waiter)
            if acquired:
                if wait_trace_cm is not None:
                    self._close_wait_trace(
                        wait_trace_cm,
                        wait_trace_run,
                        wait_started_at=wait_started_at,
                        outcome="acquired",
                        snapshot=acquired_snapshot,
                    )
                return self
            if wait_trace_snapshot is not None:
                wait_started_at = time.monotonic()
                wait_trace_cm, wait_trace_run = self._open_wait_trace(wait_trace_snapshot)
            try:
                await asyncio.wait_for(waiter.future, timeout=0.5)
            except asyncio.TimeoutError:
                self._remove_waiter(waiter)
            except asyncio.CancelledError:
                self._remove_waiter(waiter)
                if wait_trace_cm is not None:
                    self._close_wait_trace(
                        wait_trace_cm,
                        wait_trace_run,
                        wait_started_at=wait_started_at,
                        outcome="cancelled",
                    )
                raise

    def _trace_snapshot_locked(
        self,
        *,
        effective_limit: int | None = None,
        queued_waiter: bool = False,
    ) -> dict[str, Any]:
        configured_limit = get_llm_concurrency_limit()
        effective = int(effective_limit or self._effective_limit_locked())
        waiters = len(self._waiters) + (1 if queued_waiter else 0)
        cooldown_remaining_ms = int(max(0.0, self._rate_limit_until - time.monotonic()) * 1000)
        return {
            "configured_limit": configured_limit,
            "effective_limit": effective,
            "active_count": self._active,
            "waiter_count": waiters,
            "rate_limit_cap": self._rate_limit_cap or 0,
            "cooldown_remaining_ms": cooldown_remaining_ms,
        }

    def _open_wait_trace(self, snapshot: Mapping[str, Any]) -> tuple[Any | None, Any | None]:
        try:
            trace_cm = trace_substep(
                "LLM：等待并发槽",
                metadata={"substep": "llm.concurrency.wait", **dict(snapshot)},
                tags=["llm:concurrency", "llm:wait"],
                run_type="tool",
                inputs=dict(snapshot),
            )
            return trace_cm, trace_cm.__enter__()
        except Exception as exc:
            logger.warning(
                "llm_concurrency_wait_trace_start_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                **trace_log_fields(),
            )
            return None, None

    def _close_wait_trace(
        self,
        trace_cm: Any | None,
        trace_run: Any | None,
        *,
        wait_started_at: float,
        outcome: str,
        snapshot: Mapping[str, Any] | None = None,
    ) -> None:
        if trace_cm is None:
            return
        outputs = {
            **dict(snapshot or {}),
            "wait_ms": int(max(0.0, time.monotonic() - wait_started_at) * 1000),
            "outcome": outcome,
        }
        try:
            if trace_run is not None:
                trace_run.end(outputs=outputs)
        except Exception as exc:
            logger.warning(
                "llm_concurrency_wait_trace_end_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                **trace_log_fields(),
            )
        try:
            trace_cm.__exit__(None, None, None)
        except Exception as exc:
            logger.warning(
                "llm_concurrency_wait_trace_close_failed",
                error_type=type(exc).__name__,
                error=str(exc),
                **trace_log_fields(),
            )

    def _record_current_holder_locked(self) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._holders[task] = self._holders.get(task, 0) + 1

    def _drop_current_holder_locked(self) -> bool:
        task = asyncio.current_task()
        if task is None:
            return False
        depth = self._holders.get(task, 0)
        if depth <= 0:
            return False
        if depth == 1:
            self._holders.pop(task, None)
        else:
            self._holders[task] = depth - 1
        return True

    def _effective_limit_locked(self) -> int:
        configured = get_llm_concurrency_limit()
        if self._rate_limit_cap is None or time.monotonic() >= self._rate_limit_until:
            self._rate_limit_cap = None
            self._rate_limit_until = 0.0
            return configured
        return max(1, min(configured, self._rate_limit_cap))

    def note_rate_limit(self) -> None:
        """Temporarily reduce local fan-out after an upstream concurrency 429."""

        with self._lock:
            configured = get_llm_concurrency_limit()
            current_cap = self._rate_limit_cap if self._rate_limit_cap is not None else configured
            next_cap = max(1, min(configured, current_cap // 2 if current_cap > 1 else 1))
            self._rate_limit_cap = next_cap
            self._rate_limit_until = time.monotonic() + self._RATE_LIMIT_COOLDOWN_S
        logger.warning(
            "llm_concurrency_rate_limit_cooldown",
            configured_limit=configured,
            temporary_limit=next_cap,
            cooldown_s=int(self._RATE_LIMIT_COOLDOWN_S),
            **trace_log_fields(),
        )

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
        with self._lock:
            should_release = self._drop_current_holder_locked()
        if not should_release:
            return
        self._release()

    def _release_current_task_slot(self) -> bool:
        with self._lock:
            should_release = self._drop_current_holder_locked()
        if not should_release:
            return False
        self._release()
        return True

    async def sleep_without_holding_slot(self, delay_s: float) -> None:
        released = self._release_current_task_slot()
        await asyncio.sleep(delay_s)
        if released:
            await self.__aenter__()


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


def _env_csv(name: str) -> tuple[str, ...]:
    return _split_env_csv(get_env(name))


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
) -> tuple[LLMEndpoint, ...]:
    base_urls = _env_csv(base_url_env_name)
    api_keys = _env_csv(api_key_env_name)
    if role == "fallback" and not base_urls and not api_keys:
        return ()
    if role == "fallback" and api_keys and not base_urls:
        logger.warning(
            "llm_fallback_endpoint_ignored_missing_base_url",
            api_key_count=len(api_keys),
        )
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
        )
        for base_url, api_key in pairs
    )


def _settings_with_fallback_models(settings: Settings) -> Settings:
    overrides = {
        slot: normalized
        for slot in ("light", "primary", "reason")
        if (normalized := str(getattr(settings.fallback_models, slot) or "").strip())
    }
    if not overrides:
        return settings
    models = settings.models.model_copy(update=overrides, deep=True)
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
    )
    fallback_endpoints = _build_endpoint_candidates(
        role="fallback",
        base_url_env_name=_FALLBACK_BASE_URL_ENV_NAME,
        api_key_env_name=_FALLBACK_API_KEY_ENV_NAME,
        explicit_provider=None,
        api_version=primary_api_version,
    )
    return LLMRuntimeSnapshot(
        settings=get_settings(),
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
    primary_endpoint = snapshot.primary_endpoints[0] if snapshot.primary_endpoints else None
    resolved_runtime_provider = normalize_llm_provider_name(
        runtime_provider or (primary_endpoint.provider if primary_endpoint is not None else None)
    )
    routed_provider = resolved_runtime_provider
    if explicit_provider and resolved_runtime_provider != "openrouter":
        routed_provider = explicit_provider

    litellm_provider = resolve_litellm_provider_name(routed_provider)
    if not litellm_provider:
        return {}

    kwargs = {"custom_llm_provider": litellm_provider}
    if litellm_provider == "azure":
        resolved_api_version = (
            api_version
            if api_version is not None
            else (primary_endpoint.api_version if primary_endpoint is not None else None)
        )
        if resolved_api_version:
            kwargs["api_version"] = resolved_api_version
    return kwargs


def _model_name_candidates(model: Any) -> tuple[str, ...]:
    raw = str(model or "").strip()
    if not raw:
        return ()
    parts = [part for part in raw.replace("\\", "/").split("/") if part]
    candidates: list[str] = [raw]
    if parts:
        candidates.append(parts[-1])
    if len(parts) >= 2 and parts[-2].lower() in _RESPONSES_ROUTE_MARKERS:
        candidates.append(parts[-1])
    return tuple(dict.fromkeys(candidates))


def _canonical_model_name(model: Any) -> str:
    candidates = _model_name_candidates(model)
    value = candidates[-1] if candidates else ""
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _uses_openai_sampling_contract(
    context: CompletionContext,
    call_kwargs: Mapping[str, Any],
) -> bool:
    provider = normalize_llm_provider_name(context.provider)
    custom_provider = normalize_llm_provider_name(
        str(call_kwargs.get("custom_llm_provider") or "") or None
    )
    if provider in {"openai", "openai_compatible", "azure"}:
        return True
    if custom_provider in {"openai", "azure"}:
        return True
    api_base = str(call_kwargs.get("api_base") or context.base_url or "").lower()
    return "api.openai.com" in api_base or "openai.azure.com" in api_base


def _uses_default_sampling_model(model: Any) -> bool:
    return bool(_OPENAI_DEFAULT_SAMPLING_MODEL_PATTERN.match(_canonical_model_name(model)))


def _drop_unsupported_sampling_params(
    *,
    context: CompletionContext,
    call_kwargs: dict[str, Any],
) -> None:
    if not _uses_openai_sampling_contract(context, call_kwargs):
        return
    if not _uses_default_sampling_model(call_kwargs.get("model")):
        return
    dropped = [key for key in _OPENAI_DEFAULT_SAMPLING_PARAMS if key in call_kwargs]
    if not dropped:
        return
    for key in dropped:
        call_kwargs.pop(key, None)
    logger.debug(
        "llm_completion_sampling_params_dropped",
        model=call_kwargs.get("model"),
        provider=context.provider,
        dropped_params=sorted(dropped),
    )


def _is_aihubmix_base_url(base_url: str | None) -> bool:
    parsed = urlparse(str(base_url or "").strip())
    host = (parsed.hostname or "").lower()
    return host == "aihubmix.com" or host.endswith(".aihubmix.com")


def _aihubmix_app_code() -> str | None:
    for env_name in _AIHUBMIX_APP_CODE_ENV_NAMES:
        value = (get_env(env_name) or "").strip()
        if value:
            return value
    return None


def build_provider_extra_headers(api_base: str | None) -> dict[str, str]:
    """Return optional provider-specific request headers for LiteLLM calls."""

    if not _is_aihubmix_base_url(api_base):
        return {}
    app_code = _aihubmix_app_code()
    if not app_code:
        return {}
    return {"APP-Code": app_code}


def apply_provider_extra_headers(call_kwargs: dict[str, Any]) -> None:
    """Merge provider-specific headers without overwriting explicit caller headers."""

    headers = build_provider_extra_headers(str(call_kwargs.get("api_base") or ""))
    if not headers:
        return
    existing = call_kwargs.get("extra_headers")
    if isinstance(existing, Mapping):
        call_kwargs["extra_headers"] = {**headers, **dict(existing)}
        return
    call_kwargs["extra_headers"] = headers


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
        _settings_with_fallback_models(snapshot.settings)
        if endpoint.role == "fallback"
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
    resolved_model, model_selector = resolve_settings_model(settings, requested_selector)
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
            context = _build_completion_context_for_endpoint(
                task_type=resolved_task_type,
                profile=profile,
                snapshot=snapshot,
                endpoint=endpoint,
                model=model,
            )
            contexts.append(context)
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
    primary_endpoint = snapshot.primary_endpoints[0] if snapshot.primary_endpoints else None
    raise MissingLLMApiKeyError(
        provider=primary_endpoint.provider if primary_endpoint is not None else None,
        base_url_configured=(
            bool((primary_endpoint.base_url or "").strip())
            if primary_endpoint is not None
            else False
        ),
    )


def completion_context_groups(contexts: tuple[CompletionContext, ...]) -> tuple[tuple[CompletionContext, ...], ...]:
    """Group endpoint attempts so primary routes exhaust before fallback routes."""

    primary = tuple(context for context in contexts if context.endpoint_role == "primary")
    fallback = tuple(context for context in contexts if context.endpoint_role == "fallback")
    return tuple(group for group in (primary, fallback) if group)


_ENDPOINT_FALLBACK_ERROR_NAME_MARKERS = (
    "Authentication",
    "Permission",
    "RateLimit",
    "APIConnection",
    "APIError",
    "APITimeout",
    "Timeout",
    "HTTPStatus",
    "ServiceUnavailable",
    "InternalServer",
)
_ENDPOINT_FALLBACK_MESSAGE_MARKERS = (
    "connection",
    "connect",
    "timeout",
    "timed out",
    "rate limit",
    "unauthorized",
    "forbidden",
    "bad gateway",
    "service unavailable",
    "internal server",
    "gateway down",
    "gateway unavailable",
    "primary unavailable",
    "primary gateway down",
    "primary stream down",
)
_CONCURRENCY_RATE_LIMIT_MARKERS = (
    "concurrency limit exceeded",
    "concurrent limit exceeded",
    "too many concurrent",
    "too many simultaneous",
    "requests-per-minute limit exceeded",
    "request per minute limit exceeded",
    "rate limit exceeded",
    "rate_limit_exceeded",
    "rate_limit_error",
    "too many requests",
)


def is_concurrency_rate_limit_error(error: Exception | None) -> bool:
    """Return whether an error is an upstream concurrent-request quota hit."""

    if error is None:
        return False
    message = str(error).lower()
    return any(marker in message for marker in _CONCURRENCY_RATE_LIMIT_MARKERS)


def should_try_endpoint_fallback(error: Exception | None) -> bool:
    """Return whether a failed primary attempt should advance to fallback endpoints."""

    if error is None:
        return False
    if is_concurrency_rate_limit_error(error):
        return False
    if isinstance(error, LLMTimeoutError):
        return True
    message = str(error).lower()
    if "empty_llm_response" in message:
        return False
    error_name = error.__class__.__name__
    if any(marker in error_name for marker in _ENDPOINT_FALLBACK_ERROR_NAME_MARKERS):
        return True
    return any(marker in message for marker in _ENDPOINT_FALLBACK_MESSAGE_MARKERS)


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


def effective_endpoint_group_max_retries(
    context: CompletionContext,
    call_kwargs: Mapping[str, Any] | None = None,
) -> int:
    """Cap fallback endpoint retries so an unhealthy backup gateway cannot occupy LLM slots for minutes."""

    max_retries = effective_max_retries(context, call_kwargs)
    if context.endpoint_role == "fallback":
        return 1
    return max_retries


def pop_overall_timeout_s(call_kwargs: dict[str, Any]) -> float | None:
    """Remove and parse the optional whole-call timeout budget."""

    raw_timeout = call_kwargs.pop("overall_timeout_s", None)
    if raw_timeout in (None, ""):
        return None
    try:
        timeout_s = float(raw_timeout)
    except (TypeError, ValueError):
        return None
    return timeout_s if timeout_s > 0 else None


async def wait_for_overall_timeout(awaitable: Awaitable[Any], timeout_s: float | None) -> Any:
    """Apply an optional timeout to a whole helper call."""

    if timeout_s is None:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        raise LLMTimeoutError(timeout_s=int(timeout_s)) from exc


async def iter_with_overall_timeout(
    stream: AsyncGenerator[Any, None],
    timeout_s: float | None,
) -> AsyncGenerator[Any, None]:
    """Yield a stream while bounding the total stream lifetime."""

    try:
        if timeout_s is None:
            async for chunk in stream:
                yield chunk
            return

        deadline = time.monotonic() + timeout_s
        while True:
            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                raise asyncio.TimeoutError
            try:
                yield await asyncio.wait_for(stream.__anext__(), timeout=remaining_s)
            except StopAsyncIteration:
                break
    except asyncio.TimeoutError as exc:
        raise LLMTimeoutError(timeout_s=int(timeout_s)) from exc
    finally:
        await stream.aclose()


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
        with _LLM_LIMITER_LOCK:
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
    apply_provider_extra_headers(completion_kwargs)
    _drop_unsupported_sampling_params(
        context=context,
        call_kwargs=completion_kwargs,
    )
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
    if is_concurrency_rate_limit_error(error):
        get_llm_concurrency_limiter().note_rate_limit()


async def sleep_before_retry(attempt: int, *, error: Exception | None = None) -> None:
    """Apply the current linear retry backoff."""

    delay_s = min(30, attempt * 8) if is_concurrency_rate_limit_error(error) else attempt * 2
    limiter = _LLM_LIMITER
    if limiter is None:
        await asyncio.sleep(delay_s)
        return
    await limiter.sleep_without_holding_slot(delay_s)


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
