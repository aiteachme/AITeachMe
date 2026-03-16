"""学习画像接口 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams
from app.schemas.enums import QuestionTypeValue


class ProfileListRequest(PageParams):
    """画像列表分页请求。"""


class ProfileReportRequest(BaseModel):
    """画像报告请求。"""

    model_config = ConfigDict(json_schema_extra={"example": {}})


class ProfileMistakesRequest(PageParams):
    """错题本分页请求。"""


class ProfileItem(BaseModel):
    """单个知识点画像。"""

    knowledge_point: str = Field(description="知识点。")
    mastery: float | None = Field(default=None, description="掌握度。", ge=0, le=1)
    attempts: int = Field(description="作答次数。", ge=0)
    correct: int = Field(description="答对次数。", ge=0)


class ReportData(BaseModel):
    """学习报告。"""

    overall_mastery: float | None = Field(default=None, description="整体掌握度。", ge=0, le=1)
    weak_points_top5: list[ProfileItem] = Field(default_factory=list, description="最薄弱的五个知识点。")
    suggestions: list[str] = Field(default_factory=list, description="学习建议。")


class MistakeItem(BaseModel):
    """错题项。"""

    id: int = Field(description="错题 ID。")
    question_stem: str = Field(description="题干。")
    question_type: QuestionTypeValue = Field(description="题目类型。")
    user_answer: str = Field(description="用户答案。")
    correct_answer: str = Field(description="正确答案。")
    analysis: str = Field(description="错因分析。")
    knowledge_point: str = Field(description="知识点。")
    created_at: datetime = Field(description="创建时间。")
