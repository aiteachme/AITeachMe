"""Shared API schemas used across multiple endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ErrorResponse(BaseModel):
    """Standardized error payload returned by global exception handlers."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "detail": "Authentication is disabled in local mode.",
                "error_code": "AUTH_DISABLED",
            }
        }
    )

    detail: str = Field(description="Human-readable error detail.")
    error_code: str = Field(description="Stable machine-readable error code.", examples=["INVALID_SUBJECT"])


class HealthResponse(BaseModel):
    """Health-check response returned by the `/api/health` endpoint."""

    model_config = ConfigDict(json_schema_extra={"example": {"status": "ok"}})

    status: str = Field(default="ok", description="Service health status.")


class PaginationParams(BaseModel):
    """Shared pagination request body used by list-style POST endpoints."""

    model_config = ConfigDict(json_schema_extra={"example": {"limit": 20, "offset": 0}})

    limit: int = Field(default=100, ge=1, le=1000, description="Maximum number of records to return.")
    offset: int = Field(default=0, ge=0, description="Zero-based pagination offset.")
