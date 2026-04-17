"""Typed contracts for the rewritten DocGen lane."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class DocGenBaseModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class DocGenContext(DocGenBaseModel):
    subject: str = ""
    subject_display_name: str = ""
    digest_mode: str = "systematic"
    course_type: str = "systematic"
    retrieval_profile: str = ""
    tone: str = "encouraging"
    user_goal: str = ""
    plan_summary: str = ""
    source_strategy: Literal["local_first", "web_first"] = "local_first"
    include_sources: bool = True
    selected_skillpacks: list[str] = Field(default_factory=list)
    skillpack_guidance: str = ""
    recommended_tool_tags: list[str] = Field(default_factory=list)
    local_source_count: int = 0
    section_count: int = 0

    @field_validator(
        "subject",
        "subject_display_name",
        "digest_mode",
        "course_type",
        "retrieval_profile",
        "tone",
        "user_goal",
        "plan_summary",
        "skillpack_guidance",
        mode="before",
    )
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("selected_skillpacks", "recommended_tool_tags", mode="before")
    @classmethod
    def _string_list(cls, value: Any) -> list[str]:
        return clean_string_list(value)


class DocGenIntentProfile(DocGenBaseModel):
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

    @field_validator(
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

    @field_validator("exam_orientation", "review_orientation", mode="before")
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


class FileMaterialSummary(DocGenBaseModel):
    file_id: int = 0
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
    source_quality: float = 0.5
    summary_mode: str = "fallback"
    fallback_used: bool = False

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


class FileMaterialSummaryBatch(DocGenBaseModel):
    files: list[FileMaterialSummary] = Field(default_factory=list)


class EnhancedChapterOutline(DocGenBaseModel):
    chapter_index: int = 1
    confirmed_title: str = ""
    enhanced_title: str = ""
    objective: str = ""
    teaching_outline: list[str] = Field(default_factory=list)
    content_points: list[str] = Field(default_factory=list)
    concept_targets: list[str] = Field(default_factory=list)
    definition_targets: list[str] = Field(default_factory=list)
    formula_targets: list[str] = Field(default_factory=list)
    example_targets: list[str] = Field(default_factory=list)
    pitfall_targets: list[str] = Field(default_factory=list)
    summary_targets: list[str] = Field(default_factory=list)
    media_requests: list[dict[str, Any]] = Field(default_factory=list)
    practice_seed_policy: dict[str, Any] = Field(default_factory=dict)
    retrieval_queries: list[str] = Field(default_factory=list)
    plan_mismatch_warnings: list[str] = Field(default_factory=list)
    fallback_used: bool = False

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
        "summary_targets",
        "retrieval_queries",
        "plan_mismatch_warnings",
        mode="before",
    )
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=16)


class EnhancedChapterOutlineBatch(DocGenBaseModel):
    chapters: list[EnhancedChapterOutline] = Field(default_factory=list)
    plan_mismatch_warnings: list[str] = Field(default_factory=list)

    @field_validator("plan_mismatch_warnings", mode="before")
    @classmethod
    def _warnings(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=12)


class ChapterBudgetPolicy(DocGenBaseModel):
    max_research_rounds: int = 2
    max_local_queries: int = 3
    max_web_queries: int = 3
    max_opened_urls: int = 4
    max_context_chars: int = 6000
    max_writer_retries: int = 1


class ChapterGenerationTask(DocGenBaseModel):
    chapter_index: int = 1
    confirmed_title: str = ""
    enhanced_title: str = ""
    objective: str = ""
    teaching_outline: list[str] = Field(default_factory=list)
    content_points: list[str] = Field(default_factory=list)
    concept_targets: list[str] = Field(default_factory=list)
    definition_targets: list[str] = Field(default_factory=list)
    formula_targets: list[str] = Field(default_factory=list)
    example_targets: list[str] = Field(default_factory=list)
    pitfall_targets: list[str] = Field(default_factory=list)
    priority_file_ids: list[int] = Field(default_factory=list)
    priority_section_refs: list[str] = Field(default_factory=list)
    retrieval_queries: list[str] = Field(default_factory=list)
    writing_rules: list[str] = Field(default_factory=list)
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
        mode="before",
    )
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=18)

    @field_validator("priority_file_ids", mode="before")
    @classmethod
    def _int_list(cls, value: Any) -> list[int]:
        return clean_int_list(value, limit=12)

    @model_validator(mode="after")
    def _finish(self) -> "ChapterGenerationTask":
        if not self.enhanced_title:
            self.enhanced_title = self.confirmed_title or f"第 {self.chapter_index} 章"
        if not self.confirmed_title:
            self.confirmed_title = self.enhanced_title
        if not self.retrieval_queries:
            self.retrieval_queries = clean_string_list([self.enhanced_title, *self.content_points], limit=6)
        if self.min_word_count <= 0:
            self.min_word_count = 700
        if self.target_word_count < self.min_word_count:
            self.target_word_count = max(self.min_word_count, 1200)
        return self


class ChapterGenerationPlan(DocGenBaseModel):
    subject: str = ""
    digest_mode: str = "systematic"
    tone: str = "encouraging"
    source_policy: str = "local_first"
    writing_rules: list[str] = Field(default_factory=list)
    chapter_format: list[str] = Field(default_factory=list)
    budget_policy: dict[str, Any] = Field(default_factory=dict)
    chapters: list[ChapterGenerationTask] = Field(default_factory=list)
    plan_mismatch_warnings: list[str] = Field(default_factory=list)

    @field_validator("subject", "digest_mode", "tone", "source_policy", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("writing_rules", "chapter_format", "plan_mismatch_warnings", mode="before")
    @classmethod
    def _lists(cls, value: Any) -> list[str]:
        return clean_string_list(value, limit=16)


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
    quality_signals: ChapterQualitySignals = Field(default_factory=ChapterQualitySignals)
    sources: list[str] = Field(default_factory=list)
    source_details: list[dict[str, Any]] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    practice_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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


__all__ = [
    "AssetManifest",
    "ChapterBudgetPolicy",
    "ChapterDraft",
    "ChapterGenerationPlan",
    "ChapterGenerationTask",
    "ChapterQualitySignals",
    "ChapterResearchTrace",
    "DocGenContext",
    "DocGenIntentProfile",
    "EnhancedChapterDraft",
    "EnhancedChapterOutline",
    "EnhancedChapterOutlineBatch",
    "EvidenceItem",
    "EvidenceLedger",
    "FileMaterialSummary",
    "FileMaterialSummaryBatch",
    "MergeReviewIssue",
    "MergeReviewReport",
    "PracticeManifest",
    "clean_int_list",
    "clean_string_list",
    "clean_text",
    "clean_unit_float",
]
