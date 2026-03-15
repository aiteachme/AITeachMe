"""Schemas for profile mastery, report, and mistake-book APIs."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import QuestionTypeValue


class ProfileItem(BaseModel):
    """Single knowledge-point mastery record."""

    knowledge_point: str = Field(description="知识点名称。", examples=["条件概率"])
    mastery: float | None = Field(
        default=None,
        description="掌握度估计值，范围 0.0 到 1.0；无数据时为空。",
        ge=0,
        le=1,
    )
    attempts: int = Field(description="累计作答次数。", ge=0)
    correct: int = Field(description="累计答对次数。", ge=0)


class ProfileResponse(BaseModel):
    """Paginated response for profile mastery items."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "knowledge_point": "条件概率",
                        "mastery": 0.6,
                        "attempts": 5,
                        "correct": 3,
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[ProfileItem] = Field(description="当前分页内的掌握度记录。")
    total: int = Field(description="掌握度记录总数。", ge=0)


class ReportResponse(BaseModel):
    """Aggregated learning report used by the profile report endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "overall_mastery": 0.72,
                "weak_points_top5": [
                    {
                        "knowledge_point": "贝叶斯公式",
                        "mastery": 0.4,
                        "attempts": 5,
                        "correct": 2,
                    }
                ],
                "suggestions": ["优先复习贝叶斯公式的应用题。"],
            }
        }
    )

    overall_mastery: float | None = Field(
        default=None,
        description="总体掌握度估计值，按已有做题记录加权计算。",
        ge=0,
        le=1,
    )
    weak_points_top5: list[ProfileItem] = Field(description="掌握度最低的前 5 个知识点。")
    suggestions: list[str] = Field(description="结合画像生成的复习建议列表。")


class MistakeItem(BaseModel):
    """Single mistake-book item composed from exam and grading records."""

    id: int = Field(description="错题记录 ID。")
    question_stem: str = Field(description="题干内容。")
    question_type: QuestionTypeValue = Field(description="题目类型。")
    user_answer: str = Field(description="用户答案。")
    correct_answer: str = Field(description="参考答案。")
    analysis: str = Field(description="AI 生成的错因分析。")
    knowledge_point: str = Field(description="关联知识点。")
    created_at: datetime = Field(description="错题记录创建时间（UTC）。")


class MistakeListResponse(BaseModel):
    """Paginated response for the subject mistake book."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 3,
                        "question_stem": "贝叶斯公式的表达式是什么？",
                        "question_type": "short_answer",
                        "user_answer": "忘记了",
                        "correct_answer": "P(A|B)=P(B|A)P(A)/P(B)",
                        "analysis": "对公式中的条件与先验关系混淆。",
                        "knowledge_point": "贝叶斯公式",
                        "created_at": "2026-03-15T08:00:00Z",
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[MistakeItem] = Field(description="当前分页内的错题列表。")
    total: int = Field(description="错题总数。", ge=0)
