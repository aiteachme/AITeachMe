"""Task-type-based model routing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.shared.infra.config import get_settings


class TaskType(str, Enum):
    """Supported task categories used by the model router."""

    EXTRACT = "extract"  # Digest extraction requiring higher precision.
    GENERATE = "generate"  # Examine question generation requiring creativity.
    GRADE = "grade"  # Examine grading and answer evaluation.
    CHAT = "chat"  # Interactive chat responses.
    SUMMARIZE = "summarize"  # Profile and report summarization.
    CLASSIFY = "classify"  # Ingest classification tasks.
    VISION = "vision"  # OCR and multimodal parsing tasks.
    REASONING = "reasoning"  # Longer reasoning-heavy tasks.
    DOCGEN = "docgen"  # Chapter drafting and outline generation.
    DOCGEN_LIGHT = "docgen_light"  # Lightweight docgen cleanup or labeling.
    DEFAULT = "default"  # Fallback path.


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


def get_task_profile(task_type: TaskType = TaskType.DEFAULT) -> TaskProfile:
    """Resolve the effective profile for a task type.

    Priority:
    1. ``settings.model_overrides``
    2. task-specific lightweight or extraction model shortcuts
    3. the global ``settings.llm_model`` fallback
    """

    settings = get_settings()
    base = _DEFAULT_PROFILES.get(task_type, _DEFAULT_PROFILES[TaskType.DEFAULT])

    fallback_model = settings.llm_model
    override_model = settings.model_overrides.get(task_type.value)

    if not override_model:
        if task_type is TaskType.DOCGEN_LIGHT and settings.llm_model_light:
            override_model = settings.llm_model_light
        elif task_type is TaskType.EXTRACT and settings.llm_model_extract:
            override_model = settings.llm_model_extract

    resolved_model = override_model or base.model or fallback_model

    return TaskProfile(
        model=resolved_model,
        temperature=base.temperature,
        max_tokens=base.max_tokens,
        timeout_s=base.timeout_s,
        max_retries=base.max_retries,
    )