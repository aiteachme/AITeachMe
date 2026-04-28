"""Shared build-contract helpers for digest planner and docgen lanes."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator


DEFAULT_DIGEST_MODE = "systematic"
SPRINT_DIGEST_MODE = "sprint"
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
    source_file_ids: list[int] = Field(default_factory=list)

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
    def _normalize_source_file_ids(cls, value: Any) -> list[int]:
        return _clean_int_list(value)

    def to_assignment(
        self,
        *,
        default_source_file_ids: list[int],
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
    include_sources: bool = True
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

class DigestConfirmedPlanContract(BaseModel):
    """Typed confirmed-plan contract shared by planner and docgen lanes."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    subject_name: str = Field(default="", validation_alias=AliasChoices("subject_name", "subject"))
    user_prompt: str = ""
    digest_mode: str = DEFAULT_DIGEST_MODE
    chapter_plan: list[DigestChapterContract] = Field(default_factory=list)
    build_constraints: DigestBuildConstraints = Field(default_factory=DigestBuildConstraints)
    plan_summary: str = ""
    selected_file_ids: list[int] = Field(default_factory=list)
    planner_session_id: str = ""
    confirmed_plan_id: str = ""
    mode_reason: str = ""

    @field_validator(
        "subject_name",
        "user_prompt",
        "digest_mode",
        "plan_summary",
        "planner_session_id",
        "confirmed_plan_id",
        "mode_reason",
        mode="before",
    )
    @classmethod
    def _normalize_text_fields(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("selected_file_ids", mode="before")
    @classmethod
    def _normalize_selected_file_ids(cls, value: Any) -> list[int]:
        return _clean_int_list(value)

    def normalized_digest_mode(self) -> str:
        return normalize_digest_mode(self.digest_mode)

    def resolve_retrieval_profile(self) -> str:
        return resolve_digest_retrieval_profile(
            self.digest_mode,
            user_prompt=self.user_prompt,
            subject_name=self.subject_name,
        )

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def to_chapter_assignments(self, *, default_source_file_ids: list[int]) -> list[dict[str, Any]]:
        return [
            chapter.to_assignment(
                default_source_file_ids=default_source_file_ids,
            )
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


def normalize_digest_mode(digest_mode: str | None) -> str:
    """Normalize the requested digest mode."""

    normalized = str(digest_mode or "").strip().lower()
    if normalized == SPRINT_DIGEST_MODE:
        return SPRINT_DIGEST_MODE
    return DEFAULT_DIGEST_MODE


_OI_TOPIC_KEYWORDS: tuple[str, ...] = (
    "信息学奥赛",
    "信息学竞赛",
    "算法竞赛",
    "程序设计竞赛",
)
_OI_ASCII_TOPIC_KEYWORDS: tuple[str, ...] = (
    "oi",
    "oi-wiki",
    "oiwiki",
    "noi",
    "noip",
    "csp-s",
    "csp-j",
    "acm",
    "icpc",
    "codeforces",
    "atcoder",
)
_MATH_TOPIC_KEYWORDS: tuple[str, ...] = (
    "数学",
    "初中数学",
    "小学数学",
    "高中数学",
    "高等数学",
    "线性代数",
    "概率论",
    "数与代数",
    "几何",
    "代数",
    "函数",
    "方程",
    "不等式",
    "三角",
    "统计",
    "概率",
    "中考",
)
_MATH_ASCII_TOPIC_KEYWORDS: tuple[str, ...] = (
    "math",
    "mathematics",
    "algebra",
    "geometry",
    "calculus",
)
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?")


def _looks_like_oi_topic(
    *,
    user_prompt: str | None,
    subject_name: str | None,
) -> bool:
    """Return True when the requested subject reads like an OI/algorithm-contest topic.

    We intentionally key off the user-facing labels (subject name and the
    build prompt) rather than content-derived signals. For non-file builds
    (e.g. "初中数学") a subject profile has not been recognized yet, so we
    must decide profile selection from what the user typed.
    """

    haystack = " ".join(
        part for part in (user_prompt, subject_name) if part and str(part).strip()
    ).lower()
    if not haystack:
        return False
    for keyword in _OI_TOPIC_KEYWORDS:
        if keyword in haystack:
            return True
    ascii_tokens = set(_ASCII_TOKEN_RE.findall(haystack))
    if ascii_tokens.intersection(_OI_ASCII_TOPIC_KEYWORDS):
        return True
    return False


def _looks_like_math_topic(
    *,
    user_prompt: str | None,
    subject_name: str | None,
) -> bool:
    haystack = " ".join(
        part for part in (user_prompt, subject_name) if part and str(part).strip()
    ).lower()
    if not haystack:
        return False
    for keyword in _MATH_TOPIC_KEYWORDS:
        if keyword in haystack:
            return True
    ascii_tokens = set(_ASCII_TOKEN_RE.findall(haystack))
    if ascii_tokens.intersection(_MATH_ASCII_TOPIC_KEYWORDS):
        return True
    return False


def resolve_digest_retrieval_profile(
    digest_mode: str | None,
    *,
    user_prompt: str | None = None,
    subject_name: str | None = None,
) -> str:
    """Resolve the retrieval profile that should be used for doc generation.

    The primary selector is still ``digest_mode`` (sprint vs systematic). On
    top of that we route explicit OI/algorithm-contest topics to the OI
    profile so OI Wiki is only consulted when the user actually asked for
    that domain. Math topics use a tighter Chinese math profile. Other topics
    stay on the default DocGen profiles and never see OI Wiki as a source,
    even as a ranking boost.
    """

    if _looks_like_oi_topic(user_prompt=user_prompt, subject_name=subject_name):
        return "docgen_oi"
    if _looks_like_math_topic(user_prompt=user_prompt, subject_name=subject_name):
        return "docgen_zh_math"

    normalized_mode = normalize_digest_mode(digest_mode)
    if normalized_mode == SPRINT_DIGEST_MODE:
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
    "DEFAULT_DIGEST_MODE",
    "DigestBuildConstraints",
    "DigestChapterContract",
    "DigestConfirmedPlanContract",
    "PLANNER_RETRIEVAL_PROFILE",
    "SPRINT_DIGEST_MODE",
    "normalize_digest_confirmed_plan_payload",
    "parse_digest_confirmed_plan_contract",
    "normalize_digest_mode",
    "resolve_digest_retrieval_profile",
    "resolve_planner_retrieval_profile",
    "resolve_teaching_action",
]
