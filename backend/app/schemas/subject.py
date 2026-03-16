"""学科接口 schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams


class SubjectCreateRequest(BaseModel):
    """创建学科请求。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "subject": "math",
                "name": "高等数学",
                "description": "用于手动联调的学科空间",
            }
        }
    )

    subject: str = Field(description="学科标识。")
    name: str = Field(description="展示名称。")
    description: str = Field(default="", description="学科描述。")


class SubjectDetailRequest(BaseModel):
    """学科详情请求。"""

    subject: str = Field(description="学科标识。")


class SubjectUpdateRequest(SubjectCreateRequest):
    """更新学科请求。"""


class SubjectDeleteRequest(SubjectDetailRequest):
    """删除学科请求。"""


class SubjectListRequest(PageParams):
    """学科分页列表请求。"""


class SubjectItem(BaseModel):
    """学科数据项。"""

    id: int = Field(description="学科 ID。")
    subject: str = Field(description="学科标识。")
    name: str = Field(description="展示名称。")
    description: str = Field(description="学科描述。")
    created_at: datetime = Field(description="创建时间。")
    updated_at: datetime = Field(description="更新时间。")


class SubjectDeleteData(BaseModel):
    """学科删除结果。"""

    deleted: bool = Field(description="是否删除成功。")
    subject: str = Field(description="学科标识。")
