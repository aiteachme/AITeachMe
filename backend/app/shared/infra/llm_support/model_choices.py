"""Helpers for one-off user selected runtime models."""

from __future__ import annotations

MODEL_USE_SETTINGS = "settings"
ALLOWED_RUNTIME_MODEL_OVERRIDES = frozenset(
    {
        "deepseek-v4-flash",
        "qwen3.6-flash",
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


def resolve_runtime_model_selector(value: str | None, *, default_selector: str) -> str:
    """Resolve a request model value into the selector passed to LLM support."""

    return normalize_runtime_model_override(value) or default_selector


__all__ = [
    "ALLOWED_RUNTIME_MODEL_OVERRIDES",
    "MODEL_USE_SETTINGS",
    "normalize_runtime_model_override",
    "resolve_runtime_model_selector",
]
