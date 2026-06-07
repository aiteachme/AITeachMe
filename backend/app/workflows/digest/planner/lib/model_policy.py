"""Central model policy for Planner LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.model_choices import normalize_runtime_model_override
from app.workflows.common.model_policy import compact_metadata

PlannerModelSlot = Literal["light", "primary", "reason"]


class PlannerModelStep(str, Enum):
    STREAM_INTENT = "understand_goal_and_materials.stream_intent"
    SUMMARIZE_MATERIALS = "understand_goal_and_materials.summarize_materials"
    DRAFT_PLAN = "compose_planner_draft"
    COURSE_IDENTITY = "generate_course_identity"


@dataclass(frozen=True)
class PlannerModelPolicy:
    step: PlannerModelStep
    call_type: Literal["stream", "structured", "text"]
    model: PlannerModelSlot
    max_tokens: int | None = None
    timeout_s: int | None = None
    max_retries: int = 3
    temperature: float | None = None
    note: str = ""

    def completion_kwargs(self, *, model_override: str | None = None) -> dict[str, object]:
        """Return kwargs shared by Planner text/structured/stream call sites."""

        # Runtime model overrides patch settings.models at the workflow boundary.
        # Individual calls should keep their logical slot for trace readability.
        _ = model_override
        kwargs: dict[str, object] = {
            "model": self.model,
        }
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.timeout_s is not None:
            kwargs["timeout"] = self.timeout_s
        kwargs["max_retries"] = self.max_retries
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        return kwargs

    def metadata(self, *, model_override: str | None = None) -> dict[str, object]:
        """Return stable observability metadata for one Planner LLM call."""

        metadata: dict[str, object] = {
            "planner_model_step": self.step.value,
            "planner_model_slot": self.model,
            "planner_call_type": self.call_type,
            "planner_max_tokens": self.max_tokens,
            "planner_timeout_s": self.timeout_s,
            "planner_max_retries": self.max_retries,
        }
        resolved_override = normalize_runtime_model_override(model_override)
        if resolved_override:
            metadata["planner_model_override"] = resolved_override
        return metadata

    def completion_kwargs_with_metadata(
        self,
        *,
        model_override: str | None = None,
        **extra_metadata: object,
    ) -> dict[str, object]:
        kwargs = self.completion_kwargs(model_override=model_override)
        kwargs["extra_metadata"] = compact_metadata(extra_metadata, self.metadata(model_override=model_override))
        return kwargs


_POLICIES: dict[PlannerModelStep, PlannerModelPolicy] = {
    PlannerModelStep.STREAM_INTENT: PlannerModelPolicy(
        step=PlannerModelStep.STREAM_INTENT,
        call_type="stream",
        model="light",
        max_tokens=2200,
        timeout_s=300,
        temperature=0.2,
        note="首轮流式识别学习意图和规划边界。",
    ),
    PlannerModelStep.SUMMARIZE_MATERIALS: PlannerModelPolicy(
        step=PlannerModelStep.SUMMARIZE_MATERIALS,
        call_type="structured",
        model="light",
        max_tokens=1600,
        timeout_s=120,
        temperature=0.1,
        note="首轮摘要学习资料，形成 summary 字段。",
    ),
    PlannerModelStep.DRAFT_PLAN: PlannerModelPolicy(
        step=PlannerModelStep.DRAFT_PLAN,
        call_type="stream",
        model="light",
        max_tokens=5200,
        timeout_s=480,
        temperature=0.1,
        note="生成 suggestion、plan 和 chapters；plan 段落会流式展示。",
    ),
    PlannerModelStep.COURSE_IDENTITY: PlannerModelPolicy(
        step=PlannerModelStep.COURSE_IDENTITY,
        call_type="structured",
        model="light",
        max_tokens=240,
        timeout_s=300,
        temperature=0.35,
        note="一次结构化调用同时生成课程名和课程图标 key。",
    ),
}


def get_planner_model_policy(step: PlannerModelStep | str) -> PlannerModelPolicy:
    resolved_step = step if isinstance(step, PlannerModelStep) else PlannerModelStep(str(step))
    return _POLICIES[resolved_step]


def planner_completion_kwargs(step: PlannerModelStep | str, *, model_override: str | None = None) -> dict[str, object]:
    return get_planner_model_policy(step).completion_kwargs(model_override=model_override)


def planner_completion_kwargs_with_metadata(
    step: PlannerModelStep | str,
    *,
    model_override: str | None = None,
    **extra_metadata: object,
) -> dict[str, object]:
    return get_planner_model_policy(step).completion_kwargs_with_metadata(
        model_override=model_override,
        **extra_metadata,
    )


__all__ = [
    "PlannerModelPolicy",
    "PlannerModelSlot",
    "PlannerModelStep",
    "get_planner_model_policy",
    "planner_completion_kwargs",
    "planner_completion_kwargs_with_metadata",
]
