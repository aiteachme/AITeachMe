from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from app.schemas.common import PageParams


CourseNameSuggestionFilename = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class CourseDetailRequest(BaseModel):
    course_id: str = Field(description="Course id.")


class CourseUpdateRequest(BaseModel):
    course_id: str = Field(description="Course id.")
    name: str | None = Field(default=None, min_length=1, description="Display name.")
    description: str | None = Field(default=None, description="Short course description.")
    user_intent: str | None = Field(default=None, description="User learning goal or intent.")


class CourseDeleteRequest(CourseDetailRequest):
    force: bool = Field(default=False, description="Whether to confirm cascading deletion of course content.")
    known_detail_counts: dict[str, int] | None = Field(
        default=None,
        description="Optional delete-preview counts already shown to the user; used only for response metadata.",
    )


class CourseDeletePreviewRequest(CourseDetailRequest):
    pass


class CourseListRequest(PageParams):
    pass


class CourseItem(BaseModel):
    course_id: str = Field(description="Course id.")
    name: str = Field(description="Display name.")
    description: str = Field(description="Short course description.")
    user_intent: str = Field(description="User learning goal or intent.")
    icon_key: str | None = Field(default=None, description="Course icon key.")
    created_at: datetime = Field(description="Created time.")
    updated_at: datetime = Field(description="Updated time.")


class CourseDeleteData(BaseModel):
    deleted: bool = Field(description="Whether deletion succeeded.")
    course_id: str = Field(description="Course id.")
    deleted_counts: dict[str, int] = Field(default_factory=dict, description="Deleted record counts.")


class CourseDeleteImpactItem(BaseModel):
    key: str = Field(description="Impact item key.")
    label: str = Field(description="Impact item label.")
    count: int = Field(description="Impact count.", ge=0)
    description: str = Field(description="Impact description.")


class CourseDeletePreviewData(BaseModel):
    course_id: str = Field(description="Course id.")
    course_name: str = Field(description="Course name.")
    has_content: bool = Field(description="Whether the course has related content.")
    total_related_records: int = Field(description="Total related record count.", ge=0)
    impact_items: list[CourseDeleteImpactItem] = Field(
        default_factory=list,
        description="Human-readable deletion impact items.",
    )
    detail_counts: dict[str, int] = Field(default_factory=dict, description="Internal detail counts.")


class CourseNameSuggestionRequest(BaseModel):
    prompt: str | None = Field(default=None, max_length=2000, description="User input learning goal.")
    filenames: list[CourseNameSuggestionFilename] | None = Field(
        default=None,
        max_length=5,
        description="Uploaded filenames.",
    )


class CourseNameSuggestionResponse(BaseModel):
    name: str = Field(description="AI-generated course name.")
