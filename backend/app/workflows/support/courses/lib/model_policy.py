"""Central model policy for course-support LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.common.model_policy import compact_metadata

CourseSupportModelSlot = Literal["light", "primary", "reason"]


class CourseSupportModelStep(str, Enum):
    ICON_SELECTION = "courses.icon_selection"


@dataclass(frozen=True)
class CourseSupportModelPolicy:
    step: CourseSupportModelStep
    call_type: Literal["text"]
    call_purpose: LLMCallPurpose
    model: CourseSupportModelSlot
    max_tokens: int
    temperature_override: float | None = None
    note: str = ""

    def completion_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "call_purpose": self.call_purpose,
            "model": self.model,
            "max_tokens": self.max_tokens,
        }
        if self.temperature_override is not None:
            kwargs["temperature"] = self.temperature_override
        return kwargs

    def completion_kwargs_with_metadata(
        self,
        *,
        extra_metadata: Mapping[str, object] | None = None,
        **metadata: object,
    ) -> dict[str, object]:
        kwargs = self.completion_kwargs()
        kwargs["extra_metadata"] = compact_metadata(
            extra_metadata,
            metadata,
            {
                "course_support_model_step": self.step.value,
                "course_support_model_slot": self.model,
                "course_support_call_type": self.call_type,
                "course_support_max_tokens": self.max_tokens,
            },
        )
        return kwargs


_POLICIES: dict[CourseSupportModelStep, CourseSupportModelPolicy] = {
    CourseSupportModelStep.ICON_SELECTION: CourseSupportModelPolicy(
        step=CourseSupportModelStep.ICON_SELECTION,
        call_type="text",
        call_purpose=LLMCallPurpose.CLASSIFY,
        model="light",
        max_tokens=80,
        temperature_override=0.0,
        note="图标选择是短分类，但给少量冗余避免模型输出解释时被截断。",
    ),
}


def get_course_support_model_policy(
    step: CourseSupportModelStep | str,
) -> CourseSupportModelPolicy:
    resolved_step = step if isinstance(step, CourseSupportModelStep) else CourseSupportModelStep(str(step))
    return _POLICIES[resolved_step]


def course_support_completion_kwargs_with_metadata(
    step: CourseSupportModelStep | str,
    *,
    extra_metadata: Mapping[str, object] | None = None,
    **metadata: object,
) -> dict[str, object]:
    return get_course_support_model_policy(step).completion_kwargs_with_metadata(
        extra_metadata=extra_metadata,
        **metadata,
    )


__all__ = [
    "CourseSupportModelPolicy",
    "CourseSupportModelSlot",
    "CourseSupportModelStep",
    "course_support_completion_kwargs_with_metadata",
    "get_course_support_model_policy",
]

