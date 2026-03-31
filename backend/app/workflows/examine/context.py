"""Shared context builders for the examine workflow."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field

from sqlmodel import Session

from app.models import IngestStatus, KnowledgeNode, RawFile, TaskStatus, TeachingUnit
from app.repositories import profile_repo
from app.repositories.files_repo import list_raw_files_by_uids
from app.repositories.knowledge import curriculum_repo, kg_repo
from app.utils.path_helpers import (
    build_merged_knowledge_base_build_path,
    build_merged_knowledge_base_path,
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
            "style_prompt": self.style_prompt,
            "focus_prompt": self.focus_prompt,
            "user_prompt": self.user_prompt,
            "notes": list(self.notes),
        }


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


def _read_knowledge_doc_text(subject: str) -> str:
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
    sample_file_uids: list[str] | None = None,
    style_prompt: str | None = None,
    focus_prompt: str | None = None,
    user_prompt: str | None = None,
    exam_mode: str = "diagnostic",
) -> ExamStyleProfile:
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

    question_type_bias = _detect_question_type_bias(sample_markdown)
    preferred_question_types = list(question_type_bias.keys())
    if not preferred_question_types and exam_mode == "real_exam":
        preferred_question_types = ["single_choice", "fill_blank", "short_answer"]

    notes: list[str] = []
    if ready_samples:
        notes.append(f"Sample-paper references loaded: {len(ready_samples)}")
    elif sample_file_uids:
        notes.append("Sample-paper files were provided but no parsed markdown is ready yet.")
    if re.search(r"(A[\.、\)]|B[\.、\)]|C[\.、\)]|D[\.、\)])", sample_markdown):
        notes.append("Choice questions should use labeled options.")
    if exam_mode == "real_exam":
        notes.append("Use section-based paper organization and a formal exam tone.")

    return ExamStyleProfile(
        source_file_uids=[item.uid for item in ready_samples if item.uid],
        title_hint=_guess_paper_title(sample_markdown),
        format_hint="real_exam" if exam_mode == "real_exam" else "standard",
        section_titles=_detect_section_titles(sample_markdown),
        preferred_question_types=preferred_question_types,
        question_type_bias=question_type_bias,
        recommended_question_count=_detect_question_count(sample_markdown),
        style_prompt=(style_prompt or "").strip() or None,
        focus_prompt=(focus_prompt or "").strip() or None,
        user_prompt=(user_prompt or "").strip() or None,
        notes=notes,
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


def _load_node_contexts_for_unit(
    session: Session,
    *,
    user_id: str,
    subject: str,
    unit: TeachingUnit,
) -> list[NodeExamContext]:
    memberships = curriculum_repo.list_memberships_by_unit(session, unit.id or 0)
    weak_states = {
        state.knowledge_node_id: state
        for state in profile_repo.list_weak_knowledge_states(
            session,
            user_id=user_id,
            subject=subject,
            threshold=0.8,
            target_kind="node",
        )
        if state.knowledge_node_id is not None
    }

    contexts: list[NodeExamContext] = []
    for membership in memberships:
        node, summary, body = _resolve_node_content(session, membership.knowledge_node_id)
        if node is None:
            continue
        mastery_state = profile_repo.get_knowledge_state(
            session,
            user_id=user_id,
            subject=subject,
            knowledge_node_id=membership.knowledge_node_id,
        )
        contexts.append(
            NodeExamContext(
                node_id=membership.knowledge_node_id,
                node_name=node.canonical_name,
                summary=summary,
                body=body,
                role=membership.role,
                coverage_weight=float(membership.score or 1.0),
                mastery_score=(mastery_state.mastery_score if mastery_state is not None else None),
                is_weak=membership.knowledge_node_id in weak_states,
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
    doc_text = _read_knowledge_doc_text(subject)
    style = style_profile or build_exam_style_profile(
        session,
        subject=subject,
        focus_prompt=focus_prompt,
        user_prompt=user_prompt,
        exam_mode=exam_mode,
    )
    recent_mistakes = profile_repo.list_recent_wrong_attempt_summaries(
        session,
        user_id=user_id,
        subject=subject,
        limit=5,
    )

    contexts: list[UnitExamContext] = []
    for raw_unit_id in unit_ids:
        unit = curriculum_repo.get_teaching_unit_by_id(session, int(raw_unit_id))
        if unit is None or unit.id is None:
            continue

        node_contexts = _load_node_contexts_for_unit(
            session,
            user_id=user_id,
            subject=subject,
            unit=unit,
        )
        learning_objectives = [
            str(item).strip()
            for item in _parse_json_list(unit.learning_objectives_json)
            if str(item).strip()
        ]
        unit_state = profile_repo.get_knowledge_state(
            session,
            user_id=user_id,
            subject=subject,
            teaching_unit_id=unit.id,
        )
        search_terms = [unit.canonical_name, unit.title] + [item.node_name for item in node_contexts]
        doc_excerpt = _extract_doc_excerpt(doc_text, search_terms)
        weak_node_names = [item.node_name for item in node_contexts if item.is_weak]
        contexts.append(
            UnitExamContext(
                subject=subject,
                unit_id=unit.id,
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
                exam_mode=exam_mode,
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
    doc_excerpt = _extract_doc_excerpt(_read_knowledge_doc_text(subject), search_terms, max_chars=max_chars // 2)

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
    "UnitExamContext",
    "build_exam_style_profile",
    "build_grading_knowledge_context",
    "build_unit_exam_contexts",
    "truncate_text",
]
