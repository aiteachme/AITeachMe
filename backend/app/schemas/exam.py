"""Schemas for exam generation, submission, and history APIs."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import DifficultyValue, QuestionTypeValue


class ExamGenerateRequest(BaseModel):
    """Request body for generating a new exam."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "num_questions": 10,
                "difficulty_distribution": {"easy": 0.3, "medium": 0.5, "hard": 0.2},
                "knowledge_points": ["条件概率", "贝叶斯公式"],
            }
        }
    )

    num_questions: int = Field(default=10, ge=1, le=50, description="期望生成的题目数量。")
    difficulty_distribution: dict[str, float] | None = Field(
        default=None,
        description="可选的难度分布，键为 easy/medium/hard，值为比例。",
    )
    knowledge_points: list[str] | None = Field(
        default=None,
        description="可选的指定知识点范围；为空时由系统自动选取。",
    )


class QuestionItem(BaseModel):
    """Public exam question DTO that intentionally hides the correct answer."""

    question_key: str = Field(description="题目稳定键，如 q1、q2。", examples=["q1"])
    type: QuestionTypeValue = Field(description="题目类型。")
    stem: str = Field(description="题干内容。")
    options: list[str] | None = Field(
        default=None,
        description="单选题候选项；非单选题通常为空。",
    )
    knowledge_point: str = Field(description="题目对应的知识点。")
    difficulty: DifficultyValue = Field(description="题目难度。")


class ExamResponse(BaseModel):
    """Response returned after a new exam has been generated."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "exam_id": 5,
                "questions": [
                    {
                        "question_key": "q1",
                        "type": "single_choice",
                        "stem": "下列哪个公式表示条件概率？",
                        "options": ["P(A|B)=P(AB)/P(B)", "P(A)+P(B)"],
                        "knowledge_point": "条件概率",
                        "difficulty": "easy",
                    }
                ],
            }
        }
    )

    exam_id: int = Field(description="新生成考卷的 ID。", examples=[5])
    questions: list[QuestionItem] = Field(description="考卷题目列表。")


class AnswerItem(BaseModel):
    """Single submitted answer item."""

    question_key: str = Field(description="对应题目的 question_key。", examples=["q1"])
    answer: str = Field(description="用户作答内容。", examples=["P(A|B)=P(AB)/P(B)"])


class SubmitRequest(BaseModel):
    """Request body for submitting answers to an existing exam."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "answers": [
                    {"question_key": "q1", "answer": "P(A|B)=P(AB)/P(B)"}
                ]
            }
        }
    )

    answers: list[AnswerItem] = Field(description="按题目键提交的答案列表。")


class AnswerResultItem(BaseModel):
    """Per-question grading result returned after submission."""

    question_key: str = Field(description="题目键。")
    is_correct: bool = Field(description="该题是否判定为正确。")
    user_answer: str = Field(description="用户提交的答案。")
    correct_answer: str = Field(description="系统参考答案。")
    explanation: str = Field(description="标准解析或评分说明。")
    analysis: str | None = Field(default=None, description="错题分析；答对时通常为空。")


class SubmitResponse(BaseModel):
    """Exam grading summary returned after a submission is processed."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "submission_id": 9,
                "score": 80.0,
                "results": [
                    {
                        "question_key": "q1",
                        "is_correct": True,
                        "user_answer": "P(A|B)=P(AB)/P(B)",
                        "correct_answer": "P(A|B)=P(AB)/P(B)",
                        "explanation": "由条件概率定义可得。",
                        "analysis": None,
                    }
                ],
            }
        }
    )

    submission_id: int = Field(description="答卷提交记录 ID。", examples=[9])
    score: float = Field(description="百分制得分。", ge=0, le=100, examples=[80.0])
    results: list[AnswerResultItem] = Field(description="逐题判分结果。")


class ExamHistoryItem(BaseModel):
    """Single exam history item."""

    exam_id: int = Field(description="考卷 ID。")
    submission_id: int | None = Field(default=None, description="最近一次提交记录 ID。")
    score: float | None = Field(default=None, description="最近一次提交得分。")
    created_at: datetime = Field(description="考卷创建时间（UTC）。")


class ExamHistoryResponse(BaseModel):
    """Paginated response for exam history entries."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "exam_id": 5,
                        "submission_id": 9,
                        "score": 80.0,
                        "created_at": "2026-03-15T08:00:00Z",
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[ExamHistoryItem] = Field(description="当前分页内的考试记录列表。")
    total: int = Field(description="历史考试记录总数。", ge=0)
