"""Import/export request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ExportOptions(BaseModel):
    """Export options payload."""

    include_raw_files: bool = Field(default=True, description="Include original uploaded files such as PDF/DOCX.")
    include_raw_markdowns: bool = Field(default=True, description="Include parsed raw markdown files.")
    include_knowledge_docs: bool = Field(default=True, description="Include generated knowledge docs.")
    include_chat_history: bool = Field(default=True, description="Include chat history.")
    include_exam_history: bool = Field(default=True, description="Include question templates and exam history.")
    include_profile: bool = Field(default=True, description="Include user knowledge profile states.")


class ExportPreviewStats(BaseModel):
    """Export preview counters."""

    raw_file_count: int = 0
    total_raw_file_size_bytes: int = 0
    knowledge_document_count: int = 0
    knowledge_unit_count: int = 0
    knowledge_edge_count: int = 0
    confirmed_build_plan_count: int = 0
    question_type_registry_count: int = 0
    question_template_count: int = 0
    exam_paper_count: int = 0
    chat_session_count: int = 0
    user_knowledge_state_count: int = 0


class ExportPreviewData(BaseModel):
    """Export preview payload."""

    subject_id: str
    subject_name: str
    stats: ExportPreviewStats
    estimated_size_bytes: int = 0


class ImportOptions(BaseModel):
    """Import options payload."""

    new_subject_name: str | None = Field(default=None, description="Optional custom subject name after import.")


class ImportResultData(BaseModel):
    """Import result payload."""

    subject_id: str = Field(description="Imported subject external id.")
    subject_name: str = Field(description="Imported subject name.")
    imported_counts: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class CoursePackageItem(BaseModel):
    """One remote demo-course package listed from the configured catalog."""

    filename: str = Field(description="Stable course identifier used for remote import.")
    subject_name: str = Field(description="Subject name from manifest.")
    file_size_bytes: int = Field(default=0)
    exported_at: datetime | None = Field(default=None)
    stats: dict[str, int] = Field(default_factory=dict)
