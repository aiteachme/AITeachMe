"""Profile API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MasteryStateResponse(BaseModel):
    id: int
    target_kind: str
    teaching_unit_id: int | None = None
    knowledge_node_id: int | None = None
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
    target_kind: str
    teaching_unit_id: int | None = None
    knowledge_node_id: int | None = None
    priority: float
    scheduled_at: datetime | None = None
    status: str
    interval_days: int
    ease_factor: float
    repetition_count: int
    reason: str | None = None
    source_exam_paper_id: int | None = None
    updated_at: datetime
