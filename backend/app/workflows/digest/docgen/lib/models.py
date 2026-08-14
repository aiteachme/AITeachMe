"""Typed contracts for the rewritten DocGen lane."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.workflows.digest.common.pedagogy import (
    is_usable_resolved_chapter_title,
    resolve_effective_chapter_title,
)


def clean_text(value: Any) -> str:
    return str(value or "").strip()


def clean_string_list(value: Any, *, limit: int | None = None) -> list[str]:
    items = value if isinstance(value, list) else ([] if value is None else [value])
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = clean_text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if limit is not None and len(cleaned) >= limit:
            break
    return cleaned


LEARNING_CONTENT_ROLE_TYPES: tuple[str, ...] = (
    "topic",
    "concept",
    "principle",
    "formula_model",
    "procedure",
    "skill",
    "misconception",
    "application_case",
)


def clean_content_role_targets(value: Any, *, item_limit: int = 8) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    cleaned: dict[str, list[str]] = {}
    for role in LEARNING_CONTENT_ROLE_TYPES:
        items = clean_string_list(value.get(role), limit=item_limit)
        if items:
            cleaned[role] = items
    return cleaned


def clean_example_coverage_plan(value: Any, *, limit: int = 16) -> list[dict[str, Any]]:
    items = value if isinstance(value, list) else ([] if value is None else [value])
    cleaned: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            target = clean_text(item.get("target"))
            example_type = clean_text(item.get("example_type") or item.get("type"))
            purpose = clean_text(item.get("purpose"))
            try:
                min_examples = int(item.get("min_examples", 1) or 1)
            except (TypeError, ValueError):
                min_examples = 1
        else:
            target = clean_text(item)
            example_type = ""
            purpose = ""
            min_examples = 1
        if not target:
            continue
        cleaned.append(
            {
                "target": target,
                "example_type": example_type or "worked_example_or_case",
                "purpose": purpose or "用例题、案例或任务验证这个知识点能被实际使用。",
                "min_examples": max(1, min(4, min_examples)),
            }
        )
        if len(cleaned) >= limit:
            break
    return cleaned


def clean_int_list(value: Any, *, limit: int | None = None) -> list[int]:
    items = value if isinstance(value, list) else ([] if value is None else [value])
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
        if limit is not None and len(cleaned) >= limit:
            break
    return cleaned


def clean_unit_float(value: Any, *, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, parsed))


def _resolve_task_title(
    *,
    chapter_index: int,
    confirmed_title: str,
    enhanced_title: str,
    objective: str = "",
    required_elements: list[str] | None = None,
    fallback_title: str = "",
) -> str:
    title = resolve_effective_chapter_title(
        {
            "chapter_index": chapter_index,
            "title": enhanced_title,
            "resolved_title": enhanced_title,
            "objective": objective,
            "chapter_goal": objective,
            "required_elements": list(required_elements or []),
        },
        chapter_index=chapter_index,
        fallback_title=confirmed_title or fallback_title,
    )
    if is_usable_resolved_chapter_title(title):
        return title
    cleaned_fallback = clean_text(confirmed_title or fallback_title)
    return cleaned_fallback or f"第 {chapter_index} 章"


class DocGenBaseModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class DocGenContext(DocGenBaseModel):
    course_id: str = Field(default="", validation_alias=AliasChoices("course_id", "course"))
    course_name: str = Field(default="", validation_alias=AliasChoices("course_name", "course_display_name"))
    digest_mode: str = "systematic"
    retrieval_profile: str = ""
    user_prompt: str = ""
    plan: str = ""
    docgen_history_brief: str = ""
    learner_profile_text: str = ""
    learner_profile_context: dict[str, Any] = Field(default_factory=dict)
    planner_context: dict[str, Any] = Field(default_factory=dict)
    diagnose: list[dict[str, Any]] = Field(default_factory=list)
    diagnose_status: str = ""
    diagnose_note: str = ""
    build_constraints: dict[str, Any] = Field(default_factory=dict)
    source_strategy: Literal["local_first", "web_first"] = "local_first"
    include_sources: bool = False
    local_source_count: int = 0
    section_count: int = 0

    @field_validator(
        "course_id",
        "course_name",
        "digest_mode",
        "retrieval_profile",
        "user_prompt",
        "plan",
        "docgen_history_brief",
        "learner_profile_text",
        "diagnose_status",
        "diagnose_note",
        mode="before",
    )
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)


class DocGenIntentProfile(DocGenBaseModel):
    learning_goal_text: str = ""
    audience_profile_text: str = ""
    content_strategy_text: str = ""
    example_practice_policy: str = ""
    source_usage_policy: str = ""
    teaching_intent: str = ""
    example_ratio: float = 0.35
    practice_ratio: float = 0.25
    evidence_strictness: float = 0.65
    review_strictness: float = 0.55
    document_style: str = "teaching_notes"
    depth_level: str = "standard"
    explanation_depth: str = "detailed"
    example_preference: str = "balanced"
    definition_depth: str = "standard"
    exam_orientation: float = 0.5
    review_orientation: float = 0.5
    chapter_style_hints: dict[int, str] = Field(default_factory=dict)
    avoid_list: list[str] = Field(default_factory=list)
    fallback_used: bool = False

    @model_validator(mode="before")
    @classmethod
    def _merge_legacy_compat(cls, value: Any) -> Any:
        if isinstance(value, dict) and isinstance(value.get("legacy_compat"), dict):
            legacy = dict(value.get("legacy_compat") or {})
            return {**legacy, **value}
        return value

    @field_validator(
        "learning_goal_text",
        "audience_profile_text",
        "content_strategy_text",
        "example_practice_policy",
        "source_usage_policy",
        "teaching_intent",
        "document_style",
        "depth_level",
        "explanation_depth",
        "example_preference",
        "definition_depth",
        mode="before",
    )
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("avoid_list", mode="before")
    @classmethod
    def _avoid_list(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=12)

    @field_validator(
        "example_ratio",
        "practice_ratio",
        "evidence_strictness",
        "review_strictness",
        "exam_orientation",
        "review_orientation",
        mode="before",
    )
    @classmethod
    def _unit_float(cls, value: Any) -> float:
        return clean_unit_float(value, default=0.5)

    @field_validator("chapter_style_hints", mode="before")
    @classmethod
    def _chapter_hints(cls, value: Any) -> dict[int, str]:
        if not isinstance(value, dict):
            return {}
        hints: dict[int, str] = {}
        for key, hint in value.items():
            try:
                index = int(key)
            except (TypeError, ValueError):
                continue
            text = clean_text(hint)
            if index > 0 and text:
                hints[index] = text
        return hints

    @model_validator(mode="after")
    def _derive_legacy_fields(self) -> "DocGenIntentProfile":
        """Keep old DocGen call sites stable while v2 intent fields become canonical."""

        if not self.teaching_intent:
            self.teaching_intent = self.content_strategy_text or self.learning_goal_text
        if self.example_preference not in {"few", "balanced", "many"}:
            if self.example_ratio >= 0.45 or self.practice_ratio >= 0.35:
                self.example_preference = "many"
            elif self.example_ratio <= 0.18 and self.practice_ratio <= 0.15:
                self.example_preference = "few"
            else:
                self.example_preference = "balanced"
        if self.depth_level not in {"compact", "standard", "deep"}:
            self.depth_level = "deep" if self.evidence_strictness >= 0.75 else "standard"
        if self.explanation_depth not in {"compact", "standard", "detailed"}:
            self.explanation_depth = "detailed" if self.evidence_strictness >= 0.55 else "standard"
        if self.definition_depth not in {"minimal", "standard", "strict"}:
            self.definition_depth = "strict" if self.evidence_strictness >= 0.78 else "standard"
        self.exam_orientation = max(self.exam_orientation, min(1.0, (self.practice_ratio * 0.7) + 0.15))
        self.review_orientation = max(self.review_orientation, self.review_strictness)
        return self


class ChapterSourceSlice(DocGenBaseModel):
    """One LLM-selected source slice assigned to a target chapter."""

    chapter_index: int = 1
    file_id: str = ""
    filename: str = ""
    section_ref: str = ""
    section_title: str = ""
    header_path: str = ""
    line_start: int | None = None
    line_end: int | None = None
    relevance: float = 0.5
    usage: str = "context"
    reason: str = ""
    summary: str = ""
    excerpt: str = ""

    @field_validator("filename", "section_ref", "section_title", "header_path", "usage", "reason", "summary", "excerpt", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("file_id", mode="before")
    @classmethod
    def _file_id(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("line_start", "line_end", mode="before")
    @classmethod
    def _line_no(cls, value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @field_validator("relevance", mode="before")
    @classmethod
    def _relevance(cls, value: Any) -> float:
        return clean_unit_float(value, default=0.5)


class FileMaterialSummary(DocGenBaseModel):
    file_id: str = ""
    filename: str = ""
    summary: str = ""
    concepts: list[str] = Field(default_factory=list)
    definitions: list[str] = Field(default_factory=list)
    formulas: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    question_types: list[str] = Field(default_factory=list)
    high_value_sections: list[str] = Field(default_factory=list)
    noise_sections: list[str] = Field(default_factory=list)
    chapter_affinity: dict[int, float] = Field(default_factory=dict)
    chapter_slices: list[ChapterSourceSlice] = Field(default_factory=list)
    source_quality: float = 0.5
    summary_mode: str = "fallback"
    fallback_used: bool = False
    llm_call_count: int = 0

    @field_validator("filename", "summary", "summary_mode", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator(
        "concepts",
        "definitions",
        "formulas",
        "examples",
        "question_types",
        "high_value_sections",
        "noise_sections",
        mode="before",
    )
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=16)

    @field_validator("chapter_affinity", mode="before")
    @classmethod
    def _affinity(cls, value: Any) -> dict[int, float]:
        if not isinstance(value, dict):
            return {}
        result: dict[int, float] = {}
        for key, raw_score in value.items():
            try:
                index = int(key)
            except (TypeError, ValueError):
                continue
            if index > 0:
                result[index] = clean_unit_float(raw_score)
        return result

    @field_validator("source_quality", mode="before")
    @classmethod
    def _source_quality(cls, value: Any) -> float:
        return clean_unit_float(value, default=0.5)

    @field_validator("llm_call_count", mode="before")
    @classmethod
    def _llm_call_count(cls, value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0


class FileMaterialSummaryBatch(DocGenBaseModel):
    files: list[FileMaterialSummary] = Field(default_factory=list)


class HighConfidenceEvidenceUnit(DocGenBaseModel):
    evidence_id: str = ""
    source_ref: str = ""
    source_type: str = "local"
    evidence_type: str = "background"
    text: str = ""
    chapter_affinity: dict[int, float] = Field(default_factory=dict)
    confidence: float = 0.5
    source_title: str = ""
    source_span: str = ""

    @field_validator("evidence_id", "source_ref", "source_type", "evidence_type", "text", "source_title", "source_span", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("chapter_affinity", mode="before")
    @classmethod
    def _affinity(cls, value: Any) -> dict[int, float]:
        if not isinstance(value, dict):
            return {}
        result: dict[int, float] = {}
        for key, raw_score in value.items():
            try:
                index = int(key)
            except (TypeError, ValueError):
                continue
            if index > 0:
                result[index] = clean_unit_float(raw_score)
        return result

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: Any) -> float:
        return clean_unit_float(value, default=0.5)


class SourceAffinityByChapter(DocGenBaseModel):
    chapter_index: int = 1
    file_ids: list[str] = Field(default_factory=list)
    section_refs: list[str] = Field(default_factory=list)
    source_slices: list[ChapterSourceSlice] = Field(default_factory=list)
    reason: str = ""

    @field_validator("file_ids", mode="before")
    @classmethod
    def _file_ids(cls, value: Any) -> list[str]:
        return clean_string_list(value)

    @field_validator("section_refs", mode="before")
    @classmethod
    def _section_refs(cls, value: Any) -> list[str]:
        return clean_string_list(value)

    @field_validator("reason", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)


class LockedChapterTitle(DocGenBaseModel):
    chapter_index: int = 1
    confirmed_title: str = ""
    enhanced_title: str = ""
    plan_mismatch_warnings: list[str] = Field(default_factory=list)
    fallback_used: bool = False

    @field_validator("confirmed_title", "enhanced_title", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("plan_mismatch_warnings", mode="before")
    @classmethod
    def _warnings(cls, value: Any) -> list[str]:
        return clean_string_list(value)


class ChapterExecutionBrief(DocGenBaseModel):
    chapter_index: int = 1
    teaching_outline: list[str] = Field(default_factory=list)
    writing_instructions: list[str] = Field(default_factory=list)
    content_role_targets: dict[str, list[str]] = Field(default_factory=dict)
    example_coverage_plan: list[dict[str, Any]] = Field(default_factory=list)
    chapter_end_practice_plan: list[dict[str, Any]] = Field(default_factory=list)
    concept_targets: list[str] = Field(default_factory=list)
    definition_targets: list[str] = Field(default_factory=list)
    formula_targets: list[str] = Field(default_factory=list)
    example_targets: list[str] = Field(default_factory=list)
    pitfall_targets: list[str] = Field(default_factory=list)
    retrieval_queries: list[str] = Field(default_factory=list)
    plan_mismatch_warnings: list[str] = Field(default_factory=list)
    fallback_used: bool = False

    @field_validator(
        "teaching_outline",
        "writing_instructions",
        "concept_targets",
        "definition_targets",
        "formula_targets",
        "example_targets",
        "pitfall_targets",
        "retrieval_queries",
        "plan_mismatch_warnings",
        mode="before",
    )
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value)

    @field_validator("content_role_targets", mode="before")
    @classmethod
    def _content_role_targets(cls, value: Any) -> dict[str, list[str]]:
        return clean_content_role_targets(value, item_limit=6)

    @field_validator("example_coverage_plan", "chapter_end_practice_plan", mode="before")
    @classmethod
    def _example_coverage_plan(cls, value: Any) -> list[dict[str, Any]]:
        return clean_example_coverage_plan(value, limit=12)


class ChapterBudgetPolicy(DocGenBaseModel):
    max_research_rounds: int = 2
    max_local_queries: int = 3
    max_web_queries: int = 3
    max_opened_urls: int = 4
    max_context_chars: int = 6000
    max_writer_retries: int = 0


class ChapterGenerationTaskSeed(DocGenBaseModel):
    chapter_index: int = 1
    confirmed_title: str = ""
    enhanced_title: str = ""
    chapter_goal: str = ""
    mode: str = "systematic"
    priority_file_ids: list[str] = Field(default_factory=list)
    required_elements: list[str] = Field(default_factory=list)
    forbidden_scope: list[str] = Field(default_factory=list)
    retrieval_queries: list[str] = Field(default_factory=list)
    priority_section_refs: list[str] = Field(default_factory=list)
    source_slices: list[ChapterSourceSlice] = Field(default_factory=list)
    preferred_sources: list[str] = Field(default_factory=list)
    fallback_policy: str = "publish_readable_markdown"
    target_length: int = 1200
    style_rules: list[str] = Field(default_factory=list)
    citation_policy: str = "global_reference_block"
    uncertainty_policy: str = "state_uncertainty_and_avoid_fabrication"
    allowed_assets: list[str] = Field(default_factory=list)

    @field_validator("confirmed_title", "enhanced_title", "chapter_goal", "mode", "fallback_policy", "citation_policy", "uncertainty_policy", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator(
        "required_elements",
        "forbidden_scope",
        "retrieval_queries",
        "priority_section_refs",
        "preferred_sources",
        "style_rules",
        "allowed_assets",
        mode="before",
    )
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value)

    @field_validator("priority_file_ids", mode="before")
    @classmethod
    def _priority_file_ids(cls, value: Any) -> list[str]:
        return clean_string_list(value)

    @model_validator(mode="after")
    def _finish(self) -> "ChapterGenerationTaskSeed":
        resolved_title = _resolve_task_title(
            chapter_index=self.chapter_index,
            confirmed_title=self.confirmed_title,
            enhanced_title=self.enhanced_title,
            objective=self.chapter_goal,
            required_elements=self.required_elements,
        )
        if not is_usable_resolved_chapter_title(self.enhanced_title):
            self.enhanced_title = resolved_title
        if not is_usable_resolved_chapter_title(self.confirmed_title):
            self.confirmed_title = self.enhanced_title
        if not self.retrieval_queries:
            self.retrieval_queries = clean_string_list([self.enhanced_title, *self.required_elements])
        if self.target_length <= 0:
            self.target_length = 1200
        return self


class ChapterGenerationPlanSeed(DocGenBaseModel):
    course_name: str = Field(default="", validation_alias=AliasChoices("course_name", "course"))
    digest_mode: str = "systematic"
    source_policy: str = "local_first"
    writing_rules: list[str] = Field(default_factory=list)
    chapter_format: list[str] = Field(default_factory=list)
    budget_policy: dict[str, Any] = Field(default_factory=dict)
    chapters: list[ChapterGenerationTaskSeed] = Field(default_factory=list)
    plan_mismatch_warnings: list[str] = Field(default_factory=list)

    @field_validator("course_name", "digest_mode", "source_policy", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("writing_rules", "chapter_format", "plan_mismatch_warnings", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value)


class BackboneResearchAgenda(DocGenBaseModel):
    topics: list[str] = Field(default_factory=list)
    section_refs: list[str] = Field(default_factory=list)
    evidence_unit_ids: list[str] = Field(default_factory=list)
    glossary_candidates: list[str] = Field(default_factory=list)
    notation_candidates: list[str] = Field(default_factory=list)
    confusion_candidates: list[str] = Field(default_factory=list)

    @field_validator(
        "topics",
        "section_refs",
        "evidence_unit_ids",
        "glossary_candidates",
        "notation_candidates",
        "confusion_candidates",
        mode="before",
    )
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value)


class ChapterGenerationTask(DocGenBaseModel):
    chapter_index: int = 1
    confirmed_title: str = ""
    enhanced_title: str = ""
    objective: str = ""
    teaching_outline: list[str] = Field(default_factory=list)
    content_role_targets: dict[str, list[str]] = Field(default_factory=dict)
    example_coverage_plan: list[dict[str, Any]] = Field(default_factory=list)
    chapter_end_practice_plan: list[dict[str, Any]] = Field(default_factory=list)
    content_points: list[str] = Field(default_factory=list)
    concept_targets: list[str] = Field(default_factory=list)
    definition_targets: list[str] = Field(default_factory=list)
    formula_targets: list[str] = Field(default_factory=list)
    example_targets: list[str] = Field(default_factory=list)
    pitfall_targets: list[str] = Field(default_factory=list)
    priority_file_ids: list[str] = Field(default_factory=list)
    priority_section_refs: list[str] = Field(default_factory=list)
    source_slices: list[ChapterSourceSlice] = Field(default_factory=list)
    retrieval_queries: list[str] = Field(default_factory=list)
    writing_rules: list[str] = Field(default_factory=list)
    required_elements: list[str] = Field(default_factory=list)
    forbidden_scope: list[str] = Field(default_factory=list)
    preferred_sources: list[str] = Field(default_factory=list)
    fallback_policy: str = "publish_readable_markdown"
    style_rules: list[str] = Field(default_factory=list)
    citation_policy: str = "global_reference_block"
    uncertainty_policy: str = "state_uncertainty_and_avoid_fabrication"
    allowed_assets: list[str] = Field(default_factory=list)
    dependency_refs: list[str] = Field(default_factory=list)
    forward_refs: list[str] = Field(default_factory=list)
    claim_targets: list[str] = Field(default_factory=list)
    confusion_targets: list[str] = Field(default_factory=list)
    coverage_threshold: float = 0.62
    evidence_support_threshold: float = 0.5
    repetition_tolerance: float = 0.35
    patch_tolerance: float = 0.35
    placeholder_requests: list[dict[str, Any]] = Field(default_factory=list)
    practice_seed_policy: dict[str, Any] = Field(default_factory=dict)
    min_word_count: int = 700
    target_word_count: int = 1200
    budget_policy: ChapterBudgetPolicy = Field(default_factory=ChapterBudgetPolicy)

    @field_validator("confirmed_title", "enhanced_title", "objective", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator(
        "teaching_outline",
        "content_points",
        "concept_targets",
        "definition_targets",
        "formula_targets",
        "example_targets",
        "pitfall_targets",
        "priority_section_refs",
        "retrieval_queries",
        "writing_rules",
        "required_elements",
        "forbidden_scope",
        "preferred_sources",
        "style_rules",
        "allowed_assets",
        "dependency_refs",
        "forward_refs",
        "claim_targets",
        "confusion_targets",
        mode="before",
    )
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value)

    @field_validator("content_role_targets", mode="before")
    @classmethod
    def _task_content_role_targets(cls, value: Any) -> dict[str, list[str]]:
        return clean_content_role_targets(value, item_limit=10)

    @field_validator("example_coverage_plan", "chapter_end_practice_plan", mode="before")
    @classmethod
    def _task_example_coverage_plan(cls, value: Any) -> list[dict[str, Any]]:
        return clean_example_coverage_plan(value, limit=24)

    @field_validator("fallback_policy", "citation_policy", "uncertainty_policy", mode="before")
    @classmethod
    def _policy_text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("coverage_threshold", "evidence_support_threshold", "repetition_tolerance", "patch_tolerance", mode="before")
    @classmethod
    def _unit_float(cls, value: Any) -> float:
        return clean_unit_float(value, default=0.5)

    @field_validator("priority_file_ids", mode="before")
    @classmethod
    def _int_list(cls, value: Any) -> list[str]:
        return clean_string_list(value)

    @model_validator(mode="after")
    def _finish(self) -> "ChapterGenerationTask":
        resolved_title = _resolve_task_title(
            chapter_index=self.chapter_index,
            confirmed_title=self.confirmed_title,
            enhanced_title=self.enhanced_title,
            objective=self.objective,
            required_elements=[
                *self.required_elements,
                *self.content_points,
                *self.concept_targets,
                *self.definition_targets,
                *self.formula_targets,
                *self.example_targets,
                *self.pitfall_targets,
            ],
        )
        if not is_usable_resolved_chapter_title(self.enhanced_title):
            self.enhanced_title = resolved_title
        if not is_usable_resolved_chapter_title(self.confirmed_title):
            self.confirmed_title = self.enhanced_title
        if not self.retrieval_queries:
            self.retrieval_queries = clean_string_list([self.enhanced_title, *self.content_points])
        if not self.required_elements:
            self.required_elements = clean_string_list(
                [
                    *self.content_points,
                    *self.concept_targets,
                    *self.definition_targets,
                    *self.formula_targets,
                    *self.example_targets,
                    *self.pitfall_targets,
                ],
            )
        if not self.style_rules:
            self.style_rules = list(self.writing_rules)
        if not self.claim_targets:
            self.claim_targets = clean_string_list([*self.required_elements, *self.concept_targets])
        if not self.allowed_assets:
            self.allowed_assets = clean_string_list(
                [str(item.get("kind") or "") for item in self.placeholder_requests if isinstance(item, dict)],
            )
        if self.min_word_count <= 0:
            self.min_word_count = 700
        if self.target_word_count < self.min_word_count:
            self.target_word_count = max(self.min_word_count, 1200)
        return self


class ChapterGenerationPlan(DocGenBaseModel):
    course_name: str = Field(default="", validation_alias=AliasChoices("course_name", "course"))
    digest_mode: str = "systematic"
    source_policy: str = "local_first"
    writing_rules: list[str] = Field(default_factory=list)
    chapter_format: list[str] = Field(default_factory=list)
    budget_policy: dict[str, Any] = Field(default_factory=dict)
    chapters: list[ChapterGenerationTask] = Field(default_factory=list)
    plan_mismatch_warnings: list[str] = Field(default_factory=list)

    @field_validator("course_name", "digest_mode", "source_policy", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("writing_rules", "chapter_format", "plan_mismatch_warnings", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value)


class CanonicalGlossaryItem(DocGenBaseModel):
    term: str = ""
    aliases: list[str] = Field(default_factory=list)
    definition: str = ""
    source_hint: str = ""
    target_chapters: list[int] = Field(default_factory=list)

    @field_validator("term", "definition", "source_hint", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("aliases", mode="before")
    @classmethod
    def _aliases(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=8)

    @field_validator("target_chapters", mode="before")
    @classmethod
    def _chapters(cls, value: Any) -> list[int]:
        return clean_int_list(value, limit=12)


class ConceptDependencyEdge(DocGenBaseModel):
    from_concept: str = ""
    to_concept: str = ""
    relation: str = "prerequisite_for"
    reason: str = ""

    @field_validator("from_concept", "to_concept", "relation", "reason", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)


class NotationItem(DocGenBaseModel):
    symbol: str = ""
    meaning: str = ""
    target_chapters: list[int] = Field(default_factory=list)
    source_hint: str = ""

    @field_validator("symbol", "meaning", "source_hint", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("target_chapters", mode="before")
    @classmethod
    def _chapters(cls, value: Any) -> list[int]:
        return clean_int_list(value, limit=12)


class CanonicalClaim(DocGenBaseModel):
    claim_id: str = ""
    claim_type: str = "background"
    claim_text: str = ""
    target_chapter: int | None = None
    importance: float = 0.5
    requires_evidence: bool = True
    source_hint: str = ""

    @field_validator("claim_id", "claim_type", "claim_text", "source_hint", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("importance", mode="before")
    @classmethod
    def _importance(cls, value: Any) -> float:
        return clean_unit_float(value, default=0.5)


class ConfusionItem(DocGenBaseModel):
    confusion_id: str = ""
    topic: str = ""
    contrast: str = ""
    resolution_hint: str = ""
    target_chapters: list[int] = Field(default_factory=list)

    @field_validator("confusion_id", "topic", "contrast", "resolution_hint", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("target_chapters", mode="before")
    @classmethod
    def _chapters(cls, value: Any) -> list[int]:
        return clean_int_list(value, limit=12)


class BackboneConflictWarning(DocGenBaseModel):
    warning_id: str = ""
    severity: Literal["info", "warning", "error"] = "warning"
    detail: str = ""
    chapter_refs: list[int] = Field(default_factory=list)

    @field_validator("warning_id", "detail", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("chapter_refs", mode="before")
    @classmethod
    def _chapters(cls, value: Any) -> list[int]:
        return clean_int_list(value, limit=12)


class DocumentBackbone(DocGenBaseModel):
    canonical_glossary: list[CanonicalGlossaryItem] = Field(default_factory=list)
    concept_dependency_graph: list[ConceptDependencyEdge] = Field(default_factory=list)
    notation_registry: list[NotationItem] = Field(default_factory=list)
    canonical_claim_pool: list[CanonicalClaim] = Field(default_factory=list)
    confusion_map: list[ConfusionItem] = Field(default_factory=list)
    source_trust_summary: dict[str, Any] = Field(default_factory=dict)
    fallback_used: bool = False


class DocumentPreparationBundle(DocGenBaseModel):
    """One whole-document LLM result consumed before chapter fan-out."""

    document_backbone: DocumentBackbone = Field(default_factory=DocumentBackbone)
    chapter_execution_briefs: list[ChapterExecutionBrief] = Field(default_factory=list)


class ChapterResearchTrace(DocGenBaseModel):
    chapter_index: int = 1
    rounds: list[dict[str, Any]] = Field(default_factory=list)
    executed_queries: list[str] = Field(default_factory=list)
    opened_contexts: list[dict[str, Any]] = Field(default_factory=list)
    stop_reason: str = ""
    budget_used: dict[str, Any] = Field(default_factory=dict)
    coverage_score: float = 0.0
    gap_notes: list[str] = Field(default_factory=list)


class EvidenceItem(DocGenBaseModel):
    evidence_id: str = ""
    kind: str = "background"
    claim: str = ""
    source_type: str = "generated"
    source_ref: str = ""
    source_title: str = ""
    source_span: str = ""
    confidence: float = 0.5
    used_in_markdown: bool = False


class EvidenceLedger(DocGenBaseModel):
    chapter_index: int = 1
    items: list[EvidenceItem] = Field(default_factory=list)


class EvidenceUnit(DocGenBaseModel):
    evidence_id: str = ""
    chapter_index: int = 1
    evidence_type: str = "background"
    text: str = ""
    source_ref: str = ""
    source_span: str = ""
    confidence: float = 0.5

    @field_validator("evidence_id", "evidence_type", "text", "source_ref", "source_span", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence(cls, value: Any) -> float:
        return clean_unit_float(value, default=0.5)


class ClaimItem(DocGenBaseModel):
    claim_id: str = ""
    chapter_index: int = 1
    claim_type: str = "background"
    claim_text: str = ""
    importance: float = 0.5
    requires_evidence: bool = True
    source_hint: str = ""
    evidence_ids: list[str] = Field(default_factory=list)

    @field_validator("claim_id", "claim_type", "claim_text", "source_hint", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def _evidence_ids(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=12)

    @field_validator("importance", mode="before")
    @classmethod
    def _importance(cls, value: Any) -> float:
        return clean_unit_float(value, default=0.5)


class ClaimLedger(DocGenBaseModel):
    chapter_index: int = 1
    items: list[ClaimItem] = Field(default_factory=list)
    fallback_used: bool = False


class ClaimEvidenceBinding(DocGenBaseModel):
    claim_id: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    support_level: float = 0.0
    notes: str = ""

    @field_validator("claim_id", "notes", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("evidence_ids", mode="before")
    @classmethod
    def _evidence_ids(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=12)

    @field_validator("support_level", mode="before")
    @classmethod
    def _support_level(cls, value: Any) -> float:
        return clean_unit_float(value, default=0.0)


class ClaimEvidenceMap(DocGenBaseModel):
    chapter_index: int = 1
    bindings: list[ClaimEvidenceBinding] = Field(default_factory=list)
    fallback_used: bool = False


class ConflictItem(DocGenBaseModel):
    conflict_id: str = ""
    chapter_index: int = 1
    conflict_type: str = "scope"
    severity: Literal["info", "warning", "error"] = "warning"
    detail: str = ""
    resolution: str = ""
    source_refs: list[str] = Field(default_factory=list)

    @field_validator("conflict_id", "conflict_type", "detail", "resolution", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("source_refs", mode="before")
    @classmethod
    def _source_refs(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=12)


class ConflictReport(DocGenBaseModel):
    chapter_index: int = 1
    items: list[ConflictItem] = Field(default_factory=list)
    unresolved_count: int = 0
    fallback_used: bool = False


class ChapterQualitySignals(DocGenBaseModel):
    coverage_score: float = 0.0
    quality_score: float = 0.0
    rewrite_used: bool = False
    warnings: list[str] = Field(default_factory=list)
    critic_summary: str = ""


class ChapterDraft(DocGenBaseModel):
    chapter_index: int = 1
    title: str = ""
    markdown: str = ""
    summary_draft: str = ""
    research_trace: ChapterResearchTrace = Field(default_factory=ChapterResearchTrace)
    evidence_ledger: EvidenceLedger = Field(default_factory=EvidenceLedger)
    claim_ledger_ref: str = ""
    conflict_warning_refs: list[str] = Field(default_factory=list)
    source_scope: dict[str, Any] = Field(default_factory=dict)
    quality_signals: ChapterQualitySignals = Field(default_factory=ChapterQualitySignals)
    placeholder_requests: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    source_details: list[dict[str, Any]] = Field(default_factory=list)
    fallback_used: bool = False


class EnhancedChapterDraft(DocGenBaseModel):
    chapter_index: int = 1
    title: str = ""
    markdown: str = ""
    summary: str = ""
    evidence_ledger: EvidenceLedger = Field(default_factory=EvidenceLedger)
    claim_ledger_ref: str = ""
    conflict_warning_refs: list[str] = Field(default_factory=list)
    quality_signals: ChapterQualitySignals = Field(default_factory=ChapterQualitySignals)
    source_scope: dict[str, Any] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    source_details: list[dict[str, Any]] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    practice_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    fallback_used: bool = False


class ReviewedChapterDraft(EnhancedChapterDraft):
    review_report_ref: str = ""
    patched: bool = False


class AssetManifest(DocGenBaseModel):
    assets: list[dict[str, Any]] = Field(default_factory=list)


class PracticeManifest(DocGenBaseModel):
    questions: list[dict[str, Any]] = Field(default_factory=list)


class MergeReviewIssue(DocGenBaseModel):
    severity: Literal["warning", "error"] = "warning"
    chapter_index: int | None = None
    issue_type: str = "quality"
    detail: str = ""
    suggestion: str = ""


class MergeReviewReport(DocGenBaseModel):
    passed: bool = True
    decision: Literal["publish", "publish_with_warnings", "fail"] = "publish"
    issues: list[MergeReviewIssue] = Field(default_factory=list)
    coverage_summary: dict[str, Any] = Field(default_factory=dict)
    style_summary: dict[str, Any] = Field(default_factory=dict)
    source_summary: dict[str, Any] = Field(default_factory=dict)


class ChapterReviewReport(DocGenBaseModel):
    report_id: str = ""
    chapter_index: int = 1
    passed: bool = True
    coverage_score: float = 0.0
    evidence_support_score: float = 0.0
    quality_score: float = 0.0
    missing_elements: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    review_mode: str = ""
    llm_action_count: int = 0
    rule_action_count: int = 0

    @field_validator("report_id", "review_mode", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("missing_elements", "warnings", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=18)


class ChapterReviewActionSuggestion(DocGenBaseModel):
    action_type: Literal[
        "surface_patch",
        "section_patch",
        "evidence_patch",
        "regenerate_chapter",
        "record_only",
        "re_dispatch",
        "rebuild_backbone",
    ] = "record_only"
    severity: Literal["info", "warning", "error"] = "warning"
    reason: str = ""
    target_anchor: str = ""
    instruction: str = ""
    constraints: list[str] = Field(default_factory=list)
    expected_effect: str = ""

    @field_validator("reason", "target_anchor", "instruction", "expected_effect", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("constraints", mode="before")
    @classmethod
    def _constraints(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=12)


class LLMChapterReviewResult(DocGenBaseModel):
    passed: bool = True
    coverage_score: float = 1.0
    evidence_support_score: float = 1.0
    quality_score: float = 1.0
    missing_elements: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    actions: list[ChapterReviewActionSuggestion] = Field(default_factory=list)

    @field_validator("coverage_score", "evidence_support_score", "quality_score", mode="before")
    @classmethod
    def _unit_float(cls, value: Any) -> float:
        return clean_unit_float(value, default=0.0)

    @field_validator("missing_elements", "warnings", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=18)


class DocumentConsistencyReport(DocGenBaseModel):
    passed: bool = True
    issues: list[dict[str, Any]] = Field(default_factory=list)
    glossary_warnings: list[str] = Field(default_factory=list)
    source_summary: dict[str, Any] = Field(default_factory=dict)
    fallback_used: bool = False

    @field_validator("glossary_warnings", mode="before")
    @classmethod
    def _warnings(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=24)


class ReviewAction(DocGenBaseModel):
    action_id: str = ""
    action_type: Literal[
        "surface_patch",
        "section_patch",
        "evidence_patch",
        "regenerate_chapter",
        "record_only",
        "re_dispatch",
        "rebuild_backbone",
    ] = "surface_patch"
    chapter_index: int | None = None
    severity: Literal["info", "warning", "error"] = "warning"
    reason: str = ""
    target_anchor: str = ""
    instruction: str = ""
    constraints: list[str] = Field(default_factory=list)
    expected_effect: str = ""
    status: Literal["recorded", "applied", "skipped", "downgraded"] = "recorded"

    @field_validator("action_id", "reason", "target_anchor", "instruction", "expected_effect", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("constraints", mode="before")
    @classmethod
    def _constraints(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=12)


class LLMDocumentConsistencyReviewResult(DocGenBaseModel):
    passed: bool = True
    issues: list[dict[str, Any]] = Field(default_factory=list)
    glossary_warnings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    actions: list[ReviewAction] = Field(default_factory=list)

    @field_validator("glossary_warnings", "warnings", mode="before")
    @classmethod
    def _warnings(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=18)


class RepairTraceItem(DocGenBaseModel):
    trace_id: str = ""
    action_id: str = ""
    action_type: str = ""
    chapter_index: int | None = None
    status: Literal["recorded", "applied", "skipped", "downgraded"] = "recorded"
    reason: str = ""
    target_anchor: str = ""
    changed: bool = False
    llm_attempted: bool = False
    llm_call_group: str = ""
    detail: str = ""

    @field_validator("trace_id", "action_id", "action_type", "reason", "target_anchor", "detail", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)


__all__ = [
    "AssetManifest",
    "BackboneConflictWarning",
    "BackboneResearchAgenda",
    "CanonicalClaim",
    "CanonicalGlossaryItem",
    "ChapterBudgetPolicy",
    "ChapterDraft",
    "ChapterGenerationPlanSeed",
    "ChapterGenerationPlan",
    "ChapterGenerationTaskSeed",
    "ChapterGenerationTask",
    "ChapterQualitySignals",
    "ChapterReviewActionSuggestion",
    "ChapterReviewReport",
    "ChapterResearchTrace",
    "ChapterSourceSlice",
    "ClaimEvidenceBinding",
    "ClaimEvidenceMap",
    "ClaimItem",
    "ClaimLedger",
    "ConceptDependencyEdge",
    "ConfusionItem",
    "ConflictItem",
    "ConflictReport",
    "DocumentBackbone",
    "DocumentPreparationBundle",
    "DocumentConsistencyReport",
    "DocGenContext",
    "DocGenIntentProfile",
    "EnhancedChapterDraft",
    "EvidenceItem",
    "EvidenceLedger",
    "EvidenceUnit",
    "FileMaterialSummary",
    "FileMaterialSummaryBatch",
    "HighConfidenceEvidenceUnit",
    "LLMChapterReviewResult",
    "LLMDocumentConsistencyReviewResult",
    "LEARNING_CONTENT_ROLE_TYPES",
    "MergeReviewIssue",
    "MergeReviewReport",
    "NotationItem",
    "PracticeManifest",
    "RepairTraceItem",
    "ReviewAction",
    "ReviewedChapterDraft",
    "SourceAffinityByChapter",
    "clean_int_list",
    "clean_content_role_targets",
    "clean_example_coverage_plan",
    "clean_string_list",
    "clean_text",
    "clean_unit_float",
]
