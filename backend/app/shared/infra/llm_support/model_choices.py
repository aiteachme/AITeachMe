"""Helpers for one-off user selected runtime models."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.shared.infra.llm_support.common import (
    LLMRuntimeSnapshot,
    get_llm_runtime_snapshot,
    use_llm_runtime_snapshot,
)

MODEL_USE_SETTINGS = "settings"
ALLOWED_RUNTIME_MODEL_OVERRIDES = frozenset(
    {
        "deepseek-v4-flash",
        "qwen3.6-flash",
        "qwen-flash",
    }
)


def normalize_runtime_model_override(value: str | None) -> str | None:
    """Return a concrete model name selected by the user, or ``None`` for settings."""

    model = str(value or "").strip()
    if not model or model == MODEL_USE_SETTINGS:
        return None
    if model not in ALLOWED_RUNTIME_MODEL_OVERRIDES:
        return None
    return model


def build_runtime_model_override_snapshot(value: str | None) -> LLMRuntimeSnapshot | None:
    """Return a snapshot where reason/primary/light all point to the selected model."""

    model = normalize_runtime_model_override(value)
    if model is None:
        return None

    snapshot = get_llm_runtime_snapshot()
    settings = snapshot.settings
    models = settings.models.model_copy(
        update={
            "reason": model,
            "primary": model,
            "light": model,
        },
    )
    return LLMRuntimeSnapshot(
        settings=settings.model_copy(update={"models": models}, deep=True),
        base_url=snapshot.base_url,
        api_keys=snapshot.api_keys,
        provider=snapshot.provider,
        api_version=snapshot.api_version,
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
    "MODEL_USE_SETTINGS",
    "build_runtime_model_override_snapshot",
    "normalize_runtime_model_override",
    "use_runtime_model_override",
]
