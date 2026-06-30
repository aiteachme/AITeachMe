"""Task-type profiles for the LLM layer.

Model names are resolved from ``settings.models`` in ``llm_support.common``.
This module does not route models or sampling behavior. It only keeps
observability labels and operational defaults such as timeout/retry budgets.
Workflow lanes should pass concrete model-policy kwargs for prompt-sensitive
and runtime-sensitive values such as ``temperature``, ``max_tokens``,
``timeout`` and ``max_retries``.

``TaskType`` is kept as a lightweight constants namespace for compatibility
and coarse observability. Workflow model policies should not rely on it for
request budgets.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.shared.infra.env_support import get_env


class TaskType:
    """String constants used for coarse LLM observability labels."""

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
    EMBEDDING = "embedding"
    IMAGE_GENERATION = "image_generation"
    DEFAULT = "default"


@dataclass(frozen=True)
class LLMCallProfile:
    """Non-model call defaults for one task type."""

    timeout_s: int = 60
    max_retries: int = 3


_DEFAULT_PROFILES: dict[str, LLMCallProfile] = {
    TaskType.EXTRACT: LLMCallProfile(timeout_s=300, max_retries=3),
    TaskType.GENERATE: LLMCallProfile(timeout_s=300, max_retries=3),
    TaskType.GRADE: LLMCallProfile(timeout_s=180, max_retries=3),
    TaskType.CHAT: LLMCallProfile(timeout_s=240, max_retries=3),
    TaskType.SUMMARIZE: LLMCallProfile(timeout_s=240, max_retries=3),
    TaskType.CLASSIFY: LLMCallProfile(timeout_s=120, max_retries=3),
    TaskType.VISION: LLMCallProfile(timeout_s=480, max_retries=3),
    TaskType.REASONING: LLMCallProfile(timeout_s=480, max_retries=3),
    TaskType.DOCGEN: LLMCallProfile(timeout_s=600, max_retries=3),
    TaskType.DOCGEN_LIGHT: LLMCallProfile(timeout_s=480, max_retries=3),
    TaskType.EMBEDDING: LLMCallProfile(timeout_s=120, max_retries=1),
    TaskType.IMAGE_GENERATION: LLMCallProfile(timeout_s=600, max_retries=3),
    TaskType.DEFAULT: LLMCallProfile(timeout_s=240, max_retries=3),
}


def normalize_task_type(task_type: object | None = None) -> str:
    value = getattr(task_type, "value", task_type)
    normalized = str(value or "").strip().lower()
    return normalized or TaskType.DEFAULT


def _task_env_key(task_type: str) -> str:
    return normalize_task_type(task_type).upper()


def _bounded_env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw_value = get_env(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return min(max(value, min_value), max_value)


def _apply_env_overrides(task_type: str, profile: LLMCallProfile) -> LLMCallProfile:
    """Allow ops to tune timeout/retry budgets without editing project settings."""

    key = _task_env_key(task_type)
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


def get_task_profile(task_type: object | None = None) -> LLMCallProfile:
    """Return call defaults for a coarse task type."""

    resolved = normalize_task_type(task_type)
    profile = _DEFAULT_PROFILES.get(resolved, _DEFAULT_PROFILES[TaskType.DEFAULT])
    return _apply_env_overrides(resolved, profile)


TaskProfile = LLMCallProfile


__all__ = [
    "LLMCallProfile",
    "TaskProfile",
    "TaskType",
    "get_task_profile",
    "normalize_task_type",
]
