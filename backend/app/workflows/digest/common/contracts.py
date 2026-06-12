"""Shared build-contract helpers for digest planner and docgen lanes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


DEFAULT_DIGEST_MODE = "systematic"
SPRINT_DIGEST_MODE = "sprint"
PLANNER_RETRIEVAL_PROFILE = "planner_grounding"
DOCGEN_BALANCED_RETRIEVAL_PROFILE = "docgen_balanced"
DOCGEN_ALLOWED_RETRIEVAL_PROFILES = frozenset(
    {
        DOCGEN_BALANCED_RETRIEVAL_PROFILE,
        "docgen_zh_math",
    }
)


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


def _clean_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


class DigestChapterContract(BaseModel):
    """A normalized, execution-ready chapter contract."""

    model_config = ConfigDict(extra="allow")

    chapter_index: int = Field(default=1, ge=1)
    title: str = ""
    resolved_title: str = ""
    objective: str = ""
    required_elements: list[str] = Field(default_factory=list)
    writing_instructions: str = ""
    source_file_ids: list[str] = Field(default_factory=list)

    @field_validator("title", "resolved_title", "objective", "writing_instructions", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("required_elements", mode="before")
    @classmethod
    def _normalize_string_list(cls, value: Any) -> list[str]:
        return _clean_string_list(value)

    @field_validator("source_file_ids", mode="before")
    @classmethod
    def _normalize_source_file_ids(cls, value: Any) -> list[str]:
        return _clean_string_list(value)

    def to_assignment(
        self,
        *,
        default_source_file_ids: list[str],
    ) -> dict[str, Any]:
        chapter_index = max(1, int(self.chapter_index or 1))
        title = self.title or f"第 {chapter_index} 章"
        return {
            "chapter_index": chapter_index,
            "title": title,
            "resolved_title": self.resolved_title,
            "objective": self.objective,
            "required_elements": list(self.required_elements),
            "writing_instructions": self.writing_instructions,
            "source_file_ids": list(self.source_file_ids or default_source_file_ids),
        }


class DigestBuildConstraints(BaseModel):
    """Normalized document build controls stored on a confirmed plan."""

    model_config = ConfigDict(extra="allow")

    include_exercises: bool = True
    include_sources: bool = False
    math_mode: bool = False
    min_chapters: int | None = None
    max_chapters: int | None = None
    target_chapter_count: int | None = None
    target_length: str = ""
    target_total_words: int | None = None

    @field_validator("target_total_words", mode="before")
    @classmethod
    def _normalize_target_total_words(cls, value: Any) -> int | None:
        return _clean_positive_int(value)

    @field_validator("target_length", mode="before")
    @classmethod
    def _normalize_target_length(cls, value: Any) -> str:
        return _clean_text(value)


class DigestPlannerDiagnosticQuestion(BaseModel):
    """A pre-diagnosis prompt frozen on the confirmed build plan."""

    model_config = ConfigDict(extra="ignore")

    question: str = ""
    purpose: str = ""
    sample_answers: list[str] = Field(default_factory=list)

    @field_validator("question", "purpose", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("sample_answers", mode="before")
    @classmethod
    def _normalize_sample_answers(cls, value: Any) -> list[str]:
        return _clean_string_list(value)


class DigestConfirmedPlanContract(BaseModel):
    """Typed confirmed-plan contract shared by planner and docgen lanes."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    course_name: str = ""
    course_icon: str = ""
    user_prompt: str = ""
    digest_mode: str = DEFAULT_DIGEST_MODE
    planning_note: str = ""
    suggestion: str = ""
    plan: str = ""
    chapters: list[DigestChapterContract] = Field(default_factory=list)
    diagnose: list[DigestPlannerDiagnosticQuestion] = Field(default_factory=list)
    build_constraints: DigestBuildConstraints = Field(default_factory=DigestBuildConstraints)
    selected_file_ids: list[str] = Field(default_factory=list)
    planner_session_id: str = ""
    confirmed_plan_id: str = ""
    model_override: str = ""
    mode_reason: str = ""
    retrieval_profile: str = ""
    docgen_history_brief: str = ""
    planner_context: dict[str, Any] = Field(default_factory=dict)

    @field_validator(
        "course_name",
        "course_icon",
        "user_prompt",
        "digest_mode",
        "planning_note",
        "suggestion",
        "plan",
        "planner_session_id",
        "confirmed_plan_id",
        "model_override",
        "mode_reason",
        "retrieval_profile",
        "docgen_history_brief",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("selected_file_ids", mode="before")
    @classmethod
    def _normalize_selected_file_ids(cls, value: Any) -> list[str]:
        return _clean_string_list(value)

    @field_validator("planner_context", mode="before")
    @classmethod
    def _normalize_planner_context(cls, value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    def normalized_digest_mode(self) -> str:
        return normalize_digest_mode(self.digest_mode)

    def resolve_retrieval_profile(self) -> str:
        return resolve_digest_retrieval_profile(
            self.digest_mode,
            retrieval_profile=self.retrieval_profile,
        )

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_chapter_assignments(self, *, default_source_file_ids: list[str]) -> list[dict[str, Any]]:
        return [
            chapter.to_assignment(
                default_source_file_ids=default_source_file_ids,
            )
            for chapter in self.chapters
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


def normalize_digest_mode(digest_mode: str | None) -> str:
    """Normalize the requested digest mode."""

    normalized = str(digest_mode or "").strip().lower()
    if normalized == SPRINT_DIGEST_MODE:
        return SPRINT_DIGEST_MODE
    return DEFAULT_DIGEST_MODE


def _normalize_docgen_retrieval_profile(value: str | None) -> str:
    profile = str(value or "").strip().lower()
    if profile in DOCGEN_ALLOWED_RETRIEVAL_PROFILES:
        return profile
    return ""


def resolve_digest_retrieval_profile(
    digest_mode: str | None,
    *,
    retrieval_profile: str | None = None,
    user_prompt: str | None = None,
    course_name: str | None = None,
) -> str:
    """Resolve the retrieval profile that should be used for doc generation.

    This is an internal retriever preset, not a teaching-mode label. Local code
    must not infer subject semantics from user-facing text. A specialized
    profile is used only when an upstream model-produced contract supplies it
    explicitly; otherwise the generic DocGen profile is safer.
    """

    del digest_mode, user_prompt, course_name
    return _normalize_docgen_retrieval_profile(retrieval_profile) or DOCGEN_BALANCED_RETRIEVAL_PROFILE


def build_digest_retrieval_policy(
    internal_profile: str | None,
    *,
    has_local_materials: bool,
    allow_external_search: bool = True,
    digest_mode: str | None = None,
    user_prompt: str | None = None,
    course_name: str | None = None,
) -> dict[str, Any]:
    """Build the user-facing retrieval policy from the internal preset."""

    profile = _normalize_docgen_retrieval_profile(internal_profile) or resolve_digest_retrieval_profile(
        digest_mode,
    )
    del user_prompt, course_name
    if profile == "docgen_zh_math":
        focus = "math_learning_sources"
        reason = "上游结构化合同显式选择数学学习检索 profile，优先使用数学学习资料补充。"
    else:
        focus = "general_learning_sources"
        reason = "未提供结构化专门检索 profile，使用通用学习资料检索策略。"
    return {
        "schema_version": 1,
        "local_first": bool(has_local_materials),
        "allow_web": bool(allow_external_search),
        "source_priority": ["local_materials", focus, "general_web"],
        "external_focus": focus,
        "reason": reason,
        "internal_profile": profile,
    }


def resolve_planner_retrieval_profile() -> str:
    """Resolve the retrieval profile used by the planner grounding lane."""

    return PLANNER_RETRIEVAL_PROFILE


def resolve_teaching_action(action: str | None, *, fallback: str) -> str:
    """Normalize teaching-action labels so tracing metadata stays stable."""

    normalized = str(action or "").strip()
    return normalized or fallback


__all__ = [
    "DEFAULT_DIGEST_MODE",
    "DOCGEN_ALLOWED_RETRIEVAL_PROFILES",
    "DOCGEN_BALANCED_RETRIEVAL_PROFILE",
    "DigestBuildConstraints",
    "DigestChapterContract",
    "DigestConfirmedPlanContract",
    "DigestPlannerDiagnosticQuestion",
    "PLANNER_RETRIEVAL_PROFILE",
    "SPRINT_DIGEST_MODE",
    "normalize_digest_confirmed_plan_payload",
    "parse_digest_confirmed_plan_contract",
    "normalize_digest_mode",
    "build_digest_retrieval_policy",
    "resolve_digest_retrieval_profile",
    "resolve_planner_retrieval_profile",
    "resolve_teaching_action",
]
