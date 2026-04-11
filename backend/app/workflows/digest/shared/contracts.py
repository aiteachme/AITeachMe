"""Shared build-contract helpers for digest planner and docgen lanes."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


DEFAULT_COURSE_TYPE = "systematic"
SPRINT_COURSE_TYPE = "sprint"
PLANNER_RETRIEVAL_PROFILE = "planner_grounding"
_COVERAGE_SPLIT_RE = re.compile(r"[，。；：、,.!?！？/\n]|以及|并且|然后|再|先|后|与|和|及")


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


def _clean_unit_float(value: Any, *, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))


def _build_coverage_requirements(required_elements: list[str], objective: str) -> list[str]:
    targets = list(required_elements or [])
    for fragment in _COVERAGE_SPLIT_RE.split(_clean_text(objective)):
        cleaned = fragment.strip()
        if len(cleaned) < 2:
            continue
        targets.append(cleaned)
    return _clean_string_list(targets)


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


class DigestMediaQuota(BaseModel):
    """Execution quota for chapter sidecar assets."""

    model_config = ConfigDict(extra="allow")

    mermaid: int = 0
    images: int = 0
    interactive_html: int = 0
    animation: int = 0

    @field_validator("mermaid", "images", "interactive_html", "animation", mode="before")
    @classmethod
    def _normalize_quota(cls, value: Any) -> int:
        return max(0, int(_clean_positive_int(value) or 0))


class DigestPracticeQuota(BaseModel):
    """Execution quota for practice content injected into a chapter or course."""

    model_config = ConfigDict(extra="allow")

    short_answer: int = 0
    self_check: int = 0
    reasoning: int = 0
    application: int = 0

    @field_validator("short_answer", "self_check", "reasoning", "application", mode="before")
    @classmethod
    def _normalize_quota(cls, value: Any) -> int:
        return max(0, int(_clean_positive_int(value) or 0))


class DigestChapterExecutionContract(BaseModel):
    """Hard execution contract consumed by research and writing runtimes."""

    model_config = ConfigDict(extra="allow")

    target_word_count: int = 0
    min_word_count: int = 0
    coverage_requirements: list[str] = Field(default_factory=list)
    min_coverage_score: float = 0.0
    explanation_depth: str = ""
    repair_enabled: bool = True
    quality_hint: str = ""
    media_quota: DigestMediaQuota = Field(default_factory=DigestMediaQuota)
    practice_quota: DigestPracticeQuota = Field(default_factory=DigestPracticeQuota)

    @field_validator("target_word_count", "min_word_count", mode="before")
    @classmethod
    def _normalize_word_count(cls, value: Any) -> int:
        return max(0, int(_clean_positive_int(value) or 0))

    @field_validator("coverage_requirements", mode="before")
    @classmethod
    def _normalize_coverage_requirements(cls, value: Any) -> list[str]:
        return _clean_string_list(value)

    @field_validator("min_coverage_score", mode="before")
    @classmethod
    def _normalize_min_coverage_score(cls, value: Any) -> float:
        return _clean_unit_float(value)

    @field_validator("explanation_depth", "quality_hint", mode="before")
    @classmethod
    def _normalize_text(cls, value: Any) -> str:
        return _clean_text(value)


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
    execution_contract: DigestChapterExecutionContract = Field(default_factory=DigestChapterExecutionContract)
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

    def to_assignment(
        self,
        *,
        default_source_file_ids: list[int],
        digest_mode: str = DEFAULT_COURSE_TYPE,
        total_chapters: int | None = None,
        build_constraints: "DigestBuildConstraints | None" = None,
        media_plan: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        chapter_index = max(1, int(self.chapter_index or 1))
        title = self.title or f"第 {chapter_index} 章"
        execution_contract = _build_execution_contract(
            digest_mode=digest_mode,
            chapter_index=chapter_index,
            total_chapters=total_chapters,
            required_elements=list(self.required_elements),
            objective=self.objective,
            media_hints=self.media_hints,
            build_constraints=build_constraints,
            media_plan=media_plan,
            override=self.execution_contract,
        )
        return {
            "chapter_index": chapter_index,
            "title": title,
            "resolved_title": self.resolved_title,
            "objective": self.objective,
            "required_elements": list(self.required_elements),
            "search_queries": list(self.search_queries),
            "writing_instructions": self.writing_instructions,
            "media_hints": self.media_hints.model_dump(mode="json"),
            "execution_contract": execution_contract.model_dump(mode="json"),
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
    min_coverage_score: float = 0.0
    quality_floor: float = 0.0

    @field_validator("target_total_words", mode="before")
    @classmethod
    def _normalize_target_total_words(cls, value: Any) -> int | None:
        return _clean_positive_int(value)

    @field_validator("target_length", mode="before")
    @classmethod
    def _normalize_target_length(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("min_coverage_score", "quality_floor", mode="before")
    @classmethod
    def _normalize_score(cls, value: Any) -> float:
        return _clean_unit_float(value)


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
        total_chapters = len(self.chapter_plan)
        return [
            chapter.to_assignment(
                default_source_file_ids=default_source_file_ids,
                digest_mode=self.resolve_course_type(),
                total_chapters=total_chapters,
                build_constraints=self.build_constraints,
                media_plan=self.media_plan,
            )
            for chapter in self.chapter_plan
        ]


def _build_execution_contract(
    *,
    digest_mode: str,
    chapter_index: int,
    total_chapters: int | None,
    required_elements: list[str],
    objective: str,
    media_hints: DigestChapterMediaHints,
    build_constraints: DigestBuildConstraints | None,
    media_plan: Mapping[str, Any] | None,
    override: DigestChapterExecutionContract | None,
) -> DigestChapterExecutionContract:
    course_type = resolve_digest_course_type(digest_mode)
    chapter_count = max(1, int(total_chapters or 1))
    target_total_words = int(getattr(build_constraints, "target_total_words", 0) or 0)
    if target_total_words <= 0:
        target_total_words = 6800 if course_type == SPRINT_COURSE_TYPE else max(10000, chapter_count * 1400)
    per_chapter_target = max(650 if course_type == SPRINT_COURSE_TYPE else 1100, int(target_total_words / chapter_count))
    per_chapter_min = max(450 if course_type == SPRINT_COURSE_TYPE else 750, int(per_chapter_target * 0.68))

    coverage_requirements = _build_coverage_requirements(required_elements, objective)
    enable_interactive = bool((media_plan or {}).get("enable_interactive_html", False))
    mermaid_quota = 1 if media_hints.mermaid else 0
    if course_type != SPRINT_COURSE_TYPE and chapter_index == 1:
        mermaid_quota = max(1, mermaid_quota)

    image_quota = 1 if media_hints.images else 0
    interactive_quota = 1 if enable_interactive and media_hints.interactive else 0
    if enable_interactive and not interactive_quota and any(
        marker in requirement for marker in ("公式", "推导", "对比", "辨析", "关系")
        for requirement in coverage_requirements
    ):
        interactive_quota = 1

    if build_constraints and not build_constraints.include_exercises:
        practice_quota = DigestPracticeQuota()
    elif course_type == SPRINT_COURSE_TYPE:
        practice_quota = DigestPracticeQuota(short_answer=2, self_check=3, reasoning=1, application=1)
    else:
        practice_quota = DigestPracticeQuota(short_answer=1, self_check=1, reasoning=2, application=2)

    base_contract = DigestChapterExecutionContract(
        target_word_count=per_chapter_target,
        min_word_count=per_chapter_min,
        coverage_requirements=coverage_requirements,
        min_coverage_score=(
            float(getattr(build_constraints, "min_coverage_score", 0.0) or 0.0)
            or (0.6 if course_type == SPRINT_COURSE_TYPE else 0.72)
        ),
        explanation_depth="compact" if course_type == SPRINT_COURSE_TYPE else "detailed",
        repair_enabled=True,
        quality_hint="exam_oriented" if course_type == SPRINT_COURSE_TYPE else "systematic_depth",
        media_quota=DigestMediaQuota(
            mermaid=mermaid_quota,
            images=image_quota,
            interactive_html=interactive_quota,
            animation=0,
        ),
        practice_quota=practice_quota,
    )
    if override is None:
        return base_contract
    override_payload = override.model_dump(mode="json", exclude_none=True)
    if _is_blank_execution_contract_payload(override_payload):
        return base_contract
    merged_payload = base_contract.model_dump(mode="json")
    for key, value in override_payload.items():
        if key in {"media_quota", "practice_quota"}:
            nested = dict(merged_payload.get(key) or {})
            nested.update(value or {})
            merged_payload[key] = nested
            continue
        merged_payload[key] = value
    return DigestChapterExecutionContract.model_validate(merged_payload)


def _is_blank_execution_contract_payload(payload: Mapping[str, Any]) -> bool:
    for key, value in payload.items():
        if isinstance(value, Mapping):
            if not _is_blank_execution_contract_payload(value):
                return False
            continue
        if key == "repair_enabled" and value is True:
            continue
        if value not in (0, 0.0, "", False, None, [], {}):
            return False
    return True


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
    "DigestChapterExecutionContract",
    "DigestChapterMediaHints",
    "DigestMediaQuota",
    "DigestPracticeQuota",
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
