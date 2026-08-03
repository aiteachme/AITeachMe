"""Helpers for one-off user selected runtime models."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

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
    FALLBACK_RUNTIME_MODEL_OVERRIDES_SET,
)

MODEL_USE_SETTINGS = "settings"


def normalize_runtime_model_override(value: str | None) -> str | None:
    """Return a concrete model name selected by the user, or ``None`` for settings."""

    model = str(value or "").strip()
    if not model or model == MODEL_USE_SETTINGS:
        return None
    if model not in ALLOWED_RUNTIME_MODEL_OVERRIDES_SET:
        return None
    return model


def _missing_fallback_endpoint(snapshot: LLMRuntimeSnapshot) -> LLMEndpoint:
    primary_endpoint = snapshot.primary_endpoints[0] if snapshot.primary_endpoints else None
    return LLMEndpoint(
        role="fallback",
        base_url=None,
        api_key=None,
        provider="openai_compatible",
        api_version=primary_endpoint.api_version if primary_endpoint is not None else None,
    )


def build_runtime_model_override_snapshot(value: str | None) -> LLMRuntimeSnapshot | None:
    """Return a snapshot where reason/primary/light all point to the selected model."""

    model = normalize_runtime_model_override(value)
    if model is None:
        return None

    snapshot = get_llm_runtime_snapshot()
    settings = snapshot.settings
    route_via_fallback = model in FALLBACK_RUNTIME_MODEL_OVERRIDES_SET
    endpoint_candidates = (
        snapshot.fallback_endpoints if route_via_fallback else snapshot.primary_endpoints
    )
    if route_via_fallback and not endpoint_candidates:
        endpoint_candidates = (_missing_fallback_endpoint(snapshot),)
    models = settings.models.model_copy(
        update={
            "reason": model,
            "primary": model,
            "light": model,
        },
    )
    fallback_models = settings.fallback_models.model_copy(
        update={
            "reason": model,
            "primary": model,
            "light": model,
        },
    )
    return LLMRuntimeSnapshot(
        settings=settings.model_copy(
            update={"models": models, "fallback_models": fallback_models},
            deep=True,
        ),
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
    "build_runtime_model_override_snapshot",
    "normalize_runtime_model_override",
    "use_runtime_model_override",
]
