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
            "subject",
            "knowledge_unit_id",
            "stem_hash",
            name="uq_template_subject_node_stem",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    knowledge_unit_id: int | None = Field(default=None, foreign_key="knowledge_unit.id", index=True)
    question_type: str
    difficulty: str
    stem: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    stem_hash: str = Field(index=True)
    options_json: str | None = Field(default=None, sa_column=sa.Column(sa.Text(), nullable=True))
    answer: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    explanation: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    knowledge_unit_refs_json: str = Field(default="[]", sa_column=sa.Column(sa.Text(), nullable=False, default="[]"))
    selection_hints_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False, default="{}"))
    template_version: int = Field(default=1, ge=1)
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class QuestionTypeRegistry(SQLModel, table=True):
    """Question type definition available to exam generation and grading."""

    __tablename__ = "question_type_registry"
    __table_args__ = (
        UniqueConstraint("scope", "subject", "type_key", name="uq_question_type_scope_subject_key"),
    )

    id: int | None = Field(default=None, primary_key=True)
    type_key: str = Field(index=True)
    display_name: str
    scope: str = Field(default="global", index=True)
    subject: str = Field(default="", index=True)
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
    subject: str = Field(index=True)
    user_id: str = Field(default="local", index=True)
    exam_mode: str
    status: str = Field(default="draft", index=True)
    total_items: int = Field(default=0, ge=0)
    submitted_at: datetime | None = Field(default=None)
    graded_at: datetime | None = Field(default=None)
    total_score: float | None = Field(default=None, ge=0.0)
    score_obtained: float | None = Field(default=None, ge=0.0)
    duration_seconds: int | None = Field(default=None, ge=0)
    selection_context_json: str = Field(default="{}", sa_column=sa.Column(sa.Text(), nullable=False, default="{}"))
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
    knowledge_unit_id: int | None = Field(default=None, foreign_key="knowledge_unit.id", index=True)
    knowledge_unit_refs_json: str = Field(default="[]", sa_column=sa.Column(sa.Text(), nullable=False, default="[]"))
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
