"""API contracts for course question-type package import and catalog management."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class QuestionTypePackageIssueResponse(BaseModel):
    code: str
    path: str
    message: str


class QuestionTypeAnswerFieldResponse(BaseModel):
    key: str
    label: str
    control: str
    required: bool
    min_length: int = 0
    max_length: int = 1
    placeholder: str = ""


class QuestionTypeRubricItemResponse(BaseModel):
    key: str
    label: str
    weight: float
    description: str


class QuestionTypePackagePreviewData(BaseModel):
    import_id: str | None = None
    valid: bool
    status: Literal["valid", "invalid"]
    expires_at: datetime | None = None
    package_hash: str = ""
    package_key: str = ""
    type_key: str = ""
    version: str = ""
    name: str = ""
    description: str = ""
    template_key: str = ""
    runtime_key: str = ""
    renderer_key: str = ""
    grader_key: str = ""
    modes: list[str] = Field(default_factory=list)
    answer_fields: list[QuestionTypeAnswerFieldResponse] = Field(default_factory=list)
    rubric: list[QuestionTypeRubricItemResponse] = Field(default_factory=list)
    tool_ids: list[str] = Field(default_factory=list)
    asset_count: int = 0
    conflict: Literal["none", "already_installed", "version_conflict", "new_version"] = "none"
    existing_version_id: int | None = None
    runtime_ready: bool = False
    runtime_message: str = ""
    errors: list[QuestionTypePackageIssueResponse] = Field(default_factory=list)
    warnings: list[QuestionTypePackageIssueResponse] = Field(default_factory=list)


class QuestionTypePackageInstallRequest(BaseModel):
    set_current: bool = True


class QuestionTypePackageInstallData(BaseModel):
    registry_id: int
    version_id: int
    type_key: str
    version: str
    status: str
    runtime_ready: bool
    already_installed: bool = False


class QuestionTypePackageVersionResponse(BaseModel):
    id: int
    version: str
    package_hash: str
    source_filename: str
    is_current: bool
    profile_eligible: bool
    created_at: datetime


class QuestionTypeCatalogItemResponse(BaseModel):
    id: int
    type_key: str
    display_name: str
    scope: str
    course_id: str
    description: str
    answer_format: str
    grading_method: str
    option_schema: dict[str, Any] = Field(default_factory=dict)
    rubric: dict[str, Any] | list[Any] = Field(default_factory=dict)
    source: str
    confidence: float
    is_system: bool
    is_active: bool
    status: str
    package_key: str | None = None
    current_version_id: int | None = None
    current_version: str | None = None
    template_key: str | None = None
    runtime_key: str | None = None
    renderer_key: str | None = None
    grader_key: str | None = None
    modes: list[str] = Field(default_factory=list)
    runtime_ready: bool = True
    runtime_message: str = ""
    answer_fields: list[QuestionTypeAnswerFieldResponse] = Field(default_factory=list)
    versions: list[QuestionTypePackageVersionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class QuestionTypeCatalogPatchRequest(BaseModel):
    status: Literal["active", "inactive", "archived"] | None = None
    current_version_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_change(self) -> "QuestionTypeCatalogPatchRequest":
        if self.status is None and self.current_version_id is None:
            raise ValueError("至少需要提供一项题型变更。")
        return self


class QuestionTypeExampleResponse(BaseModel):
    example_id: str
    template_key: str = Field(
        deprecated=True,
        description="兼容旧客户端的示例下载标识；使用 example_id。此字段不是包内的运行模板。",
    )
    name: str
    filename: str


__all__ = [
    "QuestionTypeCatalogItemResponse",
    "QuestionTypeCatalogPatchRequest",
    "QuestionTypeExampleResponse",
    "QuestionTypePackageInstallData",
    "QuestionTypePackageInstallRequest",
    "QuestionTypePackageIssueResponse",
    "QuestionTypePackagePreviewData",
]
