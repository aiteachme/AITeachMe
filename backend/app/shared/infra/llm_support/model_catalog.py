"""Code-owned model catalog and routing defaults."""

from __future__ import annotations

from typing import Any, Literal

ModelAPIModeHint = Literal["chat_completions", "responses"]

PRIMARY_GATEWAY_MODEL_ALLOWLIST: tuple[str, ...] = (
    "codex-auto-review",
    "gpt-4o-audio-preview",
    "gpt-4o-realtime-preview",
    "gpt-5.2",
    "gpt-5.2-2025-12-11",
    "gpt-5.2-chat-latest",
    "gpt-5.2-pro",
    "gpt-5.2-pro-2025-12-11",
    "gpt-5.3-codex",
    "gpt-5.3-codex-spark",
    "gpt-5.4",
    "gpt-5.4-2026-03-05",
    "gpt-5.4-mini",
    "gpt-5.5",
    "gpt-image-1",
    "gpt-image-1.5",
    "gpt-image-2",
)

FALLBACK_RUNTIME_MODEL_OVERRIDES: tuple[str, ...] = ("gemini-3.1-flash-lite",)

RESPONSES_API_MODELS: tuple[str, ...] = PRIMARY_GATEWAY_MODEL_ALLOWLIST
CHAT_COMPLETIONS_API_MODELS: tuple[str, ...] = FALLBACK_RUNTIME_MODEL_OVERRIDES

ALLOWED_RUNTIME_MODEL_OVERRIDES: tuple[str, ...] = (
    *PRIMARY_GATEWAY_MODEL_ALLOWLIST,
    *FALLBACK_RUNTIME_MODEL_OVERRIDES,
)

PRIMARY_GATEWAY_MODEL_ALLOWLIST_SET = frozenset(PRIMARY_GATEWAY_MODEL_ALLOWLIST)
RESPONSES_API_MODELS_SET = frozenset(RESPONSES_API_MODELS)
CHAT_COMPLETIONS_API_MODELS_SET = frozenset(CHAT_COMPLETIONS_API_MODELS)
ALLOWED_RUNTIME_MODEL_OVERRIDES_SET = frozenset(ALLOWED_RUNTIME_MODEL_OVERRIDES)

_RESPONSES_ROUTE_MARKERS = frozenset({"responses"})
_PRIMARY_GATEWAY_MODEL_ALLOWLIST_LOWER = frozenset(item.lower() for item in PRIMARY_GATEWAY_MODEL_ALLOWLIST_SET)
_RESPONSES_API_MODELS_LOWER = frozenset(item.lower() for item in RESPONSES_API_MODELS_SET)
_CHAT_COMPLETIONS_API_MODELS_LOWER = frozenset(item.lower() for item in CHAT_COMPLETIONS_API_MODELS_SET)


def model_name_candidates(model: Any) -> tuple[str, ...]:
    """Return raw and suffix model names used by LiteLLM/provider routing."""

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


def model_matches_any_name(model: Any, names: tuple[str, ...] | frozenset[str]) -> bool:
    """Return whether a model matches any exact catalog name or provider suffix."""

    allowed = frozenset(str(item or "").strip().lower() for item in names if str(item or "").strip())
    if not allowed:
        return False
    candidates = frozenset(candidate.lower() for candidate in model_name_candidates(model))
    return bool(candidates & allowed)


def is_primary_gateway_model(model: Any) -> bool:
    """Return whether the model is explicitly available on the primary gateway."""

    candidates = frozenset(candidate.lower() for candidate in model_name_candidates(model))
    return bool(candidates & _PRIMARY_GATEWAY_MODEL_ALLOWLIST_LOWER)


def classify_known_model_api_mode(model: Any) -> ModelAPIModeHint | None:
    """Return the API mode for models whose transport is code-owned."""

    candidates = frozenset(candidate.lower() for candidate in model_name_candidates(model))
    if candidates & _CHAT_COMPLETIONS_API_MODELS_LOWER:
        return "chat_completions"
    if candidates & _RESPONSES_API_MODELS_LOWER:
        return "responses"
    parts = [
        part.lower()
        for part in str(model or "").strip().replace("\\", "/").split("/")
        if part
    ]
    if any(part in _RESPONSES_ROUTE_MARKERS for part in parts[:-1]):
        return "responses"
    return None


__all__ = [
    "ALLOWED_RUNTIME_MODEL_OVERRIDES",
    "ALLOWED_RUNTIME_MODEL_OVERRIDES_SET",
    "CHAT_COMPLETIONS_API_MODELS",
    "CHAT_COMPLETIONS_API_MODELS_SET",
    "FALLBACK_RUNTIME_MODEL_OVERRIDES",
    "ModelAPIModeHint",
    "PRIMARY_GATEWAY_MODEL_ALLOWLIST",
    "PRIMARY_GATEWAY_MODEL_ALLOWLIST_SET",
    "RESPONSES_API_MODELS",
    "RESPONSES_API_MODELS_SET",
    "classify_known_model_api_mode",
    "is_primary_gateway_model",
    "model_matches_any_name",
    "model_name_candidates",
]
