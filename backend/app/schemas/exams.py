"""Exam API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ExamGenerateRequest(BaseModel):
    """Trigger exam generation request."""

    exam_mode: str = Field(description="Exam mode.")
    user_prompt: str | None = Field(default=None, description="Optional user prompt for preference hints.")
    num_questions: int | None = Field(default=None, ge=1, le=200, description="Optional target question count.")
    theme_tree_node_id: int | None = Field(default=None, description="Optional theme tree node scope.")
    teaching_unit_ids: list[int] | None = Field(default=None, description="Optional teaching unit scope.")


class ExamSubmitAnswerItem(BaseModel):
    """One submitted answer item."""

    exam_paper_item_id: int | None = Field(default=None, description="Exam paper item ID.")
    item_order: int | None = Field(default=None, ge=1, description="Fallback key: item order.")
    answer: str = Field(description="User answer.")


class ExamSubmitRequest(BaseModel):
    """Submit exam answers request."""

    answers: list[ExamSubmitAnswerItem] = Field(default_factory=list, description="Submitted answers.")


class RuntimeStatusResponse(BaseModel):
    """Generic runtime status response."""

    id: int
    status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ExamGenerateResponse(RuntimeStatusResponse):
    subject: str
    user_id: str
    exam_mode: str
    num_questions: int
    exam_paper_id: int | None = None
    theme_tree_node_id: int | None = None
    teaching_unit_ids: list[int] = Field(default_factory=list)


class ExamGradeResponse(RuntimeStatusResponse):
    exam_paper_id: int
    score: float | None = None
    states_updated: int
    tasks_created: int
    mastery_consumed: bool


class ExamHistoryItem(BaseModel):
    id: int
    subject: str
    user_id: str
    exam_mode: str
    status: str
    total_items: int
    score_obtained: float | None = None
    total_score: float | None = None
    created_at: datetime
    submitted_at: datetime | None = None
    graded_at: datetime | None = None


class ExamPaperDeleteResponse(BaseModel):
    deleted: bool
    exam_paper_id: int


class QuestionBankItemResponse(BaseModel):
    question_template_id: int
    stem: str
    question_type: str
    difficulty: str
    teaching_unit_id: int
    times_asked: int
    last_asked_at: datetime
    last_exam_paper_id: int


class ExamPaperItemResponse(BaseModel):
    id: int
    item_order: int
    question_template_id: int
    question_type: str
    difficulty: str
    stem: str
    options: list[str] | None = None
    explanation: str
    teaching_unit_id: int
    node_links: list[dict] = Field(default_factory=list)
    user_answer: str | None = None
    is_correct: bool | None = None
    score_obtained: float | None = None
    score_max: float | None = None
    error_cause_label: str | None = None


class ExamPaperDetailResponse(BaseModel):
    id: int
    subject: str
    user_id: str
    exam_mode: str
    status: str
    total_items: int
    score_obtained: float | None = None
    total_score: float | None = None
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    created_at: datetime
    items: list[ExamPaperItemResponse] = Field(default_factory=list)
