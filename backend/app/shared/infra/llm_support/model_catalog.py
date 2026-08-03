"""Code-owned model catalog and routing defaults."""

from __future__ import annotations

from typing import Any, Literal

ModelAPIModeHint = Literal["responses"]
ReasoningEffort = Literal[
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
]

# Text-generation models that should prefer the Responses API in ``auto`` mode.
# Models not listed here use Chat Completions unless the caller explicitly
# requests Responses. Specialized audio, Realtime, image, and video models use
# their dedicated project integrations instead of this text adapter.
RESPONSES_API_MODELS: tuple[str, ...] = (
    "codex-auto-review",
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
    "gpt-5.4-mini-2026-03-17",
    "gpt-5.4-pro",
    "gpt-5.4-pro-2026-03-05",
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.5-pro-2026-04-23",
    "gpt-5.6",
    "gpt-5.6-luna",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
)

FALLBACK_RUNTIME_MODEL_OVERRIDES: tuple[str, ...] = ("gemini-3.1-flash-lite",)

ALLOWED_RUNTIME_MODEL_OVERRIDES: tuple[str, ...] = (
    *RESPONSES_API_MODELS,
    *FALLBACK_RUNTIME_MODEL_OVERRIDES,
)

FALLBACK_RUNTIME_MODEL_OVERRIDES_SET = frozenset(FALLBACK_RUNTIME_MODEL_OVERRIDES)
ALLOWED_RUNTIME_MODEL_OVERRIDES_SET = frozenset(ALLOWED_RUNTIME_MODEL_OVERRIDES)

_RESPONSES_ROUTE_MARKERS = frozenset({"responses"})
_RESPONSES_API_MODELS_LOWER = frozenset(item.lower() for item in RESPONSES_API_MODELS)

# The portable /v1/models response does not advertise reasoning-effort values.
# Keep verified families here so settings UI and request validation share one
# deterministic capability source; unknown gateway aliases remain configurable
# through YAML without being guessed in the UI.
_STANDARD_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    "none",
    "low",
    "medium",
    "high",
    "xhigh",
)
_CODEX_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    "low",
    "medium",
    "high",
    "xhigh",
)
_PRO_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    "medium",
    "high",
    "xhigh",
)
_MAX_REASONING_EFFORTS: tuple[ReasoningEffort, ...] = (
    "none",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)
_KNOWN_NON_REASONING_MODELS = frozenset({"gpt-5.2-chat-latest"})


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


def classify_known_model_api_mode(model: Any) -> ModelAPIModeHint | None:
    """Return the Responses hint for code-owned text model names."""

    candidates = frozenset(candidate.lower() for candidate in model_name_candidates(model))
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


def reasoning_efforts_for_model(
    model: Any,
) -> tuple[ReasoningEffort, ...] | None:
    """Return known reasoning efforts, ``()`` for known non-reasoning, or ``None`` when unknown."""

    for candidate in reversed(model_name_candidates(model)):
        normalized = candidate.lower()
        if normalized in _KNOWN_NON_REASONING_MODELS:
            return ()
        if normalized == "gpt-5.6" or normalized.startswith("gpt-5.6-"):
            return _MAX_REASONING_EFFORTS
        if normalized.startswith(("gpt-5.2-pro", "gpt-5.4-pro", "gpt-5.5-pro")):
            return _PRO_REASONING_EFFORTS
        if normalized == "gpt-5.5" or normalized.startswith("gpt-5.5-"):
            return _STANDARD_REASONING_EFFORTS
        if normalized == "gpt-5.4" or normalized.startswith("gpt-5.4-"):
            return _STANDARD_REASONING_EFFORTS
        if normalized == "gpt-5.3-codex" or normalized.startswith("gpt-5.3-codex-"):
            return _CODEX_REASONING_EFFORTS
        if normalized == "gpt-5.2" or normalized.startswith("gpt-5.2-"):
            return _STANDARD_REASONING_EFFORTS
    return None


__all__ = [
    "ALLOWED_RUNTIME_MODEL_OVERRIDES",
    "ALLOWED_RUNTIME_MODEL_OVERRIDES_SET",
    "FALLBACK_RUNTIME_MODEL_OVERRIDES",
    "FALLBACK_RUNTIME_MODEL_OVERRIDES_SET",
    "ModelAPIModeHint",
    "ReasoningEffort",
    "RESPONSES_API_MODELS",
    "classify_known_model_api_mode",
    "model_name_candidates",
    "reasoning_efforts_for_model",
]
