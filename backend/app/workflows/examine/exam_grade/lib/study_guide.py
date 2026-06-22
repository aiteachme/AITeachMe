"""Study-guide generation for graded exam papers."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.exams import ExamStudyGuideFocusUnit, ExamStudyGuideResponse
from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.observability.trace import traceable_with_context
from app.workflows.examine.exam_grade.lib.model_policy import (
    ExamGradeModelStep,
    exam_grade_completion_kwargs_with_metadata,
)
from app.workflows.examine.exam_grade.prompts import build_study_guide_messages


class ExamStudyGuidePayload(BaseModel):
    overall_summary: str = Field(min_length=20, max_length=1600)
    strengths: list[str] = Field(default_factory=list)
    priority_gaps: list[str] = Field(default_factory=list)
    action_steps: list[str] = Field(default_factory=list)
    review_tasks: list[str] = Field(default_factory=list)
    focus_units: list[ExamStudyGuideFocusUnit] = Field(default_factory=list)

    @field_validator("overall_summary")
    @classmethod
    def _strip_summary(cls, value: str) -> str:
        return " ".join(str(value or "").split()).strip()

    @field_validator("strengths", "priority_gaps", "action_steps", "review_tasks")
    @classmethod
    def _normalize_str_list(cls, value: list[str]) -> list[str]:
        return [" ".join(str(item or "").split()).strip() for item in value if str(item or "").strip()]


class ExamStudyGuideGenerationError(RuntimeError):
    """Raised when the study-guide model does not produce a usable guide."""


@traceable_with_context(
    name="考试：学习指南生成",
    run_type="chain",
    metadata_factory=lambda **kwargs: {
        "substep": "exam.study_guide.generate",
        "exam_paper_id": kwargs.get("exam_paper_id"),
        "course_name": kwargs.get("course_name"),
        "wrong_question_count": len(kwargs.get("wrong_question_summaries") or []),
        "weak_point_count": len(kwargs.get("weak_points") or []),
        "pending_review_count": len(kwargs.get("pending_reviews") or []),
    },
    tags_factory=lambda **kwargs: [
        "exam-grade",
        "study-guide",
    ],
)
async def generate_exam_study_guide(
    *,
    exam_paper_id: int,
    course_name: str,
    exam_title: str,
    score_summary: str,
    wrong_question_summaries: list[dict[str, str]],
    weak_points: list[dict[str, str]],
    pending_reviews: list[dict[str, str]],
    generated_at: datetime,
) -> ExamStudyGuideResponse:
    try:
        result = await acompletion_with_fallback(
            build_study_guide_messages(
                course_name=course_name,
                exam_title=exam_title,
                score_summary=score_summary,
                wrong_question_summaries=wrong_question_summaries,
                weak_points=weak_points,
                pending_reviews=pending_reviews,
            ),
            **exam_grade_completion_kwargs_with_metadata(
                ExamGradeModelStep.STUDY_GUIDE,
                extra_metadata={
                    "substep": "exam.study_guide",
                    "course_name": course_name,
                    "exam_paper_id": exam_paper_id,
                },
            ),
            response_model=ExamStudyGuidePayload,
        )
        assert isinstance(result, ExamStudyGuidePayload)
    except Exception as exc:
        raise ExamStudyGuideGenerationError(
            f"study-guide model failed for exam_paper_id={exam_paper_id}: {exc}"
        ) from exc
    return ExamStudyGuideResponse(
        exam_paper_id=exam_paper_id,
        course_name=course_name,
        generated_at=generated_at,
        overall_summary=result.overall_summary,
        strengths=result.strengths,
        priority_gaps=result.priority_gaps,
        action_steps=result.action_steps,
        review_tasks=result.review_tasks,
        focus_units=result.focus_units,
    )


__all__ = [
    "ExamStudyGuideGenerationError",
    "ExamStudyGuidePayload",
    "generate_exam_study_guide",
]
