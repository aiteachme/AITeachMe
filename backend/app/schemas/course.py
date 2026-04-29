from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams


class CourseCreateRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "",
                "description": "",
                "user_intent": "",
            }
        }
    )

    name: str = Field(default="", description="Display name. Planner may fill it after the first conversation.")
    description: str = Field(default="", description="Short course description.")
    user_intent: str = Field(default="", description="User learning goal or intent.")


class CourseDetailRequest(BaseModel):
    course_id: str = Field(description="Course id.")


class CourseUpdateRequest(BaseModel):
    course_id: str = Field(description="Course id.")
    name: str | None = Field(default=None, min_length=1, description="Display name.")
    description: str | None = Field(default=None, description="Short course description.")
    user_intent: str | None = Field(default=None, description="User learning goal or intent.")


class CourseDeleteRequest(CourseDetailRequest):
    force: bool = Field(default=False, description="Whether to confirm cascading deletion of course content.")


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
    prompt: str | None = Field(default=None, description="User input learning goal.")
    filenames: list[str] | None = Field(default=None, description="Uploaded filenames.")


class CourseNameSuggestionResponse(BaseModel):
    name: str = Field(description="AI-generated course name.")
