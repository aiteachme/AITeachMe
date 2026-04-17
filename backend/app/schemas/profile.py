"""Profile API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.workflows.profile.subject_profile import SubjectProfileSummary
from app.workflows.profile.user_profile import UserProfileSummary


class MasteryStateResponse(BaseModel):
    id: int
    knowledge_unit_id: int
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
    weak_knowledge_unit_count: int
    knowledge_unit_states: list[MasteryStateResponse] = Field(default_factory=list)
    subject_profile: SubjectProfileSummary | None = None
    user_profile: UserProfileSummary | None = None


class ReviewTaskResponse(BaseModel):
    id: int
    user_id: str
    subject: str
    knowledge_unit_id: int
    priority: float
    scheduled_at: datetime | None = None
    status: str
    interval_days: int
    ease_factor: float
    repetition_count: int
    reason: str | None = None
    source_exam_paper_id: int | None = None
    updated_at: datetime
