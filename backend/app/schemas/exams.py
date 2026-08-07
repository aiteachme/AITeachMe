"""Exam API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExamGenerateRequest(BaseModel):
    """Trigger exam generation request."""

    exam_mode: str = Field(description="Exam mode: web_practice | paper_exam. Mastery drills use their dedicated API.")
    user_prompt: str | None = Field(default=None, description="Optional user requirements for exam generation.")
    sample_file_ids: list[str] | None = Field(default=None, description="Optional uploaded sample-paper file IDs.")
    num_questions: int | None = Field(default=None, ge=1, le=200, description="Optional target question count.")
    paper_layout_mode: str | None = Field(
        default=None,
        description="Optional paper layout mode for paper_exam: auto | standard_two_page | gaokao_four_page | gaokao_six_page | gaokao_eight_page.",
    )


class ExamSubmitAnswerItem(BaseModel):
    """One submitted answer item."""

    exam_paper_item_id: int | None = Field(default=None, description="Exam paper item ID.")
    item_order: int | None = Field(default=None, ge=1, description="Fallback key: item order.")
    answer: str = Field(description="User answer.")


class ExamSubmitRequest(BaseModel):
    """Submit exam answers request."""

    answers: list[ExamSubmitAnswerItem] = Field(default_factory=list, description="Submitted answers.")
    submission_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="Stable client-generated key used to safely retry this submission.",
    )


class MasteryDrillStartRequest(BaseModel):
    """Start a new durable drill or resume the active one for the course."""

    session_key: str = Field(min_length=1, max_length=128)
    question_template_ids: list[int] = Field(min_length=1, max_length=80)
    configured_question_count: int = Field(ge=1, le=80)
    configured_question_types: list[str] = Field(default_factory=list, max_length=20)


class MasteryDrillAttemptRequest(BaseModel):
    """Persist and grade one answer attempt."""

    exam_paper_item_id: int = Field(ge=1)
    answer: str = Field(max_length=20000)
    attempt_key: str = Field(min_length=1, max_length=128)
    time_spent_seconds: int | None = Field(default=None, ge=0, le=86400)
    hint_used: bool = False
    confidence_self_report: int | None = Field(default=None, ge=1, le=5)


class MasteryDrillCompleteRequest(BaseModel):
    """Idempotently finish a drill after every item has been passed."""

    completion_key: str = Field(min_length=1, max_length=128)
    duration_seconds: int | None = Field(default=None, ge=0, le=604800)


class QuestionTemplateMarkRequest(BaseModel):
    """Update whether a question template is marked as a favorite."""

    is_marked: bool = Field(description="Whether the question template is marked.")


class QuestionTemplateMarkResponse(BaseModel):
    question_template_id: int
    is_marked: bool


class QuestionTemplateGradeRequest(BaseModel):
    """Grade one answer against a question template."""

    answer: str = Field(description="Submitted answer.")


class QuestionTemplateGradeResponse(BaseModel):
    question_template_id: int
    question_type: str
    is_correct: bool
    score_obtained: float
    score_max: float
    feedback_text: str
    error_cause_label: str | None = None
    grading_mode: Literal["objective_rule", "subjective_llm", "subjective_fallback"]
    correct_answer: str


class MasteryDrillAttemptResponse(BaseModel):
    id: int
    mastery_drill_session_id: int
    exam_paper_item_id: int
    question_template_id: int
    attempt_no: int
    attempt_key: str
    status: Literal["grading", "graded", "failed"]
    answer: str
    is_correct: bool | None = None
    score_obtained: float | None = None
    score_max: float | None = None
    feedback_text: str | None = None
    error_cause_label: str | None = None
    grading_mode: str | None = None
    time_spent_seconds: int | None = None
    hint_used: bool = False
    confidence_self_report: int | None = None
    error_code: str | None = None
    answered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MasteryDrillSessionResponse(BaseModel):
    id: int
    exam_paper_id: int
    status: Literal["active", "completed", "abandoned"]
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    total_attempts: int = 0
    wrong_attempts: int = 0
    started_at: datetime
    completed_at: datetime | None = None
    attempts: list[MasteryDrillAttemptResponse] = Field(default_factory=list)


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
    served_from_prepared: bool


class ExamPrewarmStatusResponse(BaseModel):
    status: Literal["ready", "preparing", "missing", "failed", "stale"]
    exam_mode: str
    num_questions: int
    prepared_at: datetime | None = None
    expires_at: datetime | None = None
    updated_at: datetime | None = None
    background_requested: bool = False
    error_message: str | None = None


class ExamProfileSyncResponse(BaseModel):
    exam_paper_id: int
    status: Literal[
        "not_tracked",
        "pending",
        "processing",
        "retry_wait",
        "completed",
        "failed",
    ]
    attempt_count: int = 0
    manual_retry_count: int = 0
    next_attempt_at: datetime | None = None
    last_error_code: str | None = None
    states_updated: int = 0
    review_task_count: int = 0
    can_retry: bool = False
    updated_at: datetime | None = None


class ExamGradeResponse(RuntimeStatusResponse):
    exam_paper_id: int
    score: float | None = None
    states_updated: int
    tasks_created: int
    mastery_consumed: bool
    profile_sync: ExamProfileSyncResponse | None = None


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


class ExamGenerationProgress(BaseModel):
    completed_items: int = Field(default=0, ge=0)
    generated_items: int = Field(default=0, ge=0)
    failed_items: int = Field(default=0, ge=0)
    total_items: int = Field(default=0, ge=0)


class MasteryDrillHistorySummary(BaseModel):
    status: Literal["active", "completed", "abandoned"]
    total_attempts: int = Field(default=0, ge=0)
    wrong_attempts: int = Field(default=0, ge=0)
    attempt_accuracy: float | None = Field(default=None, ge=0.0, le=1.0)


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
    updated_at: datetime
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    generation_progress: ExamGenerationProgress | None = None
    paper_preview: PaperPreview = Field(default_factory=PaperPreview)
    mastery_drill: MasteryDrillHistorySummary | None = None


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
    profile_sync: ExamProfileSyncResponse | None = None
    mastery_drill: MasteryDrillSessionResponse | None = None
    paper_preview: PaperPreview = Field(default_factory=PaperPreview)
    items: list[ExamPaperItemResponse] = Field(default_factory=list)
