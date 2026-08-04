"""Helpers for one-off user selected runtime model tiers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from app.shared.infra.llm_support.common import (
    LLMRuntimeSnapshot,
    get_llm_runtime_snapshot,
    resolve_settings_model,
    use_llm_runtime_snapshot,
)

MODEL_USE_SETTINGS = "settings"
RUNTIME_MODEL_OVERRIDE_SLOTS = ("reason", "primary", "light")
_RUNTIME_MODEL_OVERRIDE_SLOT_SET = frozenset(RUNTIME_MODEL_OVERRIDE_SLOTS)


def normalize_runtime_model_override(value: str | None) -> str | None:
    """Return a user-selected model tier, or ``None`` for automatic settings."""

    selector = str(value or "").strip().lower()
    if not selector or selector == MODEL_USE_SETTINGS:
        return None
    if selector not in _RUNTIME_MODEL_OVERRIDE_SLOT_SET:
        return None
    return selector


def build_runtime_model_override_snapshot(value: str | None) -> LLMRuntimeSnapshot | None:
    """Return a snapshot where all text tiers use the selected settings tier."""

    selector = normalize_runtime_model_override(value)
    if selector is None:
        return None

    snapshot = get_llm_runtime_snapshot()
    settings = snapshot.settings
    model, _ = resolve_settings_model(settings, selector)
    fallback_model = str(getattr(settings.fallback_models, selector) or "").strip() or None
    reasoning_effort = settings.llm.reasoning_efforts.for_selector(selector)
    models = settings.models.model_copy(
        update={slot: model for slot in RUNTIME_MODEL_OVERRIDE_SLOTS},
    )
    fallback_models = settings.fallback_models.model_copy(
        update={slot: fallback_model for slot in RUNTIME_MODEL_OVERRIDE_SLOTS},
    )
    reasoning_efforts = settings.llm.reasoning_efforts.model_copy(
        update={slot: reasoning_effort for slot in RUNTIME_MODEL_OVERRIDE_SLOTS},
    )
    llm = settings.llm.model_copy(
        update={"reasoning_efforts": reasoning_efforts},
    )
    return LLMRuntimeSnapshot(
        settings=settings.model_copy(
            update={
                "models": models,
                "fallback_models": fallback_models,
                "llm": llm,
            },
            deep=True,
        ),
        primary_endpoints=snapshot.primary_endpoints,
        fallback_endpoints=snapshot.fallback_endpoints,
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
    "MODEL_USE_SETTINGS",
    "RUNTIME_MODEL_OVERRIDE_SLOTS",
    "build_runtime_model_override_snapshot",
    "normalize_runtime_model_override",
    "use_runtime_model_override",
]
