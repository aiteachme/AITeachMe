"""Shared context builders for the examine workflow."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.models import (
    IngestStatus,
    KnowledgeNode,
    RawFile,
    TaskStatus,
    TeachingUnit,
    UserKnowledgeState,
    is_paper_exam_mode,
    normalize_exam_mode,
)
from app.repositories import profile_repo
from app.repositories.files_repo import list_raw_files_by_uids
from app.repositories.knowledge import curriculum_repo, kg_repo
from app.utils.path_helpers import (
    build_merged_knowledge_base_build_path,
    build_merged_knowledge_base_path,
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
class NodeExamContext:
    node_id: int
    node_name: str
    summary: str
    body: str
    role: str
    coverage_weight: float
    mastery_score: float | None = None
    is_weak: bool = False

    @property
    def content(self) -> str:
        return "\n".join(part for part in [self.summary.strip(), self.body.strip()] if part)


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


@dataclass(frozen=True)
class UnitExamContext:
    subject: str
    unit_id: int
    unit_name: str
    unit_summary: str
    unit_body: str
    learning_objectives: list[str]
    doc_excerpt: str
    node_contexts: list[NodeExamContext]
    unit_mastery_score: float | None
    recent_mistakes: list[dict[str, str]]
    weak_node_names: list[str]
    style_profile: ExamStyleProfile
    exam_mode: str
    preferred_question_types: list[str]
    requested_question_count: int
    user_prompt: str | None = None
    focus_prompt: str | None = None

    def prompt_block(self) -> str:
        objective_lines = [f"- {item}" for item in self.learning_objectives[:5]]
        node_lines = [
            (
                f"- {item.node_name} | role={item.role} | mastery={_format_mastery(item.mastery_score)} | "
                f"weak={'yes' if item.is_weak else 'no'}\n"
                f"  {truncate_text(item.content, max_chars=320)}"
            )
            for item in self.node_contexts[:6]
        ]
        mistake_lines = [
            f"- Wrong before: {truncate_text(item.get('question_stem', ''), max_chars=100)}"
            for item in self.recent_mistakes[:3]
        ]
        parts = [
            f"Subject: {self.subject}",
            f"Unit: {self.unit_name}",
            f"Unit mastery: {_format_mastery(self.unit_mastery_score)}",
            f"Exam mode: {self.exam_mode}",
            f"Preferred question types: {', '.join(self.preferred_question_types) or 'auto'}",
        ]
        if self.learning_objectives:
            parts.append("Learning objectives:\n" + "\n".join(objective_lines))
        if self.unit_summary.strip():
            parts.append("Unit summary:\n" + truncate_text(self.unit_summary, max_chars=500))
        if self.unit_body.strip():
            parts.append("Unit body hints:\n" + truncate_text(self.unit_body, max_chars=650))
        if self.doc_excerpt.strip():
            parts.append("Knowledge document excerpt:\n" + truncate_text(self.doc_excerpt, max_chars=900))
        if node_lines:
            parts.append("Knowledge graph anchors:\n" + "\n".join(node_lines))
        if self.weak_node_names:
            parts.append(f"Weak nodes: {', '.join(self.weak_node_names[:8])}")
        if mistake_lines:
            parts.append("Recent mistakes:\n" + "\n".join(mistake_lines))
        style_block = self.style_profile.to_prompt_block()
        if style_block:
            parts.append("Paper style profile:\n" + style_block)
        if self.focus_prompt:
            parts.append(f"Focus prompt: {self.focus_prompt}")
        if self.user_prompt:
            parts.append(f"General user prompt: {self.user_prompt}")
        return "\n\n".join(part for part in parts if part.strip())


def truncate_text(text: str, *, max_chars: int) -> str:
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _format_mastery(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.2f}"


def _markdown_ready(raw_file: RawFile) -> bool:
    return (
        raw_file.status == TaskStatus.COMPLETED.value
        and raw_file.ingest_status in _READY_INGEST_STATUSES
        and bool((raw_file.parsed_markdown or "").strip())
    )


def _parse_json_list(raw: str | None) -> list[object]:
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return decoded if isinstance(decoded, list) else []


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in values:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _normalize_int_list(values: list[int] | None) -> list[int]:
    if not values:
        return []
    ordered = sorted({int(item) for item in values if int(item) > 0})
    return ordered


def summarize_hint_text(text: str | None, *, max_chars: int = 120) -> str | None:
    normalized = truncate_text(text or "", max_chars=max_chars)
    return normalized or None


def has_explicit_exam_context(
    *,
    style_prompt: str | None = None,
    focus_prompt: str | None = None,
    sample_file_uids: list[str] | None = None,
    teaching_unit_ids: list[int] | None = None,
    theme_tree_node_id: int | None = None,
) -> bool:
    return any(
        [
            bool((style_prompt or "").strip()),
            bool((focus_prompt or "").strip()),
            bool(sample_file_uids),
            bool(teaching_unit_ids),
            theme_tree_node_id is not None,
        ]
    )


def build_template_context_signature(
    *,
    curriculum_version_id: int | None,
    exam_mode: str,
    preferred_question_types: list[str] | None,
    difficulty_focus: str | None,
    context_locked: bool,
    scope_locked: bool,
    scope_unit_ids: list[int] | None = None,
    style_prompt: str | None = None,
    focus_prompt: str | None = None,
    sample_file_uids: list[str] | None = None,
) -> str:
    payload = {
        "curriculum_version_id": int(curriculum_version_id or 0),
        "exam_mode": normalize_exam_mode(exam_mode),
        "preferred_question_types": _unique_strings(preferred_question_types or []),
        "difficulty_focus": normalize_difficulty_focus(difficulty_focus),
        "context_locked": context_locked,
        "scope_locked": scope_locked,
        "scope_unit_ids": (_normalize_int_list(scope_unit_ids) if scope_locked else []),
        "style_prompt": ((style_prompt or "").strip() if context_locked else ""),
        "focus_prompt": ((focus_prompt or "").strip() if context_locked else ""),
        "sample_file_uids": (list(dict.fromkeys(sample_file_uids or [])) if context_locked else []),
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


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


def normalize_difficulty_focus(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    aliases = {
        "auto": "",
        "adaptive": "",
        "profile": "",
        "normal": "medium",
        "moderate": "medium",
        "challenging": "hard",
    }
    normalized = aliases.get(normalized, normalized)
    allowed = {"easy", "medium", "hard", "mixed"}
    return normalized if normalized in allowed else None


def read_knowledge_doc_text(subject: str) -> str:
    for path in [
        build_merged_knowledge_base_path(subject),
        build_merged_knowledge_base_build_path(subject),
    ]:
        if not path.exists():
            continue
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            continue
    return ""


def _split_markdown_blocks(markdown: str) -> list[str]:
    return [block.strip() for block in re.split(r"\n\s*\n", markdown or "") if block.strip()]


def _extract_doc_excerpt(markdown: str, terms: list[str], *, max_chars: int = 1500) -> str:
    normalized_terms = _unique_strings([term for term in terms if term])
    if not markdown.strip():
        return ""

    blocks = _split_markdown_blocks(markdown)
    if not blocks:
        return truncate_text(markdown, max_chars=max_chars)

    scored: list[tuple[int, int, str]] = []
    lowered_terms = [term.lower() for term in normalized_terms]
    for index, block in enumerate(blocks):
        lowered = block.lower()
        hit_count = sum(1 for term in lowered_terms if term and term in lowered)
        if hit_count <= 0:
            continue
        size_penalty = abs(len(block) - 360)
        scored.append((hit_count, -size_penalty, f"{index}:{block}"))

    if not scored:
        return truncate_text(markdown, max_chars=max_chars)

    picked_blocks: list[str] = []
    for _, _, packed in sorted(scored, reverse=True):
        _, block = packed.split(":", 1)
        picked_blocks.append(block)
        if len("\n\n".join(picked_blocks)) >= max_chars or len(picked_blocks) >= 4:
            break
    return truncate_text("\n\n".join(picked_blocks), max_chars=max_chars)


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
        if subject_profile.focus_node_ids:
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
    mode = normalize_exam_mode(exam_mode)
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

    notes: list[str] = []
    if ready_samples:
        notes.append(f"Sample-paper references loaded: {len(ready_samples)}")
    elif sample_file_uids:
        notes.append("Sample-paper files were provided but no parsed markdown is ready yet.")
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
            list(subject_profile.focus_node_ids[:12])
            if subject_profile is not None
            else []
        ),
        style_prompt=(style_prompt or "").strip() or None,
        focus_prompt=(focus_prompt or "").strip() or None,
        user_prompt=(user_prompt or "").strip() or None,
        notes=_unique_strings(notes),
    )


def _resolve_node_content(session: Session, node_id: int) -> tuple[KnowledgeNode | None, str, str]:
    resolved = kg_repo.get_node_with_current_revision(session, node_id)
    if resolved is None:
        node = session.get(KnowledgeNode, node_id)
        if node is None:
            return None, "", ""
        return node, node.summary or "", node.body_markdown or node.body or ""

    node, revision = resolved
    summary = revision.summary or node.summary or ""
    body = revision.body or node.body_markdown or node.body or ""
    return node, summary, body


def _load_teaching_units_by_id(
    session: Session,
    *,
    unit_ids: list[int],
) -> dict[int, TeachingUnit]:
    unique_ids = sorted({int(unit_id) for unit_id in unit_ids if int(unit_id) > 0})
    if not unique_ids:
        return {}

    rows = list(session.exec(select(TeachingUnit).where(TeachingUnit.id.in_(unique_ids))).all())
    return {int(unit.id): unit for unit in rows if unit.id is not None}


def _load_unit_memberships(
    units: list[TeachingUnit],
) -> dict[int, list[tuple[int, str, float]]]:
    memberships_by_unit: dict[int, list[tuple[int, str, float]]] = {}
    for unit in units:
        if unit.id is None:
            continue

        memberships: list[tuple[int, str, float]] = []
        for item in _parse_json_list(unit.member_node_refs_json):
            if not isinstance(item, dict):
                continue
            raw_node_id = item.get("knowledge_node_id")
            if not isinstance(raw_node_id, int) or raw_node_id <= 0:
                continue
            memberships.append(
                (
                    raw_node_id,
                    str(item.get("role", "primary")),
                    float(item.get("score", 0.0) or 0.0),
                )
            )
        memberships_by_unit[int(unit.id)] = memberships
    return memberships_by_unit


def _load_knowledge_nodes_by_id(
    session: Session,
    *,
    node_ids: list[int],
) -> dict[int, KnowledgeNode]:
    unique_ids = sorted({int(node_id) for node_id in node_ids if int(node_id) > 0})
    if not unique_ids:
        return {}

    rows = list(session.exec(select(KnowledgeNode).where(KnowledgeNode.id.in_(unique_ids))).all())
    return {int(node.id): node for node in rows if node.id is not None}


def _load_node_content_map(
    session: Session,
    *,
    node_ids: list[int],
) -> dict[int, tuple[str, str]]:
    content_by_id: dict[int, tuple[str, str]] = {}
    for node_id in sorted({int(item) for item in node_ids if int(item) > 0}):
        _, summary, body = _resolve_node_content(session, node_id)
        content_by_id[node_id] = (summary, body)
    return content_by_id


def _load_unit_state_map(
    session: Session,
    *,
    user_id: str,
    subject: str,
    unit_ids: list[int],
) -> dict[int, UserKnowledgeState]:
    unique_ids = sorted({int(unit_id) for unit_id in unit_ids if int(unit_id) > 0})
    if not unique_ids:
        return {}

    rows = list(
        session.exec(
            select(UserKnowledgeState).where(
                UserKnowledgeState.user_id == user_id,
                UserKnowledgeState.subject == subject,
                UserKnowledgeState.teaching_unit_id.in_(unique_ids),
                UserKnowledgeState.knowledge_node_id.is_(None),
            )
        ).all()
    )
    return {
        int(state.teaching_unit_id): state
        for state in rows
        if state.teaching_unit_id is not None
    }


def _load_node_state_map(
    session: Session,
    *,
    user_id: str,
    subject: str,
    node_ids: list[int],
) -> dict[int, UserKnowledgeState]:
    unique_ids = sorted({int(node_id) for node_id in node_ids if int(node_id) > 0})
    if not unique_ids:
        return {}

    rows = list(
        session.exec(
            select(UserKnowledgeState).where(
                UserKnowledgeState.user_id == user_id,
                UserKnowledgeState.subject == subject,
                UserKnowledgeState.knowledge_node_id.in_(unique_ids),
                UserKnowledgeState.teaching_unit_id.is_(None),
            )
        ).all()
    )
    return {
        int(state.knowledge_node_id): state
        for state in rows
        if state.knowledge_node_id is not None
    }


def _build_node_contexts_for_unit(
    *,
    unit_id: int,
    memberships_by_unit: dict[int, list[tuple[int, str, float]]],
    node_by_id: dict[int, KnowledgeNode],
    node_content_by_id: dict[int, tuple[str, str]],
    node_state_by_id: dict[int, UserKnowledgeState],
    weak_node_ids: set[int],
) -> list[NodeExamContext]:
    contexts: list[NodeExamContext] = []
    for node_id, role, score in memberships_by_unit.get(unit_id, []):
        node = node_by_id.get(node_id)
        if node is None:
            continue

        mastery_state = node_state_by_id.get(node_id)
        summary, body = node_content_by_id.get(
            node_id,
            (node.summary or "", node.body_markdown or node.body or ""),
        )
        contexts.append(
            NodeExamContext(
                node_id=node_id,
                node_name=node.canonical_name,
                summary=summary,
                body=body,
                role=role,
                coverage_weight=score or 1.0,
                mastery_score=(mastery_state.mastery_score if mastery_state is not None else None),
                is_weak=node_id in weak_node_ids,
            )
        )
    return contexts


def build_unit_exam_contexts(
    session: Session,
    *,
    subject: str,
    user_id: str,
    unit_ids: list[int],
    questions_per_unit: int,
    exam_mode: str,
    preferred_question_types: list[str] | None = None,
    user_prompt: str | None = None,
    focus_prompt: str | None = None,
    style_profile: ExamStyleProfile | None = None,
) -> list[UnitExamContext]:
    mode = normalize_exam_mode(exam_mode)
    doc_text = read_knowledge_doc_text(subject)
    style = style_profile or build_exam_style_profile(
        session,
        subject=subject,
        user_id=user_id,
        focus_prompt=focus_prompt,
        user_prompt=user_prompt,
        exam_mode=mode,
    )
    weak_node_ids = {
        int(state.knowledge_node_id)
        for state in profile_repo.list_weak_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            threshold=0.8,
            target_kind="node",
        )
        if state.knowledge_node_id is not None
    }
    units_by_id = _load_teaching_units_by_id(session, unit_ids=unit_ids)
    ordered_units = [
        units_by_id[int(unit_id)]
        for unit_id in unit_ids
        if int(unit_id) in units_by_id and units_by_id[int(unit_id)].id is not None
    ]
    memberships_by_unit = _load_unit_memberships(ordered_units)
    all_node_ids = [
        node_id
        for memberships in memberships_by_unit.values()
        for node_id, _, _ in memberships
    ]
    node_by_id = _load_knowledge_nodes_by_id(session, node_ids=all_node_ids)
    node_content_by_id = _load_node_content_map(session, node_ids=all_node_ids)
    unit_state_by_id = _load_unit_state_map(
        session,
        user_id=user_id,
        subject=subject,
        unit_ids=[int(unit.id) for unit in ordered_units if unit.id is not None],
    )
    node_state_by_id = _load_node_state_map(
        session,
        user_id=user_id,
        subject=subject,
        node_ids=all_node_ids,
    )

    contexts: list[UnitExamContext] = []
    for unit in ordered_units:
        if unit.id is None:
            continue

        node_contexts = _build_node_contexts_for_unit(
            unit_id=int(unit.id),
            memberships_by_unit=memberships_by_unit,
            node_by_id=node_by_id,
            node_content_by_id=node_content_by_id,
            node_state_by_id=node_state_by_id,
            weak_node_ids=weak_node_ids,
        )
        learning_objectives = [
            str(item).strip()
            for item in _parse_json_list(unit.learning_objectives_json)
            if str(item).strip()
        ]
        unit_state = unit_state_by_id.get(int(unit.id))
        search_terms = [unit.canonical_name, unit.title] + [item.node_name for item in node_contexts]
        doc_excerpt = _extract_doc_excerpt(doc_text, search_terms)
        weak_node_names = [item.node_name for item in node_contexts if item.is_weak]
        recent_mistakes = profile_repo.list_recent_wrong_attempt_summaries(
            session,
            user_id=user_id,
            subject=subject,
            teaching_unit_id=int(unit.id),
            knowledge_node_ids=[item.node_id for item in node_contexts],
            limit=3,
        )
        contexts.append(
            UnitExamContext(
                subject=subject,
                unit_id=int(unit.id),
                unit_name=unit.canonical_name,
                unit_summary=unit.summary,
                unit_body=unit.body_markdown,
                learning_objectives=learning_objectives,
                doc_excerpt=doc_excerpt,
                node_contexts=node_contexts,
                unit_mastery_score=(unit_state.mastery_score if unit_state is not None else None),
                recent_mistakes=recent_mistakes,
                weak_node_names=weak_node_names,
                style_profile=style,
                exam_mode=mode,
                preferred_question_types=list(preferred_question_types or style.preferred_question_types),
                requested_question_count=max(1, int(questions_per_unit)),
                user_prompt=(user_prompt or "").strip() or None,
                focus_prompt=(focus_prompt or "").strip() or None,
            )
        )
    return contexts


def build_grading_knowledge_context(
    session: Session,
    *,
    subject: str,
    teaching_unit_id: int | None = None,
    node_ids: list[int] | None = None,
    max_chars: int = 1800,
    knowledge_doc_text: str | None = None,
) -> str:
    unique_node_ids = [node_id for node_id in dict.fromkeys(node_ids or []) if int(node_id) > 0]
    unit = curriculum_repo.get_teaching_unit_by_id(session, teaching_unit_id) if teaching_unit_id else None

    node_contexts: list[NodeExamContext] = []
    for node_id in unique_node_ids[:6]:
        node, summary, body = _resolve_node_content(session, node_id)
        if node is None:
            continue
        node_contexts.append(
            NodeExamContext(
                node_id=node_id,
                node_name=node.canonical_name,
                summary=summary,
                body=body,
                role="primary",
                coverage_weight=1.0,
            )
        )

    search_terms = [subject]
    if unit is not None:
        search_terms.extend([unit.canonical_name, unit.title])
    search_terms.extend(item.node_name for item in node_contexts)
    doc_excerpt = _extract_doc_excerpt(
        knowledge_doc_text if knowledge_doc_text is not None else read_knowledge_doc_text(subject),
        search_terms,
        max_chars=max_chars // 2,
    )

    parts: list[str] = []
    if unit is not None:
        parts.append(f"Teaching unit: {unit.canonical_name}")
        if unit.summary:
            parts.append("Unit summary:\n" + truncate_text(unit.summary, max_chars=260))
        if unit.body_markdown:
            parts.append("Unit body:\n" + truncate_text(unit.body_markdown, max_chars=360))

    if node_contexts:
        node_lines = [
            f"- {item.node_name}: {truncate_text(item.content, max_chars=260)}"
            for item in node_contexts
            if item.content.strip()
        ]
        if node_lines:
            parts.append("Knowledge anchors:\n" + "\n".join(node_lines))

    if doc_excerpt:
        parts.append("Knowledge document excerpt:\n" + truncate_text(doc_excerpt, max_chars=max_chars // 2))

    return truncate_text("\n\n".join(part for part in parts if part.strip()), max_chars=max_chars)


__all__ = [
    "ExamStyleProfile",
    "NodeExamContext",
    "TemplateSelectionHints",
    "UnitExamContext",
    "build_template_context_signature",
    "build_exam_style_profile",
    "build_grading_knowledge_context",
    "build_unit_exam_contexts",
    "has_explicit_exam_context",
    "load_template_selection_hints",
    "normalize_difficulty_focus",
    "read_knowledge_doc_text",
    "summarize_hint_text",
    "template_matches_request_context",
    "truncate_text",
]
