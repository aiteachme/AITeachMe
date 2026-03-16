"""Schemas for top-level subject management APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginationParams


class SubjectCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "subject": "math",
                "name": "High School Math",
                "description": "Manual test subject for ingest and chat flows.",
            }
        }
    )

    subject: str = Field(description="Top-level subject slug.")
    name: str = Field(description="Display name for the subject.")
    description: str = Field(default="", description="Optional subject description.")


class SubjectDetailRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"subject": "math"}})

    subject: str = Field(description="Top-level subject slug.")


class SubjectUpdateRequest(SubjectCreateRequest):
    pass


class SubjectDeleteRequest(SubjectDetailRequest):
    pass


class SubjectListRequest(PaginationParams):
    pass


class SubjectItem(BaseModel):
    id: int
    subject: str = Field(description="Top-level subject slug.")
    name: str
    description: str
    created_at: datetime
    updated_at: datetime


class SubjectDetailResponse(SubjectItem):
    pass


class SubjectListResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 1,
                        "subject": "math",
                        "name": "High School Math",
                        "description": "Manual test subject for ingest and chat flows.",
                        "created_at": "2026-03-15T08:00:00Z",
                        "updated_at": "2026-03-15T08:00:00Z",
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[SubjectItem]
    total: int


class SubjectDeleteResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"deleted": True, "subject": "math"}})

    deleted: bool
    subject: str
