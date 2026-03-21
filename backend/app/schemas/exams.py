"""测验接口 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams
from app.schemas.enums import DifficultyValue, QuestionTypeValue


class ExamMakeRequest(BaseModel):
    """出题请求。"""

    model_config = ConfigDict(
        json_schema_extra={"example": {"num": 10, "points": ["条件概率", "贝叶斯定理"]}}
    )

    num: int = Field(default=10, ge=1, le=50, description="题目数量。")
    points: list[str] | None = Field(default=None, description="可选知识点范围。")


class QuestionItem(BaseModel):
    """题目数据。"""

    question_key: str = Field(description="题目标识。")
    type: QuestionTypeValue = Field(description="题目类型。")
    stem: str = Field(description="题干。")
    options: list[str] | None = Field(default=None, description="选项。")
    knowledge_point: str = Field(description="知识点。")
    difficulty: DifficultyValue = Field(description="难度。")


class ExamData(BaseModel):
    """试卷数据。"""

    exam_id: int = Field(description="试卷 ID。")
    questions: list[QuestionItem] = Field(default_factory=list, description="题目列表。")


class AnswerItem(BaseModel):
    """答题项。"""

    question_key: str = Field(description="题目标识。")
    answer: str = Field(description="用户答案。")


class ExamSubmitRequest(BaseModel):
    """交卷请求。"""

    exam_id: int = Field(description="试卷 ID。")
    answers: list[AnswerItem] = Field(default_factory=list, description="答案列表。")


class AnswerResultItem(BaseModel):
    """判题结果项。"""

    question_key: str = Field(description="题目标识。")
    is_correct: bool = Field(description="是否正确。")
    user_answer: str = Field(description="用户答案。")
    correct_answer: str = Field(description="正确答案。")
    explanation: str = Field(description="题目解析。")
    analysis: str | None = Field(default=None, description="错因分析。")


class SubmitData(BaseModel):
    """交卷结果。"""

    submission_id: int = Field(description="提交记录 ID。")
    score: float = Field(description="得分。", ge=0, le=100)
    results: list[AnswerResultItem] = Field(default_factory=list, description="逐题判分结果。")


class ExamListRequest(PageParams):
    """历史试卷分页请求。"""


class ExamDeleteRequest(BaseModel):
    """删除试卷请求。"""

    exam_id: int = Field(description="试卷 ID。")


class ExamDeleteData(BaseModel):
    """删除试卷结果。"""

    deleted: bool = Field(description="是否删除成功。")
    exam_id: int = Field(description="试卷 ID。")


class ExamHistoryItem(BaseModel):
    """试卷历史项。"""

    exam_id: int = Field(description="试卷 ID。")
    submission_id: int | None = Field(default=None, description="最近一次提交 ID。")
    score: float | None = Field(default=None, description="最近一次得分。")
    created_at: datetime = Field(description="创建时间。")
