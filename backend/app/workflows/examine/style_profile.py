"""Exam style profile builder (sample-paper analysis, profile integration)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlmodel import Session

from app.models import (
    IngestStatus,
    RawFile,
    TaskStatus,
    is_paper_exam_mode,
    exam_mode_value,
)
from app.repositories.files_repo import list_raw_files_by_uids
from app.workflows.examine.context_helpers import (
    _unique_strings,
    normalize_difficulty_focus,
    truncate_text,
)
from app.workflows.profile.subject_profile import (
    SubjectProfileSummary,
    build_subject_profile_summary,
    load_subject_profile_summary,
)
from app.workflows.profile.user_profile import (
    UserProfileSummary,
    build_user_profile_summary,
    load_user_profile_summary,
)

_READY_INGEST_STATUSES = {
    IngestStatus.FAST_PARSED.value,
    IngestStatus.ENHANCING.value,
    IngestStatus.READY_FOR_DIGEST.value,
    IngestStatus.ENHANCE_FAILED.value,
}

_QUESTION_TYPE_PATTERNS: dict[str, re.Pattern[str]] = {
    "single_choice": re.compile(r"(选择题|单选题|单项选择题|choice)", re.IGNORECASE),
    "fill_blank": re.compile(r"(填空题|fill\s*in\s*the\s*blank|blank)", re.IGNORECASE),
    "short_answer": re.compile(r"(简答题|问答题|论述题|分析题|解答题|short\s*answer|essay)", re.IGNORECASE),
}

_QUESTION_COUNT_PATTERN = re.compile(
    r"(?m)^\s*(?:第?\s*\d+\s*题|\d+[\.、\)]|[一二三四五六七八九十]+[、.])"
)

_SECTION_TITLE_PATTERN = re.compile(
    r"(?m)^\s*(第[一二三四五六七八九十0-9]+部分.*|[一二三四五六七八九十]+、.*|"
    r"(?:单项选择题|选择题|填空题|简答题|问答题|综合题).*)$"
)


@dataclass(frozen=True)
class ExamStyleProfile:
    source_file_uids: list[str] = field(default_factory=list)
    title_hint: str = ""
    format_hint: str = "standard"
    section_titles: list[str] = field(default_factory=list)
    preferred_question_types: list[str] = field(default_factory=list)
    question_type_bias: dict[str, float] = field(default_factory=dict)
    recommended_question_count: int | None = None
    difficulty_focus: str | None = None
    focus_teaching_unit_ids: list[int] = field(default_factory=list)
    focus_node_ids: list[int] = field(default_factory=list)
    style_prompt: str | None = None
    focus_prompt: str | None = None
    user_prompt: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        lines: list[str] = []
        if self.title_hint:
            lines.append(f"- Paper title style: {self.title_hint}")
        if self.format_hint:
            lines.append(f"- Format hint: {self.format_hint}")
        if self.section_titles:
            lines.append(f"- Section style: {', '.join(self.section_titles[:4])}")
        if self.preferred_question_types:
            lines.append(f"- Preferred question types: {', '.join(self.preferred_question_types)}")
        if self.difficulty_focus:
            lines.append(f"- Difficulty focus: {self.difficulty_focus}")
        if self.focus_teaching_unit_ids:
            lines.append(
                "- Focus teaching units: "
                + ", ".join(str(item) for item in self.focus_teaching_unit_ids[:6])
            )
        if self.notes:
            lines.extend(f"- {note}" for note in self.notes[:6])
        if self.style_prompt:
            lines.append(f"- Style prompt: {self.style_prompt}")
        if self.focus_prompt:
            lines.append(f"- Focus prompt: {self.focus_prompt}")
        if self.user_prompt:
            lines.append(f"- General request: {self.user_prompt}")
        return "\n".join(lines)

    def to_metadata(self) -> dict[str, object]:
        return {
            "source_file_uids": list(self.source_file_uids),
            "title_hint": self.title_hint,
            "format_hint": self.format_hint,
            "section_titles": list(self.section_titles),
            "preferred_question_types": list(self.preferred_question_types),
            "question_type_bias": dict(self.question_type_bias),
            "recommended_question_count": self.recommended_question_count,
            "difficulty_focus": self.difficulty_focus,
            "focus_teaching_unit_ids": list(self.focus_teaching_unit_ids),
            "focus_node_ids": list(self.focus_node_ids),
            "style_prompt": self.style_prompt,
            "focus_prompt": self.focus_prompt,
            "user_prompt": self.user_prompt,
            "notes": list(self.notes),
        }


class TemplateSelectionHints(BaseModel):
    exam_mode: str | None = None
    preferred_question_types: list[str] = Field(default_factory=list)
    unit_mastery_score: float | None = None
    weak_node_names: list[str] = Field(default_factory=list)
    learning_objectives: list[str] = Field(default_factory=list)
    preferred_node_id: int | None = None
    style_profile: dict[str, object] = Field(default_factory=dict)
    focus_prompt: str | None = None
    user_prompt: str | None = None
    context_signature: str | None = None
    context_locked: bool = False
    scope_locked: bool = False
    focus_teaching_unit_ids: list[int] = Field(default_factory=list)
    focus_node_ids: list[int] = Field(default_factory=list)
    style_prompt_summary: str | None = None
    focus_prompt_summary: str | None = None


# ── Internal detection helpers ────────────────────────────────────────


def _markdown_ready(raw_file: RawFile) -> bool:
    return (
        raw_file.status == TaskStatus.COMPLETED.value
        and raw_file.ingest_status in _READY_INGEST_STATUSES
        and bool((raw_file.parsed_markdown or "").strip())
    )


def _normalize_bias(counter: Counter[str]) -> dict[str, float]:
    total = sum(counter.values())
    if total <= 0:
        return {}
    return {
        key: round(value / total, 4)
        for key, value in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        if value > 0
    }


def _guess_paper_title(sample_markdown: str) -> str:
    for line in sample_markdown.splitlines():
        candidate = line.strip().strip("#").strip()
        if len(candidate) < 6 or len(candidate) > 80:
            continue
        if "答案" in candidate:
            continue
        return candidate
    return ""


def _detect_question_type_bias(sample_markdown: str) -> dict[str, float]:
    counter: Counter[str] = Counter()
    for question_type, pattern in _QUESTION_TYPE_PATTERNS.items():
        counter[question_type] = len(pattern.findall(sample_markdown))
    return _normalize_bias(counter)


def _detect_section_titles(sample_markdown: str) -> list[str]:
    matches = [match.group(0).strip() for match in _SECTION_TITLE_PATTERN.finditer(sample_markdown)]
    return _unique_strings(matches)[:6]


def _detect_question_count(sample_markdown: str) -> int | None:
    matches = _QUESTION_COUNT_PATTERN.findall(sample_markdown)
    count = len(matches)
    return count if 4 <= count <= 80 else None


def _default_paper_exam_style_prompt() -> str:
    return (
        "如果没有参考样卷，也请按真实正式考试试卷的形式命题："
        "题干表达要规范克制，整卷尽量采用按题型分段、由易到难、适合打印演练的考卷风格。"
    )


# ── Profile integration helpers ──────────────────────────────────────


def _load_subject_profile_for_exam(
    session: Session,
    *,
    subject: str,
    user_id: str | None,
) -> SubjectProfileSummary | None:
    summary = load_subject_profile_summary(session, subject=subject)
    if summary is not None:
        return summary
    if not user_id:
        return None
    return build_subject_profile_summary(
        session,
        subject=subject,
        user_id=user_id,
    )


def _load_user_profile_for_exam(
    session: Session,
    *,
    user_id: str | None,
) -> UserProfileSummary | None:
    if not user_id:
        return None
    summary = load_user_profile_summary(session, user_id=user_id)
    if summary is not None:
        return summary
    return build_user_profile_summary(session, user_id=user_id)


def _merge_preferred_question_types(
    *,
    sample_types: list[str],
    subject_profile: SubjectProfileSummary | None,
    user_profile: UserProfileSummary | None,
) -> list[str]:
    merged = list(sample_types)
    if subject_profile is not None:
        merged.extend(subject_profile.recommended_question_types)
        merged.extend(subject_profile.preferred_question_types)
    if user_profile is not None:
        merged.extend(user_profile.preferred_question_types)
    return _unique_strings(merged)[:3]


def _build_profile_notes(
    *,
    subject_profile: SubjectProfileSummary | None,
    user_profile: UserProfileSummary | None,
) -> list[str]:
    notes: list[str] = []
    if subject_profile is not None:
        notes.append(
            f"Subject profile recommends `{subject_profile.recommended_exam_mode}` mode."
        )
        if subject_profile.focus_teaching_unit_ids:
            notes.append("Keep more questions on current weak teaching units.")
        if subject_profile.focus_knowledge_unit_ids:
            notes.append("Anchor explanations to current weak knowledge nodes.")
    if user_profile is not None:
        notes.append(f"User explanation style: {user_profile.explanation_style}.")
        notes.append(f"User pace preference: {user_profile.pace_preference}.")
    return notes


def _load_sample_files(
    session: Session,
    *,
    subject: str,
    sample_file_uids: list[str] | None,
) -> list[RawFile]:
    if not sample_file_uids:
        return []
    raw_files = list_raw_files_by_uids(session, subject, sample_file_uids)
    file_by_uid = {item.uid: item for item in raw_files}
    return [file_by_uid[uid] for uid in sample_file_uids if uid in file_by_uid]


# ── Main builder ─────────────────────────────────────────────────────


def build_exam_style_profile(
    session: Session,
    *,
    subject: str,
    user_id: str | None = None,
    sample_file_uids: list[str] | None = None,
    style_prompt: str | None = None,
    focus_prompt: str | None = None,
    user_prompt: str | None = None,
    difficulty: str | None = None,
    exam_mode: str = "web_practice",
) -> ExamStyleProfile:
    mode = exam_mode_value(exam_mode)
    sample_files = _load_sample_files(
        session,
        subject=subject,
        sample_file_uids=sample_file_uids,
    )
    ready_samples = [item for item in sample_files if _markdown_ready(item)]
    sample_markdown = "\n\n".join(
        truncate_text(item.parsed_markdown or "", max_chars=3500)
        for item in ready_samples
        if (item.parsed_markdown or "").strip()
    )
    subject_profile = _load_subject_profile_for_exam(
        session,
        subject=subject,
        user_id=user_id,
    )
    user_profile = _load_user_profile_for_exam(session, user_id=user_id)

    question_type_bias = _detect_question_type_bias(sample_markdown)
    preferred_question_types = _merge_preferred_question_types(
        sample_types=list(question_type_bias.keys()),
        subject_profile=subject_profile,
        user_profile=user_profile,
    )
    if not preferred_question_types and is_paper_exam_mode(mode):
        preferred_question_types = ["single_choice", "fill_blank", "short_answer"]
    normalized_style_prompt = (style_prompt or "").strip() or None
    uses_default_paper_exam_prompt = (
        is_paper_exam_mode(mode)
        and not ready_samples
        and normalized_style_prompt is None
    )
    if uses_default_paper_exam_prompt:
        normalized_style_prompt = _default_paper_exam_style_prompt()

    notes: list[str] = []
    if ready_samples:
        notes.append(f"Sample-paper references loaded: {len(ready_samples)}")
    elif sample_file_uids:
        notes.append("Sample-paper files were provided but no parsed markdown is ready yet.")
    if uses_default_paper_exam_prompt:
        notes.append("No ready sample paper found, so the built-in formal paper style prompt is enabled.")
    if re.search(r"(A[\.?\)]|B[\.?\)]|C[\.?\)]|D[\.?\)])", sample_markdown):
        notes.append("Choice questions should use labeled options.")
    if is_paper_exam_mode(mode):
        notes.append("Use section-based paper organization and a formal exam tone.")
    notes.extend(
        _build_profile_notes(
            subject_profile=subject_profile,
            user_profile=user_profile,
        )
    )

    recommended_question_count = _detect_question_count(sample_markdown)
    if recommended_question_count is None and subject_profile is not None:
        recommended_question_count = subject_profile.recommended_question_count

    explicit_difficulty_focus = normalize_difficulty_focus(difficulty)
    difficulty_focus = explicit_difficulty_focus
    if difficulty_focus is None and subject_profile is not None:
        difficulty_focus = subject_profile.difficulty_focus
    if difficulty_focus is not None and explicit_difficulty_focus is not None:
        notes.append(f"Explicit difficulty override: {difficulty_focus}")

    return ExamStyleProfile(
        source_file_uids=[item.uid for item in ready_samples if item.uid],
        title_hint=_guess_paper_title(sample_markdown),
        format_hint="paper_exam" if is_paper_exam_mode(mode) else "standard",
        section_titles=_detect_section_titles(sample_markdown),
        preferred_question_types=preferred_question_types,
        question_type_bias=question_type_bias,
        recommended_question_count=recommended_question_count,
        difficulty_focus=difficulty_focus,
        focus_teaching_unit_ids=(
            list(subject_profile.focus_teaching_unit_ids[:8])
            if subject_profile is not None
            else []
        ),
        focus_node_ids=(
            list(subject_profile.focus_knowledge_unit_ids[:12])
            if subject_profile is not None
            else []
        ),
        style_prompt=normalized_style_prompt,
        focus_prompt=(focus_prompt or "").strip() or None,
        user_prompt=(user_prompt or "").strip() or None,
        notes=_unique_strings(notes),
    )


import json


def load_template_selection_hints(raw: str | None) -> TemplateSelectionHints:
    if not raw:
        return TemplateSelectionHints()
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return TemplateSelectionHints()
    if not isinstance(decoded, dict):
        return TemplateSelectionHints()
    try:
        return TemplateSelectionHints.model_validate(decoded)
    except Exception:
        return TemplateSelectionHints()


def template_matches_request_context(
    raw_hints: str | None,
    *,
    requested_context_signature: str | None,
    context_locked: bool,
) -> bool:
    hints = load_template_selection_hints(raw_hints)
    if context_locked:
        if not requested_context_signature:
            return False
        return hints.context_signature == requested_context_signature
    return not hints.context_locked


__all__ = [
    "ExamStyleProfile",
    "TemplateSelectionHints",
    "build_exam_style_profile",
    "load_template_selection_hints",
    "template_matches_request_context",
]
