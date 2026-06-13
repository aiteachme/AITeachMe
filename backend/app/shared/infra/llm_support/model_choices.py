"""Helpers for one-off user selected runtime models."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace

from app.shared.infra.llm_support.common import (
    LLMEndpoint,
    LLMRuntimeSnapshot,
    get_llm_runtime_snapshot,
    use_llm_runtime_snapshot,
)
from app.shared.infra.llm_support.model_catalog import (
    ALLOWED_RUNTIME_MODEL_OVERRIDES,
    ALLOWED_RUNTIME_MODEL_OVERRIDES_SET,
    FALLBACK_RUNTIME_MODEL_OVERRIDES,
    PRIMARY_GATEWAY_MODEL_ALLOWLIST,
    PRIMARY_GATEWAY_MODEL_ALLOWLIST_SET,
)

MODEL_USE_SETTINGS = "settings"
_PRIMARY_ENDPOINT_MODEL_OVERRIDES = PRIMARY_GATEWAY_MODEL_ALLOWLIST_SET


def normalize_runtime_model_override(value: str | None) -> str | None:
    """Return a concrete model name selected by the user, or ``None`` for settings."""

    model = str(value or "").strip()
    if not model or model == MODEL_USE_SETTINGS:
        return None
    if model not in ALLOWED_RUNTIME_MODEL_OVERRIDES_SET:
        return None
    return model


def _override_endpoint(endpoint: LLMEndpoint) -> LLMEndpoint:
    return replace(endpoint, use_default_models=False)


def _missing_fallback_endpoint(snapshot: LLMRuntimeSnapshot) -> LLMEndpoint:
    return LLMEndpoint(
        role="fallback",
        base_url=None,
        api_key=None,
        provider="openai_compatible",
        api_version=snapshot.api_version,
        use_default_models=False,
    )


def build_runtime_model_override_snapshot(value: str | None) -> LLMRuntimeSnapshot | None:
    """Return a snapshot where reason/primary/light all point to the selected model."""

    model = normalize_runtime_model_override(value)
    if model is None:
        return None

    snapshot = get_llm_runtime_snapshot()
    settings = snapshot.settings
    route_via_fallback = model not in _PRIMARY_ENDPOINT_MODEL_OVERRIDES
    endpoint_candidates = tuple(
        _override_endpoint(endpoint)
        for endpoint in (snapshot.fallback_endpoints if route_via_fallback else snapshot.primary_endpoints)
    )
    if route_via_fallback and not endpoint_candidates:
        endpoint_candidates = (_missing_fallback_endpoint(snapshot),)
    selected_endpoint = endpoint_candidates[0] if endpoint_candidates else None
    models = settings.models.model_copy(
        update={
            "reason": model,
            "primary": model,
            "light": model,
        },
    )
    api_keys = tuple(endpoint.api_key for endpoint in endpoint_candidates if endpoint.api_key is not None)
    if not api_keys and not route_via_fallback:
        api_keys = snapshot.api_keys
    return LLMRuntimeSnapshot(
        settings=settings.model_copy(update={"models": models}, deep=True),
        base_url=selected_endpoint.base_url if selected_endpoint is not None else snapshot.base_url,
        api_keys=api_keys,
        provider=selected_endpoint.provider if selected_endpoint is not None else snapshot.provider,
        api_version=selected_endpoint.api_version if selected_endpoint is not None else snapshot.api_version,
        primary_endpoints=endpoint_candidates,
        fallback_endpoints=(),
    )


@contextmanager
def use_runtime_model_override(value: str | None) -> Iterator[LLMRuntimeSnapshot | None]:
    """Temporarily override reason/primary/light for one workflow run."""

    snapshot = build_runtime_model_override_snapshot(value)
    if snapshot is None:
        yield None
        return

    with use_llm_runtime_snapshot(snapshot) as active_snapshot:
        yield active_snapshot


__all__ = [
    "ALLOWED_RUNTIME_MODEL_OVERRIDES",
    "FALLBACK_RUNTIME_MODEL_OVERRIDES",
    "MODEL_USE_SETTINGS",
    "PRIMARY_GATEWAY_MODEL_ALLOWLIST",
    "build_runtime_model_override_snapshot",
    "normalize_runtime_model_override",
    "use_runtime_model_override",
]
