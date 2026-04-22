"""Study-guide generation for graded exam papers."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.schemas.exams import ExamStudyGuideFocusUnit, ExamStudyGuideResponse
from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.observability.trace import traceable_with_context
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


def _fallback_study_guide(
    *,
    exam_paper_id: int,
    subject: str,
    generated_at: datetime,
    weak_points: list[dict[str, str]],
    pending_reviews: list[dict[str, str]],
) -> ExamStudyGuideResponse:
    focus_units = [
        ExamStudyGuideFocusUnit(
            knowledge_unit_id=item.get("knowledge_unit_id"),
            knowledge_unit_name=str(item.get("knowledge_unit_name") or "未命名知识点"),
            mastery_score=item.get("mastery_score"),
            reason=str(item.get("reason") or "掌握度偏低，需要优先回补。"),
        )
        for item in weak_points[:3]
    ]
    return ExamStudyGuideResponse(
        exam_paper_id=exam_paper_id,
        subject=subject,
        generated_at=generated_at,
        overall_summary="本次考卷已经暴露出当前知识掌握中的薄弱环节，建议先从错题相关知识点切入，再配合待复习任务完成查漏补缺。",
        strengths=["已经完成整份考卷并形成了可用于复盘的作答记录。"] if not weak_points else ["已经明确暴露出本轮最需要优先处理的薄弱区。"],
        priority_gaps=[
            str(item.get("knowledge_unit_name") or "薄弱知识点")
            for item in weak_points[:4]
        ] or ["优先回看本次错题涉及的核心知识点。"],
        action_steps=[
            "先逐题复盘本次错题与未作答题，确认失分原因。",
            "按照薄弱知识点顺序回看对应知识讲解与例题。",
            "针对每个薄弱点补做 2-3 道同类题，验证是否真正补上。",
        ],
        review_tasks=[
            str(item.get("knowledge_unit_name") or "待复习知识点")
            for item in pending_reviews[:4]
        ] or ["完成本次错题相关知识点的复习任务。"],
        focus_units=focus_units,
    )


@traceable_with_context(
    name="考试：学习指南生成",
    run_type="chain",
    metadata_factory=lambda **kwargs: {
        "substep": "exam.study_guide.generate",
        "exam_paper_id": kwargs.get("exam_paper_id"),
        "subject": kwargs.get("subject"),
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
    subject: str,
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
                subject=subject,
                exam_title=exam_title,
                score_summary=score_summary,
                wrong_question_summaries=wrong_question_summaries,
                weak_points=weak_points,
                pending_reviews=pending_reviews,
            ),
            call_purpose=LLMCallPurpose.SUMMARIZE,
            model="primary",
            response_model=ExamStudyGuidePayload,
            temperature=0.2,
            max_tokens=1400,
            extra_metadata={
                "substep": "exam.study_guide",
                "subject": subject,
                "exam_paper_id": exam_paper_id,
            },
        )
        assert isinstance(result, ExamStudyGuidePayload)
        return ExamStudyGuideResponse(
            exam_paper_id=exam_paper_id,
            subject=subject,
            generated_at=generated_at,
            overall_summary=result.overall_summary,
            strengths=result.strengths,
            priority_gaps=result.priority_gaps,
            action_steps=result.action_steps,
            review_tasks=result.review_tasks,
            focus_units=result.focus_units,
        )
    except Exception:
        return _fallback_study_guide(
            exam_paper_id=exam_paper_id,
            subject=subject,
            generated_at=generated_at,
            weak_points=weak_points,
            pending_reviews=pending_reviews,
        )


__all__ = [
    "ExamStudyGuidePayload",
    "generate_exam_study_guide",
]
