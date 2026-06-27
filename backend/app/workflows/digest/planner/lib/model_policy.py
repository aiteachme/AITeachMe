"""Central model policy for Planner LLM calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.native_tools import PROVIDER_NATIVE_TOOLS_KWARG
from app.shared.infra.llm_support.model_choices import normalize_runtime_model_override
from app.shared.infra.settings import get_settings
from app.workflows.common.model_policy import ProviderNativeToolPolicy, compact_metadata

PlannerModelSlot = Literal["light", "primary", "reason"]
PlannerAPIMode = Literal["auto", "chat_completions", "responses"]
_PLANNER_FAST_TIMEOUT_S = 60
_PLANNER_UNDERSTAND_TIMEOUT_S = 45
_PLANNER_UNDERSTAND_OVERALL_TIMEOUT_S = 45
_PLANNER_DRAFT_TIMEOUT_S = 120
_PLANNER_DRAFT_OVERALL_TIMEOUT_S = 180
_PLANNER_IDENTITY_OVERALL_TIMEOUT_S = 60


class PlannerModelStep(str, Enum):
    MATERIAL_BATCH_SUMMARY = "load_materials.summarize_section_batch"
    STREAM_PLANNING_NOTE = "understand_goal_and_materials.stream_planning_note"
    SUMMARIZE_MATERIALS = "understand_goal_and_materials.summarize_materials"
    DIAGNOSE_QUESTIONS = "compose_planner_draft.diagnose_questions"
    DRAFT_PLAN = "compose_planner_draft"
    COURSE_IDENTITY = "generate_course_identity"


@dataclass(frozen=True)
class PlannerModelPolicy:
    step: PlannerModelStep
    call_type: Literal["stream", "structured", "text"]
    model: PlannerModelSlot
    api_mode: PlannerAPIMode | None = None
    max_tokens: int | None = None
    timeout_s: int | None = None
    overall_timeout_s: int = _PLANNER_IDENTITY_OVERALL_TIMEOUT_S
    max_retries: int = 3
    temperature: float | None = None
    provider_native_tools: ProviderNativeToolPolicy = field(default_factory=ProviderNativeToolPolicy.disabled)
    note: str = ""

    def completion_kwargs(self, *, model_override: str | None = None) -> dict[str, object]:
        """Return kwargs shared by Planner text/structured/stream call sites."""

        # Runtime model overrides patch settings.models at the workflow boundary.
        # Individual calls should keep their logical slot for trace readability.
        _ = model_override
        kwargs: dict[str, object] = {
            "model": self.model,
        }
        if self.api_mode is not None:
            kwargs["api_mode"] = self.api_mode
        kwargs[PROVIDER_NATIVE_TOOLS_KWARG] = self.provider_native_tools.build(
            settings=get_settings(),
            web_search=False,
            file_search=False,
        )
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.timeout_s is not None:
            kwargs["timeout"] = self.timeout_s
        kwargs["overall_timeout_s"] = self.overall_timeout_s
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
            "planner_api_mode": self.api_mode,
            "planner_max_tokens": self.max_tokens,
            "planner_timeout_s": self.timeout_s,
            "planner_overall_timeout_s": self.overall_timeout_s,
            "planner_max_retries": self.max_retries,
            **self.provider_native_tools.metadata(prefix="planner_provider_native"),
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
    PlannerModelStep.MATERIAL_BATCH_SUMMARY: PlannerModelPolicy(
        step=PlannerModelStep.MATERIAL_BATCH_SUMMARY,
        call_type="structured",
        model="light",
        max_tokens=1800,
        timeout_s=_PLANNER_UNDERSTAND_TIMEOUT_S,
        overall_timeout_s=_PLANNER_UNDERSTAND_OVERALL_TIMEOUT_S,
        max_retries=2,
        temperature=0.3,
        note="Planner material batch summary for uploaded section map-reduce.",
    ),
    PlannerModelStep.STREAM_PLANNING_NOTE: PlannerModelPolicy(
        step=PlannerModelStep.STREAM_PLANNING_NOTE,
        call_type="stream",
        model="light",
        max_tokens=2200,
        timeout_s=_PLANNER_UNDERSTAND_TIMEOUT_S,
        overall_timeout_s=_PLANNER_UNDERSTAND_OVERALL_TIMEOUT_S,
        temperature=0.3,
        note="首轮流式生成规划判断。",
    ),
    PlannerModelStep.SUMMARIZE_MATERIALS: PlannerModelPolicy(
        step=PlannerModelStep.SUMMARIZE_MATERIALS,
        call_type="structured",
        model="light",
        max_tokens=1600,
        timeout_s=_PLANNER_UNDERSTAND_TIMEOUT_S,
        overall_timeout_s=_PLANNER_UNDERSTAND_OVERALL_TIMEOUT_S,
        temperature=0.2,
        note="首轮摘要学习资料，形成内部资料边界供方案生成使用。",
    ),
    PlannerModelStep.DRAFT_PLAN: PlannerModelPolicy(
        step=PlannerModelStep.DRAFT_PLAN,
        call_type="stream",
        model="light",
        max_tokens=5200,
        timeout_s=_PLANNER_DRAFT_TIMEOUT_S,
        overall_timeout_s=_PLANNER_DRAFT_OVERALL_TIMEOUT_S,
        temperature=0.3,
        note="生成 suggestion、plan 和 chapters；plan 段落会流式展示。",
    ),
    PlannerModelStep.DIAGNOSE_QUESTIONS: PlannerModelPolicy(
        step=PlannerModelStep.DIAGNOSE_QUESTIONS,
        call_type="stream",
        model="light",
        max_tokens=1600,
        timeout_s=_PLANNER_FAST_TIMEOUT_S,
        overall_timeout_s=_PLANNER_FAST_TIMEOUT_S,
        temperature=0.3,
        note="生成前置诊断选择题；失败时终止本轮 Planner 构建。",
    ),
    PlannerModelStep.COURSE_IDENTITY: PlannerModelPolicy(
        step=PlannerModelStep.COURSE_IDENTITY,
        call_type="structured",
        model="light",
        max_tokens=240,
        timeout_s=_PLANNER_FAST_TIMEOUT_S,
        overall_timeout_s=_PLANNER_IDENTITY_OVERALL_TIMEOUT_S,
        temperature=0.7,
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
    "PlannerAPIMode",
    "PlannerModelPolicy",
    "PlannerModelSlot",
    "PlannerModelStep",
    "get_planner_model_policy",
    "planner_completion_kwargs",
    "planner_completion_kwargs_with_metadata",
]
