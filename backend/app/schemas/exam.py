"""Schemas for exam generation, submission, and history APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginationParams
from app.schemas.enums import DifficultyValue, QuestionTypeValue


class ExamMakeRequest(BaseModel):
    """Request body for generating a new exam inside a subject."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "num": 10,
                "points": ["Conditional Probability", "Bayes' Theorem"],
            }
        }
    )

    num: int = Field(default=10, ge=1, le=50, description="Number of questions to generate.")
    points: list[str] | None = Field(default=None, description="Optional explicit knowledge-point scope.")


class QuestionItem(BaseModel):
    """Public exam question DTO that intentionally hides the correct answer."""

    question_key: str = Field(description="Stable question key such as q1.", examples=["q1"])
    type: QuestionTypeValue = Field(description="Question type.")
    stem: str = Field(description="Question stem.")
    options: list[str] | None = Field(default=None, description="Multiple-choice options when applicable.")
    knowledge_point: str = Field(description="Knowledge point associated with the question.")
    difficulty: DifficultyValue = Field(description="Question difficulty.")


class ExamResponse(BaseModel):
    """Response returned after a new exam has been generated."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "exam_id": 5,
                "questions": [
                    {
                        "question_key": "q1",
                        "type": "single_choice",
                        "stem": "Which formula defines conditional probability?",
                        "options": ["P(A|B)=P(AB)/P(B)", "P(A)+P(B)"],
                        "knowledge_point": "Conditional Probability",
                        "difficulty": "easy",
                    }
                ],
            }
        }
    )

    exam_id: int = Field(description="Generated exam identifier.", examples=[5])
    questions: list[QuestionItem] = Field(description="Exam questions.")


class AnswerItem(BaseModel):
    question_key: str = Field(description="Question key.", examples=["q1"])
    answer: str = Field(description="Submitted answer.", examples=["P(A|B)=P(AB)/P(B)"])


class ExamSubmitRequest(BaseModel):
    """Request body for submitting answers to an existing exam."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "exam_id": 5,
                "answers": [{"question_key": "q1", "answer": "P(A|B)=P(AB)/P(B)"}],
            }
        }
    )

    exam_id: int = Field(description="Existing exam identifier.", examples=[5])
    answers: list[AnswerItem] = Field(description="Answers keyed by question_key.")


class AnswerResultItem(BaseModel):
    question_key: str = Field(description="Question key.")
    is_correct: bool = Field(description="Whether the answer is correct.")
    user_answer: str = Field(description="Submitted answer.")
    correct_answer: str = Field(description="Reference answer.")
    explanation: str = Field(description="Standard explanation or grading explanation.")
    analysis: str | None = Field(default=None, description="Mistake analysis when the answer is wrong.")


class SubmitResponse(BaseModel):
    """Exam grading summary returned after a submission is processed."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "submission_id": 9,
                "score": 80.0,
                "results": [
                    {
                        "question_key": "q1",
                        "is_correct": True,
                        "user_answer": "P(A|B)=P(AB)/P(B)",
                        "correct_answer": "P(A|B)=P(AB)/P(B)",
                        "explanation": "This follows from the definition of conditional probability.",
                        "analysis": None,
                    }
                ],
            }
        }
    )

    submission_id: int = Field(description="Submission record identifier.", examples=[9])
    score: float = Field(description="Score on a 0-100 scale.", ge=0, le=100, examples=[80.0])
    results: list[AnswerResultItem] = Field(description="Per-question grading results.")


class ExamListRequest(PaginationParams):
    pass


class ExamHistoryItem(BaseModel):
    exam_id: int = Field(description="Exam identifier.")
    submission_id: int | None = Field(default=None, description="Latest submission identifier.")
    score: float | None = Field(default=None, description="Latest submission score.")
    created_at: datetime = Field(description="Exam creation timestamp in UTC.")


class ExamHistoryResponse(BaseModel):
    """Paginated response for exam history entries."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "exam_id": 5,
                        "submission_id": 9,
                        "score": 80.0,
                        "created_at": "2026-03-15T08:00:00Z",
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[ExamHistoryItem] = Field(description="Current page of historical exams.")
    total: int = Field(description="Total number of historical exams.", ge=0)
