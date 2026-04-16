"""Task-type-based model routing helpers for the LLM layer."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from app.shared.infra.config import get_settings


class TaskType(str, Enum):
    """Supported task categories used by the model router."""

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
    """Resolved model configuration for one task category."""

    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    timeout_s: int = 60
    max_retries: int = 3


_DEFAULT_PROFILES: dict[TaskType, TaskProfile] = {
    TaskType.EXTRACT: TaskProfile(model="", temperature=0.1, timeout_s=90),
    TaskType.GENERATE: TaskProfile(model="", temperature=0.8, timeout_s=90),
    TaskType.GRADE: TaskProfile(model="", temperature=0.1, timeout_s=60),
    TaskType.CHAT: TaskProfile(model="", temperature=0.7, timeout_s=60),
    TaskType.SUMMARIZE: TaskProfile(model="", temperature=0.5, timeout_s=60),
    TaskType.CLASSIFY: TaskProfile(model="", temperature=0.1, timeout_s=30),
    TaskType.VISION: TaskProfile(model="", temperature=0.3, timeout_s=120),
    TaskType.REASONING: TaskProfile(model="", temperature=0.2, timeout_s=120, max_retries=2),
    TaskType.DOCGEN: TaskProfile(model="", temperature=0.5, timeout_s=120, max_retries=1),
    TaskType.DOCGEN_LIGHT: TaskProfile(model="", temperature=0.1, timeout_s=60, max_retries=2),
    TaskType.DEFAULT: TaskProfile(model=""),
}


def _resolve_model_for_tier(task_type: TaskType, *, tier_override: str | None = None) -> str:
    settings = get_settings()
    fallback_model = settings.llm_model

    if tier_override == "reason":
        return settings.llm_model_reason or fallback_model
    if tier_override == "primary":
        return fallback_model
    if tier_override == "light":
        if task_type is TaskType.EXTRACT:
            return settings.llm_model_extract or settings.llm_model_light or fallback_model
        return settings.llm_model_light or fallback_model
    return ""


def get_task_profile(
    task_type: TaskType = TaskType.DEFAULT,
    *,
    tier_override: str | None = None,
    model_override: str | None = None,
) -> TaskProfile:
    """Resolve the effective profile for a task type."""

    settings = get_settings()
    base = _DEFAULT_PROFILES.get(task_type, _DEFAULT_PROFILES[TaskType.DEFAULT])

    fallback_model = settings.llm_model
    override_model = model_override or settings.model_overrides.get(task_type.value)

    if not override_model and tier_override:
        override_model = _resolve_model_for_tier(task_type, tier_override=tier_override)

    if not override_model:
        # Tier-based model resolution: reason → light → primary fallback
        if task_type is TaskType.REASONING and settings.llm_model_reason:
            override_model = settings.llm_model_reason
        elif task_type in {TaskType.DOCGEN_LIGHT, TaskType.SUMMARIZE, TaskType.CLASSIFY} and settings.llm_model_light:
            override_model = settings.llm_model_light
        elif task_type is TaskType.EXTRACT:
            # EXTRACT has its own explicit slot; falls back to light tier, then primary
            override_model = settings.llm_model_extract or settings.llm_model_light

    resolved_model = override_model or base.model or fallback_model

    return replace(base, model=resolved_model)


__all__ = ["TaskProfile", "TaskType", "get_task_profile"]
