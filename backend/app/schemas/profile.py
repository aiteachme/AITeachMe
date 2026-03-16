"""Schemas for profile mastery, report, and mistake-book APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginationParams
from app.schemas.enums import QuestionTypeValue


class ProfileListRequest(PaginationParams):
    pass


class ProfileReportRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {}})


class ProfileMistakesRequest(PaginationParams):
    pass


class ProfileItem(BaseModel):
    """Single knowledge-point mastery record."""

    knowledge_point: str = Field(description="Knowledge point name.", examples=["Conditional Probability"])
    mastery: float | None = Field(default=None, description="Estimated mastery score from 0.0 to 1.0.", ge=0, le=1)
    attempts: int = Field(description="Accumulated answer attempts.", ge=0)
    correct: int = Field(description="Accumulated correct answers.", ge=0)


class ProfileListResponse(BaseModel):
    """Paginated response for profile mastery items."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "knowledge_point": "Conditional Probability",
                        "mastery": 0.6,
                        "attempts": 5,
                        "correct": 3,
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[ProfileItem] = Field(description="Current page of mastery records.")
    total: int = Field(description="Total number of mastery records.", ge=0)


class ReportResponse(BaseModel):
    """Aggregated learning report used by the profile report endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "overall_mastery": 0.72,
                "weak_points_top5": [
                    {
                        "knowledge_point": "Bayes' Theorem",
                        "mastery": 0.4,
                        "attempts": 5,
                        "correct": 2,
                    }
                ],
                "suggestions": ["Review Bayes' theorem application problems first."],
            }
        }
    )

    overall_mastery: float | None = Field(default=None, description="Weighted overall mastery score.", ge=0, le=1)
    weak_points_top5: list[ProfileItem] = Field(description="Five weakest knowledge points.")
    suggestions: list[str] = Field(description="Revision suggestions generated from the learner profile.")


class MistakeItem(BaseModel):
    """Single mistake-book item composed from exam and grading records."""

    id: int = Field(description="Mistake identifier.")
    question_stem: str = Field(description="Question stem.")
    question_type: QuestionTypeValue = Field(description="Question type.")
    user_answer: str = Field(description="Submitted answer.")
    correct_answer: str = Field(description="Reference answer.")
    analysis: str = Field(description="AI-generated mistake analysis.")
    knowledge_point: str = Field(description="Associated knowledge point.")
    created_at: datetime = Field(description="Mistake creation timestamp in UTC.")


class ProfileMistakesResponse(BaseModel):
    """Paginated response for the subject mistake book."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 3,
                        "question_stem": "What is the formula of Bayes' theorem?",
                        "question_type": "short_answer",
                        "user_answer": "I forgot",
                        "correct_answer": "P(A|B)=P(B|A)P(A)/P(B)",
                        "analysis": "The answer confuses priors and conditional probabilities.",
                        "knowledge_point": "Bayes' Theorem",
                        "created_at": "2026-03-15T08:00:00Z",
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[MistakeItem] = Field(description="Current page of mistake items.")
    total: int = Field(description="Total number of mistakes.", ge=0)
