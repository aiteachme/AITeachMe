"""Shared API schemas used across multiple endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """Standardized error payload returned by global exception handlers."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "未配置 LLM_API_KEY，当前功能需要先配置该密钥后才能使用",
                "error_code": "LLM_API_KEY_MISSING",
            }
        }
    )

    detail: str = Field(description="面向调用方的错误说明。")
    error_code: str = Field(description="稳定的机器可读错误码。", examples=["INVALID_SUBJECT"])


class HealthResponse(BaseModel):
    """Health-check response returned by the `/api/health` endpoint."""

    model_config = ConfigDict(json_schema_extra={"example": {"status": "ok"}})

    status: str = Field(default="ok", description="服务健康状态。")


class PaginationParams(BaseModel):
    """Shared pagination request body used by list-style POST endpoints."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"limit": 20, "offset": 0}}
    )

    limit: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="单次返回的最大记录数。",
        examples=[20],
    )
    offset: int = Field(
        default=0,
        ge=0,
        description="基于 0 的分页偏移量。",
        examples=[0],
    )
