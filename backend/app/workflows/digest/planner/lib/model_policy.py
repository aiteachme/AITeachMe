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


@dataclass(frozen=True)
class PlannerModelPolicy:
    step: PlannerModelStep
    call_type: Literal["stream", "structured", "text"]
    call_purpose: LLMCallPurpose
    model: PlannerModelSlot
    note: str = ""

    def completion_kwargs(self) -> dict[str, object]:
        """Return kwargs shared by Planner text/structured/stream call sites."""

        return {
            "call_purpose": self.call_purpose,
            "model": self.model,
        }


_POLICIES: dict[PlannerModelStep, PlannerModelPolicy] = {
    PlannerModelStep.STREAM_BRIEF: PlannerModelPolicy(
        step=PlannerModelStep.STREAM_BRIEF,
        call_type="stream",
        call_purpose=LLMCallPurpose.REASONING,
        model="reason",
        note="用户可见的资料边界判断，需要稳住目标理解与课程模式选择。",
    ),
    PlannerModelStep.EXTRACT_INTENT: PlannerModelPolicy(
        step=PlannerModelStep.EXTRACT_INTENT,
        call_type="structured",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="primary",
        note="结构化抽取内部规划抓手，输出短但需要比 light 更稳。",
    ),
    PlannerModelStep.COMPOSE_PLAN: PlannerModelPolicy(
        step=PlannerModelStep.COMPOSE_PLAN,
        call_type="stream",
        call_purpose=LLMCallPurpose.REASONING,
        model="reason",
        note="生成可确认课程方案和机器 JSON 合同，是 Planner 最核心的规划调用。",
    ),
    PlannerModelStep.SUBJECT_NAME: PlannerModelPolicy(
        step=PlannerModelStep.SUBJECT_NAME,
        call_type="text",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="light",
        note="短标题生成，轻量模型即可。",
    ),
}


def get_planner_model_policy(step: PlannerModelStep | str) -> PlannerModelPolicy:
    resolved_step = step if isinstance(step, PlannerModelStep) else PlannerModelStep(str(step))
    return _POLICIES[resolved_step]


def planner_completion_kwargs(step: PlannerModelStep | str) -> dict[str, object]:
    return get_planner_model_policy(step).completion_kwargs()


__all__ = [
    "PlannerModelPolicy",
    "PlannerModelSlot",
    "PlannerModelStep",
    "get_planner_model_policy",
    "planner_completion_kwargs",
]
