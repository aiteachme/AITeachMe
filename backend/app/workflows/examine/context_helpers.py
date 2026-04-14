"""Small, shared helpers used across examine context modules."""

from __future__ import annotations

import hashlib
import json
import re

from app.models import normalize_exam_mode


def truncate_text(text: str, *, max_chars: int) -> str:
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 3].rstrip() + "..."


def _format_mastery(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value:.2f}"


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


def read_knowledge_doc_text(subject: str) -> str:
    from app.utils.path_helpers import (
        build_merged_knowledge_base_build_path,
        build_merged_knowledge_base_path,
    )

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


__all__ = [
    "_extract_doc_excerpt",
    "_format_mastery",
    "_normalize_int_list",
    "_parse_json_list",
    "_unique_strings",
    "build_template_context_signature",
    "has_explicit_exam_context",
    "normalize_difficulty_focus",
    "read_knowledge_doc_text",
    "summarize_hint_text",
    "truncate_text",
]
