"""Assessment API 请求/响应 Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import PageParams


class QuestionBuildRequest(BaseModel):
    """触发题目构建请求。"""

    unit_ids: list[int] = Field(min_length=1, description="目标教学单元 ID 列表。")
    questions_per_unit: int = Field(default=9, ge=1, le=50, description="每单元生成题数。")


class ExamGenerateRequest(BaseModel):
    """触发组卷请求。"""

    exam_mode: str = Field(description="考试模式。")
    user_prompt: str | None = Field(default=None, description="用户偏好提示，例如题型偏好、难度方向。")
    num_questions: int | None = Field(default=None, ge=1, le=200, description="可选：题目数量，默认由后端自动决定。")
    theme_tree_node_id: int | None = Field(default=None, description="兼容字段：可选主题树节点 ID。")
    teaching_unit_ids: list[int] | None = Field(default=None, description="兼容字段：可选教学单元范围。")


class ExamSubmitAnswerItem(BaseModel):
    """提交答案项。"""

    exam_paper_item_id: int | None = Field(default=None, description="试卷题目项 ID。")
    item_order: int | None = Field(default=None, ge=1, description="题目序号（兼容键）。")
    answer: str = Field(description="用户答案。")


class ExamSubmitRequest(BaseModel):
    """提交试卷请求。"""

    answers: list[ExamSubmitAnswerItem] = Field(default_factory=list, description="答案列表。")


class ExamGradeRequest(BaseModel):
    """触发判卷请求。"""

    regrade: bool = Field(default=False, description="是否允许已判分试卷重判。")


class ExamHistoryQuery(PageParams):
    """试卷历史分页请求。"""


class JobStatusResponse(BaseModel):
    """通用异步任务状态。"""

    id: int
    status: str
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class QuestionBuildJobStatusResponse(JobStatusResponse):
    subject: str
    target_unit_ids: list[int] = Field(default_factory=list)
    questions_per_unit: int
    progress: int
    templates_created: int
    warnings: list[str] = Field(default_factory=list)


class ExamGenerateJobStatusResponse(JobStatusResponse):
    subject: str
    user_id: str
    exam_mode: str
    num_questions: int
    exam_paper_id: int | None = None
    theme_tree_node_id: int | None = None
    teaching_unit_ids: list[int] = Field(default_factory=list)


class ExamGradeJobStatusResponse(JobStatusResponse):
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


class MasteryStateResponse(BaseModel):
    id: int
    granularity: str
    target_id: int
    mastery_score: float
    confidence_score: float
    stability_score: float
    forgetting_due_at: datetime | None = None
    review_priority: float
    total_attempts: int
    correct_attempts: int
    last_attempt_at: datetime | None = None
    state_version: int
    updated_at: datetime


class MasteryOverviewResponse(BaseModel):
    subject: str
    user_id: str
    weak_unit_count: int
    weak_node_count: int
    unit_states: list[MasteryStateResponse] = Field(default_factory=list)
    node_states: list[MasteryStateResponse] = Field(default_factory=list)


class ReviewTaskResponse(BaseModel):
    id: int
    user_id: str
    subject: str
    task_type: str
    target_id: int
    target_granularity: str
    priority: float
    scheduled_at: datetime
    status: str
    interval_days: int
    ease_factor: float
    repetition_count: int
    reason: str | None = None
    source_state_id: int | None = None
    source_exam_paper_id: int | None = None
    created_at: datetime
    completed_at: datetime | None = None
    expired_at: datetime | None = None
