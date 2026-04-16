"""Task call profiles for the LLM layer.

Model names are resolved from ``settings.models`` in ``llm_support.common``.
This module only keeps task labels and non-model call defaults such as
temperature, timeout, and retry count.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TaskType(str, Enum):
    """Supported task categories used for call profile and observability."""

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
    DEFAULT = "default"


@dataclass(frozen=True)
class TaskProfile:
    """Non-model call defaults for one task category."""

    temperature: float = 0.7
    max_tokens: int | None = None
    timeout_s: int = 60
    max_retries: int = 3


_DEFAULT_PROFILES: dict[TaskType, TaskProfile] = {
    TaskType.EXTRACT: TaskProfile(temperature=0.1, timeout_s=90),
    TaskType.GENERATE: TaskProfile(temperature=0.8, timeout_s=90),
    TaskType.GRADE: TaskProfile(temperature=0.1, timeout_s=60),
    TaskType.CHAT: TaskProfile(temperature=0.7, timeout_s=60),
    TaskType.SUMMARIZE: TaskProfile(temperature=0.5, timeout_s=60),
    TaskType.CLASSIFY: TaskProfile(temperature=0.1, timeout_s=30),
    TaskType.VISION: TaskProfile(temperature=0.3, timeout_s=120),
    TaskType.REASONING: TaskProfile(temperature=0.2, timeout_s=120, max_retries=2),
    TaskType.DOCGEN: TaskProfile(temperature=0.5, timeout_s=120, max_retries=1),
    TaskType.DOCGEN_LIGHT: TaskProfile(temperature=0.1, timeout_s=60, max_retries=2),
    TaskType.DEFAULT: TaskProfile(),
}


def get_task_profile(task_type: TaskType = TaskType.DEFAULT) -> TaskProfile:
    """Return call defaults for a task type."""

    return _DEFAULT_PROFILES.get(task_type, _DEFAULT_PROFILES[TaskType.DEFAULT])


__all__ = [
    "TaskProfile",
    "TaskType",
    "get_task_profile",
]
