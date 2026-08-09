"""Code-owned model catalog and routing defaults."""

from __future__ import annotations

from collections.abc import Iterable
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

_RESPONSES_ROUTE_MARKERS = frozenset({"responses"})

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


def classify_known_model_api_mode(
    model: Any,
    responses_api_models: Iterable[str] = (),
) -> ModelAPIModeHint | None:
    """Return the Responses hint for configured text model names."""

    if model_is_listed(model, responses_api_models):
        return "responses"
    parts = [
        part.lower()
        for part in str(model or "").strip().replace("\\", "/").split("/")
        if part
    ]
    if any(part in _RESPONSES_ROUTE_MARKERS for part in parts[:-1]):
        return "responses"
    return None


def model_is_listed(
    model: Any,
    configured_models: Iterable[str],
) -> bool:
    """Return whether a model is explicitly listed in one configured catalog."""

    candidates = frozenset(candidate.lower() for candidate in model_name_candidates(model))
    normalized_models = frozenset(
        str(item).strip().lower()
        for item in configured_models
        if str(item).strip()
    )
    return bool(candidates & normalized_models)


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
    "ModelAPIModeHint",
    "ReasoningEffort",
    "classify_known_model_api_mode",
    "model_is_listed",
    "model_name_candidates",
    "reasoning_efforts_for_model",
]
