"""Assessment and learning-state models."""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, Index, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class QuestionTemplate(SQLModel, table=True):
    """Question template tied to a teaching unit and curriculum version."""

    __tablename__ = "question_template"
    __table_args__ = (
        UniqueConstraint(
            "subject_id",
            "teaching_unit_id",
            "stem_hash",
            name="uq_question_template_stem",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    teaching_unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    curriculum_version_id: int | None = Field(default=None, foreign_key="curriculum_version.id", index=True)
    question_type: str = Field(index=True)
    difficulty: str = Field(index=True)
    stem: str
    stem_hash: str = Field(index=True)
    options: str | None = Field(default=None)
    answer: str
    explanation: str = Field(default="")
    template_version: int = Field(default=1, ge=1)
    status: str = Field(default="active")
    source_snapshot_id: int | None = Field(
        default=None,
        foreign_key="curriculum_snapshot.id",
        index=True,
    )
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class QuestionTemplateNodeLink(SQLModel, table=True):
    """Knowledge-node coverage for a template."""

    __tablename__ = "question_template_node_link"
    __table_args__ = (
        UniqueConstraint(
            "question_template_id",
            "knowledge_node_id",
            name="uq_question_template_node_link",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    question_template_id: int = Field(foreign_key="question_template.id", index=True)
    knowledge_node_id: int = Field(foreign_key="knowledge_node.id", index=True)
    coverage_weight: float = Field(default=1.0, ge=0.0)
    role: str = Field(default="primary")
    created_at: datetime = Field(default_factory=utcnow)


class ExamPaper(SQLModel, table=True):
    """Generated exam paper."""

    __tablename__ = "exam_paper"

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    exam_mode: str = Field(index=True)
    curriculum_version_id: int | None = Field(default=None, foreign_key="curriculum_version.id", index=True)
    metadata_json: str = Field(default="{}")
    status: str = Field(default="draft", index=True)
    total_items: int = Field(default=0, ge=0)
    submitted_at: datetime | None = Field(default=None)
    graded_at: datetime | None = Field(default=None)
    total_score: float | None = Field(default=None, ge=0.0)
    score_obtained: float | None = Field(default=None, ge=0.0)
    duration_seconds: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ExamPaperItem(SQLModel, table=True):
    """Exam item snapshot."""

    __tablename__ = "exam_paper_item"
    __table_args__ = (
        UniqueConstraint("exam_paper_id", "item_order", name="uq_exam_paper_item_order"),
    )

    id: int | None = Field(default=None, primary_key=True)
    exam_paper_id: int = Field(foreign_key="exam_paper.id", index=True)
    question_template_id: int = Field(foreign_key="question_template.id", index=True)
    item_order: int = Field(ge=1)
    snapshot_stem: str
    snapshot_options: str | None = Field(default=None)
    snapshot_answer: str
    snapshot_explanation: str = Field(default="")
    snapshot_teaching_unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    snapshot_node_links_json: str = Field(default="[]")
    snapshot_difficulty: str
    snapshot_question_type: str
    created_at: datetime = Field(default_factory=utcnow)


class UserAnswerAttempt(SQLModel, table=True):
    """User answer attempt and grading result."""

    __tablename__ = "user_answer_attempt"
    __table_args__ = (
        UniqueConstraint(
            "exam_paper_item_id",
            "user_id",
            "attempt_no",
            name="uq_user_answer_attempt",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    exam_paper_item_id: int = Field(foreign_key="exam_paper_item.id", index=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    attempt_no: int = Field(default=1, ge=1)
    user_answer: str = Field(default="")
    is_correct: bool | None = Field(default=None)
    score_obtained: float | None = Field(default=None, ge=0.0)
    score_max: float | None = Field(default=None, ge=0.0)
    time_spent_seconds: int | None = Field(default=None, ge=0)
    hint_used: bool = Field(default=False)
    confidence_self_report: int | None = Field(default=None, ge=1, le=5)
    error_cause_label: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)


class UserKnowledgeState(SQLModel, table=True):
    """User mastery state."""

    __tablename__ = "user_knowledge_state"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "subject_id",
            "granularity",
            "target_id",
            name="uq_user_knowledge_state",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    granularity: str = Field(index=True)
    target_id: int = Field(index=True)
    mastery_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    stability_score: float = Field(default=0.0, ge=0.0, le=1.0)
    forgetting_due_at: datetime | None = Field(default=None)
    review_priority: float = Field(default=0.0)
    total_attempts: int = Field(default=0, ge=0)
    correct_attempts: int = Field(default=0, ge=0)
    last_attempt_at: datetime | None = Field(default=None)
    state_version: int = Field(default=1, ge=1)
    last_recomputed_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=utcnow)


class ReviewTask(SQLModel, table=True):
    """Scheduled review task."""

    __tablename__ = "review_task"
    __table_args__ = (
        Index(
            "ix_review_task_status_target",
            "user_id",
            "subject_id",
            "status",
            "target_granularity",
            "target_id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    subject_id: int = Field(foreign_key="subject.id", index=True)
    task_type: str = Field(index=True)
    target_id: int = Field(index=True)
    target_granularity: str = Field(index=True)
    priority: float = Field(default=0.0)
    scheduled_at: datetime
    status: str = Field(default="pending", index=True)
    interval_days: int = Field(default=1, ge=1)
    ease_factor: float = Field(default=2.5, ge=1.3)
    repetition_count: int = Field(default=0, ge=0)
    reason: str | None = Field(default=None)
    source_state_id: int | None = Field(default=None, foreign_key="user_knowledge_state.id", index=True)
    source_exam_paper_id: int | None = Field(default=None, foreign_key="exam_paper.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = Field(default=None)
    expired_at: datetime | None = Field(default=None)


class ExamPaperGenerationContext(SQLModel, table=True):
    """Exam generation context payload."""

    __tablename__ = "exam_paper_generation_context"

    id: int | None = Field(default=None, primary_key=True)
    exam_paper_id: int = Field(foreign_key="exam_paper.id", unique=True, index=True)
    selection_reason_json: str = Field(default="{}")
    target_theme_tree_node_id: int | None = Field(default=None, foreign_key="theme_tree_node.id")
    weakness_state_ids_json: str = Field(default="[]")
    review_task_ids_json: str = Field(default="[]")
    excluded_template_ids_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=utcnow)
