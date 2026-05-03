"""Central model policy for Profile report LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.common.model_policy import compact_metadata

ProfileModelSlot = Literal["light", "primary", "reason"]


class ProfileModelStep(str, Enum):
    REPORT_SUGGESTIONS = "profile.report_suggestions"


@dataclass(frozen=True)
class ProfileModelPolicy:
    step: ProfileModelStep
    call_type: Literal["text"]
    call_purpose: LLMCallPurpose
    model: ProfileModelSlot
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
                "profile_model_step": self.step.value,
                "profile_model_slot": self.model,
                "profile_call_type": self.call_type,
                "profile_max_tokens": self.max_tokens,
            },
        )
        return kwargs


_POLICIES: dict[ProfileModelStep, ProfileModelPolicy] = {
    ProfileModelStep.REPORT_SUGGESTIONS: ProfileModelPolicy(
        step=ProfileModelStep.REPORT_SUGGESTIONS,
        call_type="text",
        call_purpose=LLMCallPurpose.SUMMARIZE,
        model="light",
        max_tokens=1200,
        note="学习建议是轻量总结，但设置明确输出预算避免 provider 默认过小。",
    ),
}


def get_profile_model_policy(step: ProfileModelStep | str) -> ProfileModelPolicy:
    resolved_step = step if isinstance(step, ProfileModelStep) else ProfileModelStep(str(step))
    return _POLICIES[resolved_step]


def profile_completion_kwargs(step: ProfileModelStep | str) -> dict[str, object]:
    return get_profile_model_policy(step).completion_kwargs()


def profile_completion_kwargs_with_metadata(
    step: ProfileModelStep | str,
    *,
    extra_metadata: Mapping[str, object] | None = None,
    **metadata: object,
) -> dict[str, object]:
    return get_profile_model_policy(step).completion_kwargs_with_metadata(
        extra_metadata=extra_metadata,
        **metadata,
    )


__all__ = [
    "ProfileModelPolicy",
    "ProfileModelSlot",
    "ProfileModelStep",
    "get_profile_model_policy",
    "profile_completion_kwargs",
    "profile_completion_kwargs_with_metadata",
]

