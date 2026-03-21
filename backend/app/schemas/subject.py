from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams


class SubjectCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "高等数学",
                "description": "用于手动联调的学科空间",
            }
        }
    )

    name: str = Field(min_length=1, description="展示名称。")
    description: str = Field(default="", description="学科描述。")


class SubjectDetailRequest(BaseModel):
    subject_id: str = Field(description="学科外部标识。")


class SubjectUpdateRequest(BaseModel):
    subject_id: str = Field(description="学科外部标识。")
    name: str = Field(min_length=1, description="展示名称。")
    description: str = Field(default="", description="学科描述。")


class SubjectDeleteRequest(SubjectDetailRequest):
    pass


class SubjectListRequest(PageParams):
    pass


class SubjectItem(BaseModel):
    id: int = Field(description="学科 ID。")
    subject_id: str = Field(description="学科外部标识。")
    name: str = Field(description="展示名称。")
    description: str = Field(description="学科描述。")
    created_at: datetime = Field(description="创建时间。")
    updated_at: datetime = Field(description="更新时间。")


class SubjectDeleteData(BaseModel):
    deleted: bool = Field(description="是否删除成功。")
    subject_id: str = Field(description="学科外部标识。")
