"""通用响应与分页结构。"""

from __future__ import annotations

from math import ceil
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一接口响应结构。"""

    model_config = ConfigDict(
        json_schema_extra={"example": {"code": 0, "message": "ok", "data": {}}}
    )

    code: int = Field(default=0, description="业务码，0 表示成功。")
    message: str = Field(default="ok", description="响应消息。")
    data: T | None = Field(default=None, description="业务数据。")


class ErrorResponse(ApiResponse[None]):
    """统一错误响应结构。"""

    model_config = ConfigDict(
        json_schema_extra={"example": {"code": 404, "message": "资源不存在", "data": None}}
    )


class HealthData(BaseModel):
    """健康检查数据。"""

    status: str = Field(default="ok", description="服务状态。")


class PageParams(BaseModel):
    """通用分页请求参数。"""

    model_config = ConfigDict(json_schema_extra={"example": {"page": 1, "size": 20}})

    page: int = Field(default=1, ge=1, description="页码，从 1 开始。")
    size: int = Field(default=20, ge=1, le=100, description="每页数量。")

    @property
    def offset(self) -> int:
        """将页码转换为偏移量。"""

        return (self.page - 1) * self.size


class PaginatedData(BaseModel, Generic[T]):
    """通用分页响应数据。"""

    items: list[T] = Field(default_factory=list, description="当前页数据。")
    page: int = Field(description="当前页码。", ge=1)
    size: int = Field(description="每页数量。", ge=1)
    total: int = Field(description="总条数。", ge=0)
    pages: int = Field(description="总页数。", ge=0)


def build_paginated_data(
    *,
    items: list[T],
    page: int,
    size: int,
    total: int,
) -> PaginatedData[T]:
    """构造统一分页数据。"""

    pages = ceil(total / size) if size > 0 else 0
    return PaginatedData(items=items, page=page, size=size, total=total, pages=pages)


def ok_response(data: T | None = None, message: str = "ok") -> ApiResponse[T]:
    """构造成功响应。"""

    return ApiResponse(code=0, message=message, data=data)
