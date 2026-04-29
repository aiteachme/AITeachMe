from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams


class SubjectCreateRequest(BaseModel):
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
    description: str = Field(default="", description="Short subject description.")
    user_intent: str = Field(default="", description="User learning goal or intent.")


class SubjectDetailRequest(BaseModel):
    subject_id: str = Field(description="Subject id.")


class SubjectUpdateRequest(BaseModel):
    subject_id: str = Field(description="Subject id.")
    name: str | None = Field(default=None, min_length=1, description="Display name.")
    description: str | None = Field(default=None, description="Short subject description.")
    user_intent: str | None = Field(default=None, description="User learning goal or intent.")


class SubjectDeleteRequest(SubjectDetailRequest):
    force: bool = Field(default=False, description="Whether to confirm cascading deletion of subject content.")
    known_detail_counts: dict[str, int] | None = Field(
        default=None,
        description="Optional delete-preview counts already shown to the user; used only for response metadata.",
    )


class SubjectDeletePreviewRequest(SubjectDetailRequest):
    pass


class SubjectListRequest(PageParams):
    pass


class SubjectItem(BaseModel):
    subject_id: str = Field(description="Subject id.")
    name: str = Field(description="Display name.")
    description: str = Field(description="Short subject description.")
    user_intent: str = Field(description="User learning goal or intent.")
    icon_key: str | None = Field(default=None, description="Subject icon key.")
    created_at: datetime = Field(description="Created time.")
    updated_at: datetime = Field(description="Updated time.")


class SubjectDeleteData(BaseModel):
    deleted: bool = Field(description="Whether deletion succeeded.")
    subject_id: str = Field(description="Subject id.")
    deleted_counts: dict[str, int] = Field(default_factory=dict, description="Deleted record counts.")


class SubjectDeleteImpactItem(BaseModel):
    key: str = Field(description="Impact item key.")
    label: str = Field(description="Impact item label.")
    count: int = Field(description="Impact count.", ge=0)
    description: str = Field(description="Impact description.")


class SubjectDeletePreviewData(BaseModel):
    subject_id: str = Field(description="Subject id.")
    subject_name: str = Field(description="Subject name.")
    has_content: bool = Field(description="Whether the subject has related content.")
    total_related_records: int = Field(description="Total related record count.", ge=0)
    impact_items: list[SubjectDeleteImpactItem] = Field(
        default_factory=list,
        description="Human-readable deletion impact items.",
    )
    detail_counts: dict[str, int] = Field(default_factory=dict, description="Internal detail counts.")


class SubjectNameSuggestionRequest(BaseModel):
    prompt: str | None = Field(default=None, description="User input learning goal.")
    filenames: list[str] | None = Field(default=None, description="Uploaded filenames.")


class SubjectNameSuggestionResponse(BaseModel):
    name: str = Field(description="AI-generated subject name.")
