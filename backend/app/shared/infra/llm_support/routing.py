"""Call-purpose profiles for the LLM layer.

Model names are resolved from ``settings.models`` in ``llm_support.common``.
This module does not route models or sampling behavior. It only keeps
observability labels and operational defaults such as timeout/retry budgets.
Workflow lanes should pass concrete model-policy kwargs for prompt-sensitive
values such as ``temperature`` and ``max_tokens``.

``TaskType`` is kept as a compatibility alias for older call sites. New code
should prefer ``LLMCallPurpose`` / ``call_purpose=`` so it is clear that model
selection still comes from the explicit ``model=`` argument.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from app.shared.infra.env_support import get_env


class LLMCallPurpose(str, Enum):
    """Supported call purposes used for profile defaults and observability."""

    EXTRACT = "extract"
    GENERATE = "generate"
    GRADE = "grade"
    CHAT = "chat"
    SUMMARIZE = "summarize"
    CLASSIFY = "classify"
    VISION = "vision"
    REASONING = "reasoning"
    DOCGEN = "docgen"
    DOCGEN_LIGHT = "docgen_light"
    IMAGE_GENERATION = "image_generation"
    DEFAULT = "default"


@dataclass(frozen=True)
class LLMCallProfile:
    """Non-model call defaults for one call purpose."""

    timeout_s: int = 60
    max_retries: int = 3


_DEFAULT_PROFILES: dict[LLMCallPurpose, LLMCallProfile] = {
    LLMCallPurpose.EXTRACT: LLMCallProfile(timeout_s=300, max_retries=3),
    LLMCallPurpose.GENERATE: LLMCallProfile(timeout_s=300, max_retries=3),
    LLMCallPurpose.GRADE: LLMCallProfile(timeout_s=180, max_retries=3),
    LLMCallPurpose.CHAT: LLMCallProfile(timeout_s=240, max_retries=3),
    LLMCallPurpose.SUMMARIZE: LLMCallProfile(timeout_s=240, max_retries=3),
    LLMCallPurpose.CLASSIFY: LLMCallProfile(timeout_s=120, max_retries=3),
    LLMCallPurpose.VISION: LLMCallProfile(timeout_s=480, max_retries=3),
    LLMCallPurpose.REASONING: LLMCallProfile(timeout_s=480, max_retries=3),
    LLMCallPurpose.DOCGEN: LLMCallProfile(timeout_s=600, max_retries=3),
    LLMCallPurpose.DOCGEN_LIGHT: LLMCallProfile(timeout_s=480, max_retries=3),
    LLMCallPurpose.IMAGE_GENERATION: LLMCallProfile(timeout_s=600, max_retries=3),
    LLMCallPurpose.DEFAULT: LLMCallProfile(timeout_s=240, max_retries=3),
}


def _purpose_env_key(call_purpose: LLMCallPurpose) -> str:
    return call_purpose.value.upper()


def _bounded_env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw_value = get_env(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return min(max(value, min_value), max_value)


def _apply_env_overrides(call_purpose: LLMCallPurpose, profile: LLMCallProfile) -> LLMCallProfile:
    """Allow ops to tune timeout/retry budgets without editing project settings."""

    key = _purpose_env_key(call_purpose)
    timeout_s = _bounded_env_int(
        f"LLM_TIMEOUT_{key}_S",
        profile.timeout_s,
        min_value=5,
        max_value=1800,
    )
    max_retries = _bounded_env_int(
        f"LLM_MAX_RETRIES_{key}",
        profile.max_retries,
        min_value=1,
        max_value=10,
    )
    if timeout_s == profile.timeout_s and max_retries == profile.max_retries:
        return profile
    return replace(profile, timeout_s=timeout_s, max_retries=max_retries)


def get_call_profile(call_purpose: LLMCallPurpose = LLMCallPurpose.DEFAULT) -> LLMCallProfile:
    """Return call defaults for a call purpose."""

    profile = _DEFAULT_PROFILES.get(call_purpose, _DEFAULT_PROFILES[LLMCallPurpose.DEFAULT])
    return _apply_env_overrides(call_purpose, profile)


# Backward-compatible names. They are aliases, not separate concepts.
TaskType = LLMCallPurpose
TaskProfile = LLMCallProfile


def get_task_profile(task_type: TaskType = TaskType.DEFAULT) -> TaskProfile:
    """Compatibility wrapper for older ``task_type=`` call sites."""

    return get_call_profile(task_type)


__all__ = [
    "LLMCallProfile",
    "LLMCallPurpose",
    "TaskProfile",
    "TaskType",
    "get_call_profile",
    "get_task_profile",
]
