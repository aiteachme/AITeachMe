"""Central model policy for Planner LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.llm_support.model_choices import normalize_runtime_model_override
from app.workflows.digest.common.model_policy import compact_metadata

PlannerModelSlot = Literal["light", "primary", "reason"]


class PlannerModelStep(str, Enum):
    STREAM_BRIEF = "stream_brief_and_extract_intent.stream_planner_brief"
    EXTRACT_INTENT = "stream_brief_and_extract_intent.extract_plan_intent"
    COMPOSE_PLAN = "stream_and_parse_plan_draft.compose_plan"
    SUBJECT_NAME = "generate_subject_name"
    SUBJECT_ICON = "generate_subject_name.select_subject_icon"


@dataclass(frozen=True)
class PlannerModelPolicy:
    step: PlannerModelStep
    call_type: Literal["stream", "structured", "text"]
    call_purpose: LLMCallPurpose
    model: PlannerModelSlot
    max_tokens: int | None = None
    temperature_override: float | None = None
    note: str = ""

    def completion_kwargs(self, *, model_override: str | None = None) -> dict[str, object]:
        """Return kwargs shared by Planner text/structured/stream call sites."""

        resolved_model = normalize_runtime_model_override(model_override) or self.model
        kwargs: dict[str, object] = {
            "call_purpose": self.call_purpose,
            "model": resolved_model,
        }
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.temperature_override is not None:
            kwargs["temperature"] = self.temperature_override
        return kwargs

    def metadata(self, *, model_override: str | None = None) -> dict[str, object]:
        """Return stable observability metadata for one Planner LLM call."""

        metadata: dict[str, object] = {
            "planner_model_step": self.step.value,
            "planner_model_slot": self.model,
            "planner_call_type": self.call_type,
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
    PlannerModelStep.STREAM_BRIEF: PlannerModelPolicy(
        step=PlannerModelStep.STREAM_BRIEF,
        call_type="stream",
        call_purpose=LLMCallPurpose.GENERATE,
        model="light",
        max_tokens=900,
        note="用户可见的资料边界判断，不负责最终合同，用 light 降低首屏等待。",
    ),
    PlannerModelStep.EXTRACT_INTENT: PlannerModelPolicy(
        step=PlannerModelStep.EXTRACT_INTENT,
        call_type="structured",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="light",
        max_tokens=700,
        note="结构化抽取内部规划抓手，输出短，优先 light 提速。",
    ),
    PlannerModelStep.COMPOSE_PLAN: PlannerModelPolicy(
        step=PlannerModelStep.COMPOSE_PLAN,
        call_type="stream",
        call_purpose=LLMCallPurpose.REASONING,
        model="light",
        max_tokens=2600,
        note="生成可确认课程方案和机器 JSON 合同，是 Planner 最核心的规划调用。",
    ),
    PlannerModelStep.SUBJECT_NAME: PlannerModelPolicy(
        step=PlannerModelStep.SUBJECT_NAME,
        call_type="text",
        call_purpose=LLMCallPurpose.GENERATE,
        model="light",
        max_tokens=40,
        note="短标题生成属于轻量生成，使用 GENERATE 的默认采样配置。",
    ),
    PlannerModelStep.SUBJECT_ICON: PlannerModelPolicy(
        step=PlannerModelStep.SUBJECT_ICON,
        call_type="text",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="light",
        max_tokens=20,
        note="图标候选选择属于轻量分类任务。",
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
