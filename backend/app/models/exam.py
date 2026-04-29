"""Active exam-domain data models."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel, UniqueConstraint

from app.utils.time import utcnow


class QuestionTemplate(SQLModel, table=True):
    """Reusable question template derived from knowledge-node scope."""

    __tablename__ = "question_template"
    __table_args__ = (
        UniqueConstraint(
            "subject_id",
            "stem_hash",
            name="uq_template_subject_stem",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject_id: str = Field(foreign_key="subject.id", index=True)
    question_type: str
    difficulty: str
    stem: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    stem_hash: str = Field(index=True)
    options_json: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    answer: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    explanation: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    selection_hints_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False, default="{}"))
    template_version: int = Field(default=1, ge=1)
    status: str = Field(default="active")
    is_marked: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class QuestionTypeRegistry(SQLModel, table=True):
    """Question type definition available to exam generation and grading."""

    __tablename__ = "question_type_registry"
    __table_args__ = (
        UniqueConstraint("scope", "subject_id", "type_key", name="uq_question_type_scope_subject_key"),
    )

    id: int | None = Field(default=None, primary_key=True)
    type_key: str = Field(index=True)
    display_name: str
    scope: str = Field(default="global", index=True)
    subject_id: str = Field(default="", index=True)
    description: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False, default=""))
    answer_format: str = Field(default="")
    grading_method: str = Field(default="llm")
    option_schema_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False, default="{}"))
    rubric_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False, default="{}"))
    source: str = Field(default="system")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    is_system: bool = Field(default=True, index=True)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ExamPaper(SQLModel, table=True):
    """Generated exam paper for one subject and one user."""

    __tablename__ = "exam_paper"

    id: int | None = Field(default=None, primary_key=True)
    subject_id: str = Field(foreign_key="subject.id", index=True)
    user_id: str = Field(default="local", index=True)
    exam_mode: str
    status: str = Field(default="draft", index=True)
    visibility: str = Field(default="visible", index=True)
    generation_origin: str = Field(default="user", index=True)
    config_hash: str = Field(default="", index=True)
    config_snapshot_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False, default="{}"))
    total_items: int = Field(default=0, ge=0)
    submitted_at: datetime | None = Field(default=None)
    graded_at: datetime | None = Field(default=None)
    total_score: float | None = Field(default=None, ge=0.0)
    score_obtained: float | None = Field(default=None, ge=0.0)
    duration_seconds: int | None = Field(default=None, ge=0)
    selection_context_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False, default="{}"))
    paper_preview_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False, default="{}"))
    prepared_at: datetime | None = Field(default=None, index=True)
    claimed_at: datetime | None = Field(default=None, index=True)
    expires_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ExamPaperItem(SQLModel, table=True):
    """Snapshot question item that belongs to an exam paper."""

    __tablename__ = "exam_paper_item"
    __table_args__ = (
        UniqueConstraint("exam_paper_id", "item_order", name="uq_paper_item_order"),
    )

    id: int | None = Field(default=None, primary_key=True)
    exam_paper_id: int = Field(foreign_key="exam_paper.id", index=True)
    question_template_id: int = Field(foreign_key="question_template.id", index=True)
    item_order: int = Field(ge=1)
    stem_snapshot: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    options_snapshot_json: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    answer_snapshot: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    explanation_snapshot: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    selection_context_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False, default="{}"))
    difficulty: str
    question_type: str
    score: float = Field(default=1.0, ge=0.0)
    answer_content: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False, default=""))
    is_correct: bool | None = Field(default=None)
    score_obtained: float | None = Field(default=None, ge=0.0)
    score_max: float | None = Field(default=None, ge=0.0)
    time_spent_seconds: int | None = Field(default=None, ge=0)
    hint_used: bool = Field(default=False)
    confidence_self_report: int | None = Field(default=None, ge=1, le=5)
    error_cause_label: str | None = Field(default=None)
    feedback_text: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    answered_at: datetime | None = Field(default=None)
    graded_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class QuestionKnowledgeUnitLink(SQLModel, table=True):
    """Weighted many-to-many coverage between a question and knowledge units."""

    __tablename__ = "question_knowledge_unit_link"
    __table_args__ = (
        sa.CheckConstraint(
            "(question_template_id IS NOT NULL AND exam_paper_item_id IS NULL) "
            "OR (question_template_id IS NULL AND exam_paper_item_id IS NOT NULL)",
            name="ck_question_link_one_question_ref",
        ),
        UniqueConstraint(
            "question_template_id",
            "knowledge_unit_id",
            name="uq_question_template_knowledge_unit",
        ),
        UniqueConstraint(
            "exam_paper_item_id",
            "knowledge_unit_id",
            name="uq_exam_paper_item_knowledge_unit",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    question_template_id: int | None = Field(default=None, foreign_key="question_template.id", index=True)
    exam_paper_item_id: int | None = Field(default=None, foreign_key="exam_paper_item.id", index=True)
    knowledge_unit_id: int = Field(foreign_key="knowledge_unit.id", index=True)
    coverage_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ExamStudyGuideCache(SQLModel, table=True):
    """Persisted study guide generated after exam grading."""

    __tablename__ = "exam_study_guide_cache"
    __table_args__ = (
        UniqueConstraint("exam_paper_id", name="uq_exam_study_guide_paper"),
    )

    id: int | None = Field(default=None, primary_key=True)
    exam_paper_id: int = Field(foreign_key="exam_paper.id", index=True)
    subject_id: str = Field(foreign_key="subject.id", index=True)
    user_id: str = Field(default="local", index=True)
    status: str = Field(default="completed", index=True)
    guide_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False, default="{}"))
    error_message: str = Field(default="", sa_column=sa.Column(sa.Text(), nullable=False, default=""))
    generated_at: datetime | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
