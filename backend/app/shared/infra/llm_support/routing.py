"""Call-purpose profiles for the LLM layer.

Model names are resolved from ``settings.models`` in ``llm_support.common``.
This module does not route models. It only keeps observability labels and
non-model defaults. A call site should only pass an explicit kwarg when it
needs to override the profile for that specific prompt.

``TaskType`` is kept as a compatibility alias for older call sites. New code
should prefer ``LLMCallPurpose`` / ``call_purpose=`` so it is clear that model
selection still comes from the explicit ``model=`` argument.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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

    temperature: float = 0.7
    max_tokens: int | None = None
    timeout_s: int = 60
    max_retries: int = 3


_DEFAULT_PROFILES: dict[LLMCallPurpose, LLMCallProfile] = {
    LLMCallPurpose.EXTRACT: LLMCallProfile(temperature=0.1, timeout_s=90),
    LLMCallPurpose.GENERATE: LLMCallProfile(temperature=0.2, timeout_s=90),
    LLMCallPurpose.GRADE: LLMCallProfile(temperature=0.1, timeout_s=60),
    LLMCallPurpose.CHAT: LLMCallProfile(temperature=0.7, timeout_s=60),
    LLMCallPurpose.SUMMARIZE: LLMCallProfile(temperature=0.5, timeout_s=60),
    LLMCallPurpose.CLASSIFY: LLMCallProfile(temperature=0.1, timeout_s=30),
    LLMCallPurpose.VISION: LLMCallProfile(temperature=0.3, timeout_s=120),
    LLMCallPurpose.REASONING: LLMCallProfile(temperature=0.2, timeout_s=180, max_retries=2),
    LLMCallPurpose.DOCGEN: LLMCallProfile(temperature=0.5, timeout_s=180, max_retries=1),
    LLMCallPurpose.DOCGEN_LIGHT: LLMCallProfile(temperature=0.1, timeout_s=120, max_retries=2),
    LLMCallPurpose.IMAGE_GENERATION: LLMCallProfile(temperature=0.7, timeout_s=180, max_retries=1),
    LLMCallPurpose.DEFAULT: LLMCallProfile(),
}


def get_call_profile(call_purpose: LLMCallPurpose = LLMCallPurpose.DEFAULT) -> LLMCallProfile:
    """Return call defaults for a call purpose."""

    return _DEFAULT_PROFILES.get(call_purpose, _DEFAULT_PROFILES[LLMCallPurpose.DEFAULT])


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
