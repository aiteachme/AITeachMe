"""Exam API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class QuestionTypeSelection(BaseModel):
    """One built-in type or installed package, with optional version and quota."""

    model_config = ConfigDict(extra="forbid")

    question_type: Literal["single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer"] | None = None
    registry_id: int | None = Field(default=None, ge=1)
    version_id: int | None = Field(default=None, ge=1)
    count: int | None = Field(default=None, ge=1, le=200)

    @model_validator(mode="after")
    def validate_reference(self) -> "QuestionTypeSelection":
        if (self.question_type is None) == (self.registry_id is None):
            raise ValueError("每个题型选择须指定 question_type 或 registry_id，不能同时指定。")
        if self.version_id is not None and self.registry_id is None:
            raise ValueError("只有自定义题型可以指定 version_id。")
        return self


def _validate_selection_request(request: Any) -> None:
    selections = request.question_type_selections
    if not selections:
        return
    if request.question_types or request.question_type_registry_ids:
        raise ValueError("question_type_selections 不能与旧题型选择字段同时使用。")
    identities = [(item.question_type, item.registry_id) for item in selections]
    if len(set(identities)) != len(identities):
        raise ValueError("同一题型不能重复选择或同时选择多个版本。")
    counts = [item.count for item in selections]
    if any(count is not None for count in counts) and not all(count is not None for count in counts):
        raise ValueError("指定数量时，须为每个题型提供 count。")


class ExamGenerateRequest(BaseModel):
    """Trigger exam generation request."""

    exam_mode: str = Field(
        description=(
            "Exam mode: web_practice | paper_exam. Mastery drills are assembled client-side "
            "after the server ensures the reusable question bank can satisfy the saved config."
        )
    )
    user_prompt: str | None = Field(default=None, description="Optional user requirements for exam generation.")
    sample_file_ids: list[str] | None = Field(default=None, description="Optional uploaded sample-paper file IDs.")
    num_questions: int | None = Field(default=None, ge=1, le=200, description="Optional target question count.")
    question_types: list[
        Literal["single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer"]
    ] = Field(
        default_factory=list,
        max_length=5,
        description="Optional allowed question types. Empty means automatic type planning.",
    )
    question_type_registry_ids: list[int] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Optional course custom-question-type registry IDs. They can be combined with "
            "built-in question_types; the server freezes the resolved versions for this run."
        ),
    )
    question_type_selections: list[QuestionTypeSelection] = Field(default_factory=list, max_length=25)
    difficulty: Literal["auto", "easy", "medium", "hard"] = Field(
        default="auto",
        description="Optional overall difficulty preference. Auto lets the planner choose per question.",
    )
    paper_layout_mode: str | None = Field(
        default=None,
        description="Optional paper layout mode for paper_exam: auto | standard_two_page | gaokao_four_page | gaokao_six_page | gaokao_eight_page.",
    )

    @model_validator(mode="after")
    def validate_selection(self) -> "ExamGenerateRequest":
        _validate_selection_request(self)
        return self

class ExamSubmitAnswerItem(BaseModel):
    """One submitted answer item."""

    exam_paper_item_id: int | None = Field(default=None, description="Exam paper item ID.")
    item_order: int | None = Field(default=None, ge=1, description="Fallback key: item order.")
    answer: str | None = Field(default=None, max_length=20000, description="Legacy plain-text answer.")
    answer_payload: dict[str, str] | None = Field(
        default=None,
        description="Structured answer keyed by the frozen answer schema.",
    )

    @model_validator(mode="after")
    def require_one_answer_shape(self) -> "ExamSubmitAnswerItem":
        if self.answer is None and self.answer_payload is None:
            raise ValueError("必须提供 answer 或 answer_payload。")
        if self.answer is not None and self.answer_payload is not None:
            raise ValueError("answer 与 answer_payload 不能同时提供。")
        return self


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
    """Legacy payload retained for the disabled durable mastery-drill endpoint."""

    session_key: str = Field(min_length=1, max_length=128)
    question_template_ids: list[int] = Field(min_length=1, max_length=80)
    configured_question_count: int = Field(ge=1, le=80)
    configured_question_types: list[str] = Field(default_factory=list, max_length=20)


class MasteryDrillPrepareRequest(BaseModel):
    """Prepare an ephemeral mastery drill from the reusable question bank."""

    num_questions: int = Field(ge=1, le=80)
    question_types: list[
        Literal["single_choice", "multiple_choice", "true_false", "fill_blank", "short_answer"]
    ] = Field(
        default_factory=list,
        max_length=5,
        description="Allowed question types. Empty means an automatic mix.",
    )
    question_type_registry_ids: list[int] = Field(
        default_factory=list,
        max_length=20,
        description="Optional course custom-question-type registry IDs; can be mixed with built-in types.",
    )
    question_type_selections: list[QuestionTypeSelection] = Field(default_factory=list, max_length=25)

    @model_validator(mode="after")
    def validate_selection(self) -> "MasteryDrillPrepareRequest":
        _validate_selection_request(self)
        return self


class MasteryDrillAttemptRequest(BaseModel):
    """Legacy payload retained for the disabled mastery-drill attempt endpoint."""

    exam_paper_item_id: int = Field(ge=1)
    answer: str = Field(max_length=20000)
    attempt_key: str = Field(min_length=1, max_length=128)
    time_spent_seconds: int | None = Field(default=None, ge=0, le=86400)
    hint_used: bool = False
    confidence_self_report: int | None = Field(default=None, ge=1, le=5)


class MasteryDrillCompleteRequest(BaseModel):
    """Legacy payload retained for the disabled mastery-drill completion endpoint."""

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

    answer: str | None = Field(default=None, max_length=20000, description="Legacy plain-text answer.")
    answer_payload: dict[str, str] | None = Field(
        default=None,
        description="Structured answer keyed by the frozen answer schema.",
    )
    ephemeral: bool = Field(
        default=False,
        description="Whether this one-time grading result must skip analytics recording.",
    )

    @model_validator(mode="after")
    def require_one_answer_shape(self) -> "QuestionTemplateGradeRequest":
        if self.answer is None and self.answer_payload is None:
            raise ValueError("必须提供 answer 或 answer_payload。")
        if self.answer is not None and self.answer_payload is not None:
            raise ValueError("answer 与 answer_payload 不能同时提供。")
        return self


class QuestionTemplateGradeResponse(BaseModel):
    question_template_id: int
    question_type: str
    is_correct: bool
    score_obtained: float
    score_max: float
    feedback_text: str
    error_cause_label: str | None = None
    grading_mode: Literal[
        "objective_rule",
        "subjective_llm",
        "subjective_fallback",
        "custom_rubric_llm",
    ]
    correct_answer: str
    grading_detail: dict[str, Any] = Field(default_factory=dict)


class MasteryDrillAttemptResponse(BaseModel):
    id: int
    mastery_drill_session_id: int
    exam_paper_item_id: int
    question_template_id: int
    attempt_no: int
    attempt_key: str
    status: Literal["grading", "graded", "failed"]
    answer: str
    answer_payload: dict[str, str] = Field(default_factory=dict)
    is_correct: bool | None = None
    score_obtained: float | None = None
    score_max: float | None = None
    feedback_text: str | None = None
    error_cause_label: str | None = None
    grading_mode: str | None = None
    grading_detail: dict[str, Any] = Field(default_factory=dict)
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
    paper_attempts: int = Field(default=0, ge=0)
    paper_correct_attempts: int = Field(default=0, ge=0)
    paper_score_obtained: float = Field(default=0.0, ge=0.0)
    paper_score_max: float = Field(default=0.0, ge=0.0)
    paper_score_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    mastery_score: float | None = Field(
        default=None,
        description="Cumulative profile mastery retained for personalization; not the paper metric.",
    )
    reason: str


class ExamStudyGuideResponse(BaseModel):
    schema_version: Literal[2] = 2
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
    question_type_registry_id: int | None = None
    question_type_version_id: int | None = None
    renderer_key: str | None = None
    public_payload: dict[str, Any] = Field(default_factory=dict)
    answer_schema: dict[str, Any] = Field(default_factory=dict)
    profile_eligible: bool = True
    created_at: datetime
    updated_at: datetime


class MasteryDrillPrepareResponse(BaseModel):
    requested_count: int
    available_count: int
    generated_count: int
    question_type_counts: dict[str, int] = Field(default_factory=dict)
    templates: list[QuestionTemplateItemResponse] = Field(default_factory=list)


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
    user_answer_payload: dict[str, str] = Field(default_factory=dict)
    grading_detail: dict[str, Any] = Field(default_factory=dict)
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
    question_type_registry_id: int | None = None
    question_type_version_id: int | None = None
    renderer_key: str | None = None
    public_payload: dict[str, Any] = Field(default_factory=dict)
    answer_schema: dict[str, Any] = Field(default_factory=dict)
    user_answer_payload: dict[str, str] = Field(default_factory=dict)
    grading_detail: dict[str, Any] = Field(default_factory=dict)
    grading_status: str = "pending"
    grading_error_code: str = ""
    profile_eligible: bool = True


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
