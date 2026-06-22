"""Central model policy for exam grading LLM calls."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Literal

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
    model: ExamGradeModelSlot
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

    def metadata(self) -> dict[str, object]:
        return {
            "exam_grade_model_step": self.step.value,
            "exam_grade_model_slot": self.model,
            "exam_grade_call_type": self.call_type,
            "exam_grade_max_tokens": self.max_tokens,
            "exam_grade_timeout_s": self.timeout_s,
            "exam_grade_max_retries": self.max_retries,
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
        model="reason",
        max_tokens=1800,
        timeout_s=180,
        temperature=0.1,
        note="客观题正确性由规则判定，但反馈包含错因归纳和解析表达，保留 reason。",
    ),
    ExamGradeModelStep.SUBJECTIVE_GRADE: ExamGradeModelPolicy(
        step=ExamGradeModelStep.SUBJECTIVE_GRADE,
        call_type="structured",
        model="reason",
        max_tokens=2600,
        timeout_s=180,
        temperature=0.1,
        note="主观题判分反馈比客观题更长。",
    ),
    ExamGradeModelStep.STUDY_GUIDE: ExamGradeModelPolicy(
        step=ExamGradeModelStep.STUDY_GUIDE,
        call_type="structured",
        model="reason",
        max_tokens=4500,
        timeout_s=240,
        temperature=0.2,
        note="整卷学习指南会汇总错因、薄弱点和复习行动，保留 reason。",
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
