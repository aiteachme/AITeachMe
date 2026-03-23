"""Profile API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams
from app.schemas.enums import QuestionTypeValue


class ProfileListRequest(PageParams):
    """Legacy profile list request."""


class ProfileReportRequest(BaseModel):
    """Legacy profile report request."""

    model_config = ConfigDict(json_schema_extra={"example": {}})


class ProfileMistakesRequest(PageParams):
    """Legacy profile mistakes request."""


class ProfileItem(BaseModel):
    """Legacy knowledge point profile item."""

    knowledge_point: str = Field(description="Knowledge point.")
    mastery: float | None = Field(default=None, description="Mastery score in [0,1].", ge=0, le=1)
    attempts: int = Field(description="Attempt count.", ge=0)
    correct: int = Field(description="Correct count.", ge=0)


class ReportData(BaseModel):
    """Legacy profile report data."""

    overall_mastery: float | None = Field(default=None, description="Overall mastery.", ge=0, le=1)
    weak_points_top5: list[ProfileItem] = Field(default_factory=list, description="Top 5 weak points.")
    suggestions: list[str] = Field(default_factory=list, description="Suggestions.")


class MistakeItem(BaseModel):
    """Legacy mistake item."""

    id: int = Field(description="Mistake ID.")
    question_stem: str = Field(description="Question stem.")
    question_type: QuestionTypeValue = Field(description="Question type.")
    user_answer: str = Field(description="User answer.")
    correct_answer: str = Field(description="Correct answer.")
    analysis: str = Field(description="Error analysis.")
    knowledge_point: str = Field(description="Knowledge point.")
    created_at: datetime = Field(description="Created at.")


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
