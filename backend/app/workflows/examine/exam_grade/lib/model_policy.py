"""Central model policy for exam grading LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal

from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.common.model_policy import compact_metadata

ExamGradeModelSlot = Literal["light", "primary", "reason"]


class ExamGradeModelStep(str, Enum):
    OBJECTIVE_FEEDBACK = "exam_grade.objective_feedback"
    SUBJECTIVE_GRADE = "exam_grade.subjective_grade"
    STUDY_GUIDE = "exam_grade.study_guide"


@dataclass(frozen=True)
class ExamGradeModelPolicy:
    step: ExamGradeModelStep
    call_type: Literal["structured"]
    call_purpose: LLMCallPurpose
    model: ExamGradeModelSlot
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

    def metadata(self) -> dict[str, object]:
        return {
            "exam_grade_model_step": self.step.value,
            "exam_grade_model_slot": self.model,
            "exam_grade_call_type": self.call_type,
            "exam_grade_max_tokens": self.max_tokens,
        }

    def completion_kwargs_with_metadata(
        self,
        extra_metadata: Mapping[str, object] | None = None,
        **metadata: object,
    ) -> dict[str, object]:
        kwargs = self.completion_kwargs()
        kwargs["extra_metadata"] = compact_metadata(extra_metadata, metadata, self.metadata())
        return kwargs


_POLICIES: dict[ExamGradeModelStep, ExamGradeModelPolicy] = {
    ExamGradeModelStep.OBJECTIVE_FEEDBACK: ExamGradeModelPolicy(
        step=ExamGradeModelStep.OBJECTIVE_FEEDBACK,
        call_type="structured",
        call_purpose=LLMCallPurpose.GRADE,
        model="reason",
        max_tokens=1200,
        temperature_override=0.1,
        note="客观题反馈短，但需要容纳错因标签和解释。",
    ),
    ExamGradeModelStep.SUBJECTIVE_GRADE: ExamGradeModelPolicy(
        step=ExamGradeModelStep.SUBJECTIVE_GRADE,
        call_type="structured",
        call_purpose=LLMCallPurpose.GRADE,
        model="reason",
        max_tokens=1800,
        temperature_override=0.1,
        note="主观题判分反馈比客观题更长。",
    ),
    ExamGradeModelStep.STUDY_GUIDE: ExamGradeModelPolicy(
        step=ExamGradeModelStep.STUDY_GUIDE,
        call_type="structured",
        call_purpose=LLMCallPurpose.SUMMARIZE,
        model="reason",
        max_tokens=3200,
        temperature_override=0.2,
        note="整卷学习指南包含总结、优势、缺口、行动项和复习任务。",
    ),
}


def get_exam_grade_model_policy(step: ExamGradeModelStep | str) -> ExamGradeModelPolicy:
    resolved_step = step if isinstance(step, ExamGradeModelStep) else ExamGradeModelStep(str(step))
    return _POLICIES[resolved_step]


def exam_grade_completion_kwargs(step: ExamGradeModelStep | str) -> dict[str, object]:
    return get_exam_grade_model_policy(step).completion_kwargs()


def exam_grade_completion_kwargs_with_metadata(
    step: ExamGradeModelStep | str,
    *,
    extra_metadata: Mapping[str, object] | None = None,
    **metadata: object,
) -> dict[str, object]:
    return get_exam_grade_model_policy(step).completion_kwargs_with_metadata(
        extra_metadata=extra_metadata,
        **metadata,
    )


__all__ = [
    "ExamGradeModelPolicy",
    "ExamGradeModelSlot",
    "ExamGradeModelStep",
    "exam_grade_completion_kwargs",
    "exam_grade_completion_kwargs_with_metadata",
    "get_exam_grade_model_policy",
]

