"""Central model policy for Profile report LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.workflows.common.model_policy import compact_metadata

ProfileModelSlot = Literal["light", "primary", "reason"]


class ProfileModelStep(str, Enum):
    REPORT_SUGGESTIONS = "profile.report_suggestions"


@dataclass(frozen=True)
class ProfileModelPolicy:
    step: ProfileModelStep
    call_type: Literal["text"]
    model: ProfileModelSlot
    max_tokens: int
    timeout_s: int
    max_retries: int = 3
    temperature: float | None = None
    note: str = ""

    def completion_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout_s,
            "max_retries": self.max_retries,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
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
                "profile_timeout_s": self.timeout_s,
                "profile_max_retries": self.max_retries,
            },
        )
        return kwargs


_POLICIES: dict[ProfileModelStep, ProfileModelPolicy] = {
    ProfileModelStep.REPORT_SUGGESTIONS: ProfileModelPolicy(
        step=ProfileModelStep.REPORT_SUGGESTIONS,
        call_type="text",
        model="light",
        max_tokens=1800,
        timeout_s=240,
        temperature=0.5,
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
