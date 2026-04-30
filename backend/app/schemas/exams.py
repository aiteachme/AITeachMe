"""Exam API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExamGenerateRequest(BaseModel):
    """Trigger exam generation request."""

    exam_mode: str = Field(description="Exam mode: web_practice | paper_exam (legacy values are compatible).")
    user_prompt: str | None = Field(default=None, description="Optional user requirements for exam generation.")
    sample_file_ids: list[str] | None = Field(default=None, description="Optional uploaded sample-paper file IDs.")
    num_questions: int | None = Field(default=None, ge=1, le=200, description="Optional target question count.")


class ExamSubmitAnswerItem(BaseModel):
    """One submitted answer item."""

    exam_paper_item_id: int | None = Field(default=None, description="Exam paper item ID.")
    item_order: int | None = Field(default=None, ge=1, description="Fallback key: item order.")
    answer: str = Field(description="User answer.")


class ExamSubmitRequest(BaseModel):
    """Submit exam answers request."""

    answers: list[ExamSubmitAnswerItem] = Field(default_factory=list, description="Submitted answers.")


class QuestionTemplateMarkRequest(BaseModel):
    """Update whether a question template is marked as a favorite."""

    is_marked: bool = Field(description="Whether the question template is marked.")


class QuestionTemplateMarkResponse(BaseModel):
    question_template_id: int
    is_marked: bool


class RuntimeStatusResponse(BaseModel):
    """Generic runtime status response."""

    id: int
    status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ExamGenerateResponse(RuntimeStatusResponse):
    course_id: str
    user_id: str
    exam_mode: str
    num_questions: int
    exam_paper_id: int | None = None
    sample_file_ids: list[str] = Field(default_factory=list)


class ExamPrewarmStatusResponse(BaseModel):
    status: Literal["ready", "preparing", "missing", "failed", "stale"]
    exam_mode: str
    num_questions: int
    prepared_at: datetime | None = None
    expires_at: datetime | None = None
    updated_at: datetime | None = None
    background_requested: bool = False
    error_message: str | None = None


class ExamGradeResponse(RuntimeStatusResponse):
    exam_paper_id: int
    score: float | None = None
    states_updated: int
    tasks_created: int
    mastery_consumed: bool


class ExamStudyGuideFocusUnit(BaseModel):
    knowledge_unit_id: int | None = None
    knowledge_unit_name: str
    mastery_score: float | None = None
    reason: str


class ExamStudyGuideResponse(BaseModel):
    exam_paper_id: int
    course_name: str
    generated_at: datetime
    overall_summary: str
    strengths: list[str] = Field(default_factory=list)
    priority_gaps: list[str] = Field(default_factory=list)
    action_steps: list[str] = Field(default_factory=list)
    review_tasks: list[str] = Field(default_factory=list)
    focus_units: list[ExamStudyGuideFocusUnit] = Field(default_factory=list)


PaperPreviewShape = Literal["choice", "blank", "short", "judge", "chart", "formula", "code", "text"]
PaperPreviewResultStatus = Literal["ungraded", "correct", "incorrect"]
PaperPreviewGenerationStatus = Literal["pending", "planned", "generated", "failed"]


class PaperPreviewRow(BaseModel):
    order: int
    type: str
    shape: PaperPreviewShape
    difficulty: str
    density: int = Field(default=2, ge=1, le=3)
    result_status: PaperPreviewResultStatus = "ungraded"
    generation_status: PaperPreviewGenerationStatus = "generated"


class PaperPreview(BaseModel):
    keywords: list[str] = Field(default_factory=list)
    question_types: list[str] = Field(default_factory=list)
    rows: list[PaperPreviewRow] = Field(default_factory=list)
    overflow_count: int = Field(default=0, ge=0)


class ExamHistoryItem(BaseModel):
    id: int
    course_id: str
    user_id: str
    exam_mode: str
    status: str
    total_items: int
    score_obtained: float | None = None
    total_score: float | None = None
    created_at: datetime
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    paper_preview: PaperPreview = Field(default_factory=PaperPreview)


class ExamPaperDeleteResponse(BaseModel):
    deleted: bool
    exam_paper_id: int


class QuestionBankItemResponse(BaseModel):
    question_template_id: int
    stem: str
    question_type: str
    difficulty: str
    knowledge_unit_id: int
    times_asked: int
    last_asked_at: datetime
    last_exam_paper_id: int
    knowledge_points: list[str] = Field(default_factory=list)
    style_summary: str | None = None


class QuestionTemplateItemResponse(BaseModel):
    id: int
    course_id: str
    question_type: str
    difficulty: str
    stem: str
    options: list[str] | None = None
    answer: str
    explanation: str
    knowledge_unit_refs: list[dict[str, Any]] = Field(default_factory=list)
    selection_hints: dict[str, Any] = Field(default_factory=dict)
    template_version: int
    status: str
    is_marked: bool = False
    has_wrong_attempt: bool = False
    created_at: datetime
    updated_at: datetime


class QuestionTemplateAnswerHistoryItem(BaseModel):
    exam_paper_id: int
    exam_paper_item_id: int
    item_order: int
    exam_mode: str
    exam_status: str
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    answered_at: datetime | None = None
    user_answer: str
    correct_answer: str
    is_correct: bool | None = None
    score_obtained: float | None = None
    score_max: float | None = None
    error_cause_label: str | None = None
    feedback_text: str | None = None
    created_at: datetime


class QuestionTypeRegistryItemResponse(BaseModel):
    id: int
    type_key: str
    display_name: str
    scope: str
    course_id: str
    description: str
    answer_format: str
    grading_method: str
    option_schema: dict[str, Any] = Field(default_factory=dict)
    rubric: dict[str, Any] = Field(default_factory=dict)
    source: str
    confidence: float
    is_system: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ExamNodeLinkResponse(BaseModel):
    knowledge_unit_id: int
    knowledge_unit_name: str
    coverage_weight: float
    mastery_score: float | None = None


class ExamPaperItemResponse(BaseModel):
    id: int
    item_order: int
    question_template_id: int
    question_type: str
    difficulty: str
    stem: str
    options: list[str] | None = None
    correct_answer: str | None = None
    explanation: str
    knowledge_unit_links: list[ExamNodeLinkResponse] = Field(default_factory=list)
    selection_context: dict[str, Any] = Field(default_factory=dict)
    user_answer: str | None = None
    is_correct: bool | None = None
    score_obtained: float | None = None
    score_max: float | None = None
    error_cause_label: str | None = None
    is_marked: bool = False


class ExamPaperDetailResponse(BaseModel):
    id: int
    course_id: str
    user_id: str
    exam_mode: str
    status: str
    total_items: int
    score_obtained: float | None = None
    total_score: float | None = None
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    created_at: datetime
    selection_context: dict[str, Any] = Field(default_factory=dict)
    paper_preview: PaperPreview = Field(default_factory=PaperPreview)
    items: list[ExamPaperItemResponse] = Field(default_factory=list)
