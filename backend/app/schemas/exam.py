"""考试相关 Schema — ExamGenerateRequest、ExamResponse、SubmitRequest、SubmitResponse、ExamHistoryResponse"""

from datetime import datetime
from pydantic import BaseModel


class ExamGenerateRequest(BaseModel):
    num_questions: int = 10
    difficulty_distribution: dict[str, float] | None = None
    knowledge_points: list[str] | None = None


class QuestionItem(BaseModel):
    """对外 DTO，不暴露 answer 字段"""
    question_key: str
    type: str
    stem: str
    options: list[str] | None = None
    knowledge_point: str
    difficulty: str


class ExamResponse(BaseModel):
    exam_id: int
    questions: list[QuestionItem]


class AnswerItem(BaseModel):
    question_key: str
    answer: str


class SubmitRequest(BaseModel):
    answers: list[AnswerItem]


class AnswerResultItem(BaseModel):
    question_key: str
    is_correct: bool
    user_answer: str
    correct_answer: str
    explanation: str
    analysis: str | None = None


class SubmitResponse(BaseModel):
    submission_id: int
    score: float
    results: list[AnswerResultItem]


class ExamHistoryItem(BaseModel):
    exam_id: int
    submission_id: int | None = None
    score: float | None = None
    created_at: datetime


class ExamHistoryResponse(BaseModel):
    items: list[ExamHistoryItem]
    total: int
