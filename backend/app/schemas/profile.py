"""画像相关 Schema — ProfileResponse、ReportResponse、MistakeListResponse"""

from datetime import datetime
from pydantic import BaseModel


class ProfileItem(BaseModel):
    knowledge_point: str
    mastery: float | None = None
    attempts: int
    correct: int


class ProfileResponse(BaseModel):
    items: list[ProfileItem]
    total: int


class ReportResponse(BaseModel):
    overall_mastery: float | None = None
    weak_points_top5: list[ProfileItem]
    suggestions: list[str]


class MistakeItem(BaseModel):
    id: int
    question_stem: str
    question_type: str
    user_answer: str
    correct_answer: str
    analysis: str
    knowledge_point: str
    created_at: datetime


class MistakeListResponse(BaseModel):
    items: list[MistakeItem]
    total: int
