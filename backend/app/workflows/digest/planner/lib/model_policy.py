"""Central model policy for Planner LLM calls."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.routing import LLMCallPurpose

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
    temperature: float | None = None
    note: str = ""

    def completion_kwargs(self) -> dict[str, object]:
        """Return kwargs shared by Planner text/structured/stream call sites."""

        kwargs: dict[str, object] = {
            "call_purpose": self.call_purpose,
            "model": self.model,
        }
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        return kwargs

    def metadata(self) -> dict[str, object]:
        """Return stable observability metadata for one Planner LLM call."""

        return {
            "planner_model_step": self.step.value,
            "planner_model_slot": self.model,
            "planner_call_type": self.call_type,
        }

    def completion_kwargs_with_metadata(self, **extra_metadata: object) -> dict[str, object]:
        kwargs = self.completion_kwargs()
        kwargs["extra_metadata"] = {
            **self.metadata(),
            **{key: value for key, value in extra_metadata.items() if value not in (None, "", [], {})},
        }
        return kwargs


_POLICIES: dict[PlannerModelStep, PlannerModelPolicy] = {
    PlannerModelStep.STREAM_BRIEF: PlannerModelPolicy(
        step=PlannerModelStep.STREAM_BRIEF,
        call_type="stream",
        call_purpose=LLMCallPurpose.GENERATE,
        model="primary",
        max_tokens=900,
        note="用户可见的资料边界判断，不负责最终合同，用 primary 降低首屏等待。",
    ),
    PlannerModelStep.EXTRACT_INTENT: PlannerModelPolicy(
        step=PlannerModelStep.EXTRACT_INTENT,
        call_type="structured",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="primary",
        max_tokens=700,
        note="结构化抽取内部规划抓手，输出短但需要比 light 更稳。",
    ),
    PlannerModelStep.COMPOSE_PLAN: PlannerModelPolicy(
        step=PlannerModelStep.COMPOSE_PLAN,
        call_type="stream",
        call_purpose=LLMCallPurpose.REASONING,
        model="reason",
        max_tokens=2600,
        note="生成可确认课程方案和机器 JSON 合同，是 Planner 最核心的规划调用。",
    ),
    PlannerModelStep.SUBJECT_NAME: PlannerModelPolicy(
        step=PlannerModelStep.SUBJECT_NAME,
        call_type="text",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="light",
        max_tokens=40,
        temperature=0.2,
        note="短标题生成，轻量模型即可。",
    ),
    PlannerModelStep.SUBJECT_ICON: PlannerModelPolicy(
        step=PlannerModelStep.SUBJECT_ICON,
        call_type="text",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="light",
        max_tokens=20,
        temperature=0,
        note="图标候选选择，输出极短，失败后走本地规则兜底。",
    ),
}


def get_planner_model_policy(step: PlannerModelStep | str) -> PlannerModelPolicy:
    resolved_step = step if isinstance(step, PlannerModelStep) else PlannerModelStep(str(step))
    return _POLICIES[resolved_step]


def planner_completion_kwargs(step: PlannerModelStep | str) -> dict[str, object]:
    return get_planner_model_policy(step).completion_kwargs()


def planner_completion_kwargs_with_metadata(
    step: PlannerModelStep | str,
    **extra_metadata: object,
) -> dict[str, object]:
    return get_planner_model_policy(step).completion_kwargs_with_metadata(**extra_metadata)


__all__ = [
    "PlannerModelPolicy",
    "PlannerModelSlot",
    "PlannerModelStep",
    "get_planner_model_policy",
    "planner_completion_kwargs",
    "planner_completion_kwargs_with_metadata",
]
