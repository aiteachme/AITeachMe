from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams


class SubjectCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "高等数学",
            }
        }
    )

    name: str = Field(min_length=1, description="展示名称。")


class SubjectDetailRequest(BaseModel):
    subject_id: str = Field(description="学科外部标识。")


class SubjectUpdateRequest(BaseModel):
    subject_id: str = Field(description="学科外部标识。")
    name: str = Field(min_length=1, description="展示名称。")


class SubjectDeleteRequest(SubjectDetailRequest):
    force: bool = Field(default=False, description="是否确认级联删除学科下的全部内容。")


class SubjectDeletePreviewRequest(SubjectDetailRequest):
    pass


class SubjectListRequest(PageParams):
    pass


class SubjectItem(BaseModel):
    id: int = Field(description="学科 ID。")
    subject_id: str = Field(description="学科外部标识。")
    name: str = Field(description="展示名称。")
    created_at: datetime = Field(description="创建时间。")
    updated_at: datetime = Field(description="更新时间。")


class SubjectDeleteData(BaseModel):
    deleted: bool = Field(description="是否删除成功。")
    subject_id: str = Field(description="学科外部标识。")
    deleted_counts: dict[str, int] = Field(default_factory=dict, description="本次删除涉及的记录统计。")


class SubjectDeleteImpactItem(BaseModel):
    key: str = Field(description="影响项唯一标识。")
    label: str = Field(description="影响项展示名称。")
    count: int = Field(description="影响数量。", ge=0)
    description: str = Field(description="影响项说明。")


class SubjectDeletePreviewData(BaseModel):
    subject_id: str = Field(description="学科外部标识。")
    subject_name: str = Field(description="学科名称。")
    has_content: bool = Field(description="学科下是否仍有关联内容。")
    total_related_records: int = Field(description="关联记录总数。", ge=0)
    impact_items: list[SubjectDeleteImpactItem] = Field(
        default_factory=list,
        description="用户可读的删除影响列表。",
    )
    detail_counts: dict[str, int] = Field(default_factory=dict, description="内部明细统计。")


class SubjectNameSuggestionRequest(BaseModel):
    prompt: str | None = Field(default=None, description="用户输入的学习目标。")
    filenames: list[str] | None = Field(default=None, description="上传的文件名列表。")


class SubjectNameSuggestionResponse(BaseModel):
    name: str = Field(description="AI 生成的学科名称。")
