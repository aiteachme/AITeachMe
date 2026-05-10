"""Profile API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MasteryStateResponse(BaseModel):
    id: int
    knowledge_unit_id: int
    knowledge_unit_name: str | None = None
    knowledge_unit_type: str | None = None
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


class CourseProfileSummary(BaseModel):
    course_id: str
    generated_at: datetime
    avg_mastery: float | None = None
    weak_knowledge_unit_count: int = 0
    pending_review_count: int = 0
    due_review_count: int = 0
    preferred_question_types: list[str] = Field(default_factory=list)
    recommended_question_types: list[str] = Field(default_factory=list)
    recommended_exam_mode: str = "web_practice"
    recommended_question_count: int | None = None
    difficulty_focus: str = "medium"
    focus_knowledge_unit_ids: list[int] = Field(default_factory=list)
    question_type_accuracy: dict[str, float] = Field(default_factory=dict)
    difficulty_accuracy: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class UserProfileSummary(BaseModel):
    user_id: str
    generated_at: datetime
    active_course_count: int = 0
    active_course_ids: list[str] = Field(default_factory=list)
    recent_course_ids: list[str] = Field(default_factory=list)
    preferred_question_types: list[str] = Field(default_factory=list)
    preferred_exam_modes: list[str] = Field(default_factory=list)
    dominant_exam_mode: str = "web_practice"
    explanation_style: str = "balanced"
    pace_preference: str = "steady"
    consistency_level: str = "building"
    pending_review_count: int = 0
    due_review_count: int = 0
    notes: list[str] = Field(default_factory=list)


class MasteryOverviewResponse(BaseModel):
    course_id: str
    user_id: str
    weak_knowledge_unit_count: int
    knowledge_unit_states: list[MasteryStateResponse] = Field(default_factory=list)
    course_profile: CourseProfileSummary | None = None
    user_profile: UserProfileSummary | None = None


class StudyPlanStepResponse(BaseModel):
    key: str
    title: str
    detail: str
    action: str
    priority: int
    source: str


class ReviewTaskResponse(BaseModel):
    id: int
    user_id: str
    course_id: str
    knowledge_unit_id: int
    knowledge_unit_name: str | None = None
    knowledge_unit_type: str | None = None
    priority: float
    scheduled_at: datetime | None = None
    status: str
    interval_days: int
    ease_factor: float
    repetition_count: int
    reason: str | None = None
    source_exam_paper_id: int | None = None
    updated_at: datetime
