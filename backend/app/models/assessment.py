"""测评与掌握度层数据模型。"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, Index, SQLModel, UniqueConstraint


class QuestionTemplate(SQLModel, table=True):
    """题目模板。"""

    __tablename__ = "question_template"
    __table_args__ = (
        UniqueConstraint(
            "subject",
            "teaching_unit_id",
            "stem_hash",
            name="uq_template_subject_unit_stem",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    teaching_unit_id: int = Field(foreign_key="teaching_unit.id", index=True)
    question_type: str  # QuestionType
    difficulty: str  # Difficulty
    stem: str
    stem_hash: str = Field(index=True)
    options: str | None = Field(default=None)  # JSON 字符串；SINGLE_CHOICE 时应非空
    answer: str
    explanation: str
    template_version: int = Field(default=1, ge=1)
    status: str = Field(default="active")  # QuestionTemplateStatus
    source_snapshot_id: int | None = Field(
        default=None,
        foreign_key="curriculum_snapshot.id",
        index=True,
    )
    created_by_job_id: int | None = Field(
        default=None,
        foreign_key="question_build_job.id",
        index=True,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class QuestionTemplateNodeLink(SQLModel, table=True):
    """题目模板与知识节点关联。"""

    __tablename__ = "question_template_node_link"
    __table_args__ = (
        UniqueConstraint(
            "question_template_id",
            "knowledge_node_id",
            name="uq_template_node_link",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    question_template_id: int = Field(
        foreign_key="question_template.id",
        index=True,
    )
    knowledge_node_id: int = Field(
        foreign_key="knowledge_node.id",
        index=True,
    )
    coverage_weight: float = Field(default=1.0, ge=0.0)
    role: str = Field(default="primary")  # TemplateNodeRole
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExamPaper(SQLModel, table=True):
    """试卷。"""

    __tablename__ = "exam_paper"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    user_id: str = Field(default="local", index=True)
    exam_mode: str  # ExamMode
    curriculum_snapshot_id: int = Field(
        foreign_key="curriculum_snapshot.id",
        index=True,
    )
    status: str = Field(default="draft", index=True)  # ExamPaperStatus
    total_items: int = Field(default=0, ge=0)
    submitted_at: datetime | None = Field(default=None)
    graded_at: datetime | None = Field(default=None)
    total_score: float | None = Field(default=None, ge=0.0)
    score_obtained: float | None = Field(default=None, ge=0.0)
    duration_seconds: int | None = Field(default=None, ge=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExamPaperItem(SQLModel, table=True):
    """试卷题目条目（带快照）。"""

    __tablename__ = "exam_paper_item"
    __table_args__ = (
        UniqueConstraint(
            "exam_paper_id",
            "item_order",
            name="uq_paper_item_order",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    exam_paper_id: int = Field(foreign_key="exam_paper.id", index=True)
    question_template_id: int = Field(
        foreign_key="question_template.id",
        index=True,
    )
    item_order: int = Field(ge=1)
    snapshot_stem: str
    snapshot_options: str | None = Field(default=None)  # JSON 字符串
    snapshot_answer: str
    snapshot_explanation: str
    snapshot_teaching_unit_id: int
    snapshot_node_links_json: str = Field(default="[]")
    snapshot_difficulty: str
    snapshot_question_type: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserAnswerAttempt(SQLModel, table=True):
    """用户作答记录。"""

    __tablename__ = "user_answer_attempt"
    __table_args__ = (
        UniqueConstraint(
            "exam_paper_item_id",
            "user_id",
            "attempt_no",
            name="uq_attempt_item_user_attempt",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    exam_paper_item_id: int = Field(
        foreign_key="exam_paper_item.id",
        index=True,
    )
    user_id: str = Field(default="local", index=True)
    attempt_no: int = Field(default=1, ge=1)
    user_answer: str
    is_correct: bool | None = Field(default=None)
    score_obtained: float | None = Field(default=None, ge=0.0)
    score_max: float | None = Field(default=None, ge=0.0)
    time_spent_seconds: int | None = Field(default=None, ge=0)
    hint_used: bool = Field(default=False)
    confidence_self_report: int | None = Field(default=None, ge=1, le=5)
    error_cause_label: str | None = Field(default=None)  # ErrorCauseLabel
    created_at: datetime = Field(default_factory=datetime.utcnow)


class UserKnowledgeState(SQLModel, table=True):
    """用户知识状态（unit / node 双粒度）。"""

    __tablename__ = "user_knowledge_state"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "subject",
            "granularity",
            "target_id",
            name="uq_knowledge_state",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(default="local", index=True)
    subject: str = Field(index=True)
    granularity: str  # MasteryGranularity
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
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ReviewTask(SQLModel, table=True):
    """复习任务。"""

    __tablename__ = "review_task"
    __table_args__ = (
        Index(
            "ix_review_task_target_status",
            "user_id",
            "subject",
            "target_id",
            "target_granularity",
            "status",
        ),
    )
    # NOTE:
    # 目标部分唯一索引（后续在数据库初始化阶段显式 DDL 创建）:
    #   uq_review_task_pending
    #   ON (user_id, subject, target_id, target_granularity)
    #   WHERE status='pending'

    id: int | None = Field(default=None, primary_key=True)
    user_id: str = Field(default="local", index=True)
    subject: str = Field(index=True)
    task_type: str  # ReviewTaskType
    target_id: int = Field(index=True)
    target_granularity: str  # MasteryGranularity
    priority: float = Field(default=0.0)
    scheduled_at: datetime
    status: str = Field(default="pending", index=True)  # ReviewTaskStatus
    interval_days: int = Field(default=1, ge=1)
    ease_factor: float = Field(default=2.5, ge=1.3)
    repetition_count: int = Field(default=0, ge=0)
    reason: str | None = Field(default=None)  # WeaknessReason
    source_state_id: int | None = Field(
        default=None,
        foreign_key="user_knowledge_state.id",
        index=True,
    )
    source_exam_paper_id: int | None = Field(
        default=None,
        foreign_key="exam_paper.id",
        index=True,
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = Field(default=None)
    expired_at: datetime | None = Field(default=None)


class ExamPaperGenerationContext(SQLModel, table=True):
    """组卷决策上下文。"""

    __tablename__ = "exam_paper_generation_context"

    id: int | None = Field(default=None, primary_key=True)
    exam_paper_id: int = Field(
        foreign_key="exam_paper.id",
        unique=True,
        index=True,
    )
    selection_reason_json: str = Field(default="{}")
    target_theme_tree_node_id: int | None = Field(
        default=None,
        foreign_key="theme_tree_node.id",
    )
    weakness_state_ids_json: str = Field(default="[]")
    review_task_ids_json: str = Field(default="[]")
    excluded_template_ids_json: str = Field(default="[]")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class QuestionBuildJob(SQLModel, table=True):
    """题目构建任务。"""

    __tablename__ = "question_build_job"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    target_unit_ids_json: str = Field(default="[]")
    questions_per_unit: int = Field(default=9, ge=1)
    status: str = Field(default="pending", index=True)  # AsyncJobStatus
    progress: int = Field(default=0, ge=0, le=100)
    templates_created: int = Field(default=0, ge=0)
    warnings_json: str = Field(default="[]")
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExamGenerateJob(SQLModel, table=True):
    """组卷任务。"""

    __tablename__ = "exam_generate_job"

    id: int | None = Field(default=None, primary_key=True)
    subject: str = Field(index=True)
    user_id: str = Field(default="local", index=True)
    exam_mode: str  # ExamMode
    num_questions: int = Field(ge=1)
    status: str = Field(default="pending", index=True)  # AsyncJobStatus
    exam_paper_id: int | None = Field(
        default=None,
        foreign_key="exam_paper.id",
        index=True,
    )
    theme_tree_node_id: int | None = Field(
        default=None,
        foreign_key="theme_tree_node.id",
    )
    teaching_unit_ids_json: str = Field(default="[]")
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ExamGradeJob(SQLModel, table=True):
    """判卷任务。"""

    __tablename__ = "exam_grade_job"
    __table_args__ = (
        Index("ix_exam_grade_job_paper_status", "exam_paper_id", "status"),
    )
    # NOTE:
    # 目标部分唯一索引（后续在数据库初始化阶段显式 DDL 创建）:
    #   uq_grade_job_active
    #   ON (exam_paper_id)
    #   WHERE status IN ('pending', 'running')

    id: int | None = Field(default=None, primary_key=True)
    exam_paper_id: int = Field(foreign_key="exam_paper.id", index=True)
    status: str = Field(default="pending", index=True)  # AsyncJobStatus
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    states_updated: int = Field(default=0, ge=0)
    tasks_created: int = Field(default=0, ge=0)
    error_message: str | None = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
