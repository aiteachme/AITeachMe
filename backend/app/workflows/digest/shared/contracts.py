"""Shared build-contract helpers for digest planner and docgen lanes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


DEFAULT_COURSE_TYPE = "systematic"
SPRINT_COURSE_TYPE = "sprint"
PLANNER_RETRIEVAL_PROFILE = "planner_grounding"


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _clean_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned


def _clean_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    cleaned: list[int] = []
    seen: set[int] = set()
    for item in items:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed <= 0 or parsed in seen:
            continue
        seen.add(parsed)
        cleaned.append(parsed)
    return cleaned


class DigestChapterMediaHints(BaseModel):
    """Normalized media hints attached to a single chapter contract."""

    model_config = ConfigDict(extra="allow")

    images: list[str] = Field(default_factory=list)
    mermaid: list[str] = Field(default_factory=list)
    interactive: list[str] = Field(default_factory=list)

    @field_validator("images", "mermaid", "interactive", mode="before")
    @classmethod
    def _normalize_items(cls, value: Any) -> list[str]:
        return _clean_string_list(value)


class DigestChapterContract(BaseModel):
    """A normalized, execution-ready chapter contract."""

    model_config = ConfigDict(extra="allow")

    chapter_index: int = Field(default=1, ge=1)
    title: str = ""
    resolved_title: str = ""
    objective: str = ""
    required_elements: list[str] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    writing_instructions: str = ""
    media_hints: DigestChapterMediaHints = Field(default_factory=DigestChapterMediaHints)
    source_file_ids: list[int] = Field(default_factory=list)

    @field_validator("title", "resolved_title", "objective", "writing_instructions", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("required_elements", "search_queries", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: Any) -> list[str]:
        return _clean_string_list(value)

    @field_validator("source_file_ids", mode="before")
    @classmethod
    def _normalize_source_file_ids(cls, value: Any) -> list[int]:
        return _clean_int_list(value)

    def to_assignment(self, *, default_source_file_ids: list[int]) -> dict[str, Any]:
        chapter_index = max(1, int(self.chapter_index or 1))
        title = self.title or f"第 {chapter_index} 章"
        return {
            "chapter_index": chapter_index,
            "title": title,
            "resolved_title": self.resolved_title,
            "objective": self.objective,
            "required_elements": list(self.required_elements),
            "search_queries": list(self.search_queries),
            "writing_instructions": self.writing_instructions,
            "media_hints": self.media_hints.model_dump(mode="json"),
            "source_file_ids": list(self.source_file_ids or default_source_file_ids),
        }


class DigestBuildConstraints(BaseModel):
    """Normalized document build controls stored on a confirmed plan."""

    model_config = ConfigDict(extra="allow")

    include_exercises: bool = True
    include_sources: bool = True
    math_mode: bool = False
    min_chapters: int | None = None
    max_chapters: int | None = None
    target_chapter_count: int | None = None
    target_length: str = ""

    @field_validator("target_length", mode="before")
    @classmethod
    def _normalize_target_length(cls, value: Any) -> str:
        return _clean_text(value)


class DigestConfirmedPlanContract(BaseModel):
    """Typed confirmed-plan contract shared by planner and docgen lanes."""

    model_config = ConfigDict(extra="allow")

    subject: str = ""
    user_goal: str = ""
    digest_mode: str = DEFAULT_COURSE_TYPE
    tone: str = "encouraging"
    selected_skillpacks: list[str] = Field(default_factory=list)
    chapter_plan: list[DigestChapterContract] = Field(default_factory=list)
    research_queries: list[str] = Field(default_factory=list)
    media_plan: dict[str, Any] = Field(default_factory=dict)
    build_constraints: DigestBuildConstraints = Field(default_factory=DigestBuildConstraints)
    plan_summary: str = ""
    selected_file_ids: list[int] = Field(default_factory=list)
    planner_session_id: str = ""
    confirmed_plan_id: str = ""
    mode_reason: str = ""

    @field_validator(
        "subject",
        "user_goal",
        "digest_mode",
        "tone",
        "plan_summary",
        "planner_session_id",
        "confirmed_plan_id",
        "mode_reason",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("research_queries", mode="before")
    @classmethod
    def _normalize_research_queries(cls, value: Any) -> list[str]:
        return _clean_string_list(value)

    @field_validator("selected_skillpacks", mode="before")
    @classmethod
    def _normalize_selected_skillpacks(cls, value: Any) -> list[str]:
        return _clean_string_list(value)

    @field_validator("selected_file_ids", mode="before")
    @classmethod
    def _normalize_selected_file_ids(cls, value: Any) -> list[int]:
        return _clean_int_list(value)

    def resolve_course_type(self) -> str:
        return resolve_digest_course_type(self.digest_mode)

    def resolve_retrieval_profile(self) -> str:
        return resolve_digest_retrieval_profile(self.digest_mode)

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_chapter_assignments(self, *, default_source_file_ids: list[int]) -> list[dict[str, Any]]:
        return [
            chapter.to_assignment(default_source_file_ids=default_source_file_ids)
            for chapter in self.chapter_plan
        ]


def parse_digest_confirmed_plan_contract(
    payload: Mapping[str, Any] | BaseModel | None,
) -> DigestConfirmedPlanContract:
    """Validate and normalize a persisted confirmed-plan payload."""

    raw_payload: Any = payload
    if isinstance(payload, BaseModel):
        raw_payload = payload.model_dump(mode="json")
    elif payload is None:
        raw_payload = {}
    return DigestConfirmedPlanContract.model_validate(raw_payload)


def normalize_digest_confirmed_plan_payload(
    payload: Mapping[str, Any] | BaseModel | None,
) -> dict[str, Any]:
    """Return a JSON-friendly normalized confirmed-plan payload."""

    return parse_digest_confirmed_plan_contract(payload).to_payload()


def resolve_digest_course_type(digest_mode: str | None) -> str:
    """Resolve the normalized course type from the requested digest mode."""

    normalized = str(digest_mode or "").strip().lower()
    if normalized == SPRINT_COURSE_TYPE:
        return SPRINT_COURSE_TYPE
    return DEFAULT_COURSE_TYPE


def resolve_digest_retrieval_profile(digest_mode: str | None) -> str:
    """Resolve the retrieval profile that should be used for doc generation."""

    course_type = resolve_digest_course_type(digest_mode)
    if course_type == SPRINT_COURSE_TYPE:
        return "docgen_sprint"
    return "docgen_systematic"


def resolve_planner_retrieval_profile() -> str:
    """Resolve the retrieval profile used by the planner grounding lane."""

    return PLANNER_RETRIEVAL_PROFILE


def resolve_teaching_action(action: str | None, *, fallback: str) -> str:
    """Normalize teaching-action labels so tracing metadata stays stable."""

    normalized = str(action or "").strip()
    return normalized or fallback


__all__ = [
    "DEFAULT_COURSE_TYPE",
    "DigestBuildConstraints",
    "DigestChapterContract",
    "DigestChapterMediaHints",
    "DigestConfirmedPlanContract",
    "PLANNER_RETRIEVAL_PROFILE",
    "SPRINT_COURSE_TYPE",
    "normalize_digest_confirmed_plan_payload",
    "parse_digest_confirmed_plan_contract",
    "resolve_digest_course_type",
    "resolve_digest_retrieval_profile",
    "resolve_planner_retrieval_profile",
    "resolve_teaching_action",
]
