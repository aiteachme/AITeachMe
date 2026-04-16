"""Shared semantic title normalization helpers for digest lanes."""

from __future__ import annotations

import re

from app.utils.knowledge_helpers import normalize_name

_SPACE_RE = re.compile(r"\s+")
_HEADER_PATH_SPLIT_RE = re.compile(r"\s*>\s*")
_QUESTION_RANGE_SUFFIX_RE = re.compile(
    r"\s*/\s*(?:question|questions)\s+\d+(?:-\d+)?$",
    re.IGNORECASE,
)
_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:[0-9]+(?:\.[0-9]+){0,2}|[ivxlcdm]+)[.)\s:-]+",
    re.IGNORECASE,
)
_QUESTION_TITLE_RE = re.compile(
    r"^(?:question\s*\d+|questions?\s*\d+(?:-\d+)?|q\s*\d+|\d+\s*[.)])",
    re.IGNORECASE,
)
_PROCEDURAL_HINTS = (
    "exam",
    "paper",
    "answer",
    "notice",
    "instruction",
    "rule",
    "score",
    "candidate",
    "page ocr",
    "page",
    "ocr",
    "preamble",
    "fallback",
)
_GENERIC_TITLES = {
    "",
    "(root)",
    "page ocr",
    "page",
    "ocr",
    "preamble",
    "question bank",
    "question",
}
_PUNCT_ONLY_RE = re.compile(r"^[\W_]+$")

DEFAULT_QUESTION_TOPIC = "Typical Questions and Applications"
DEFAULT_STUDY_TOPIC = "Core Knowledge Overview"


def normalize_semantic_whitespace(text: str) -> str:
    """Normalize lightweight markdown-like formatting and whitespace."""

    cleaned = text.strip().strip("-").strip(":;").strip()
    cleaned = re.sub(r"[#*_`>]+", " ", cleaned)
    return _SPACE_RE.sub(" ", cleaned).strip()


def strip_question_range_suffix(title: str) -> str:
    """Remove split question-range suffixes from chunk titles."""

    return _QUESTION_RANGE_SUFFIX_RE.sub("", title).strip()


def strip_outline_number_prefix(title: str) -> str:
    """Remove chapter numbering prefixes from semantic headings."""

    cleaned = normalize_semantic_whitespace(title)
    return _SPACE_RE.sub(" ", _NUMBER_PREFIX_RE.sub("", cleaned)).strip()


def is_question_like_title(title: str) -> bool:
    """Return whether the title mainly acts as a question enumerator."""

    cleaned = normalize_semantic_whitespace(title)
    return bool(cleaned and _QUESTION_TITLE_RE.match(cleaned))


def is_procedural_title(title: str) -> bool:
    """Return whether the title is likely procedural boilerplate."""

    lowered = normalize_semantic_whitespace(title).lower()
    if not lowered:
        return True
    return any(hint in lowered for hint in _PROCEDURAL_HINTS)


def is_generic_semantic_title(title: str) -> bool:
    """Return whether the title is too generic to serve as a semantic topic."""

    cleaned = strip_outline_number_prefix(strip_question_range_suffix(title))
    lowered = cleaned.lower()
    if not lowered or lowered in _GENERIC_TITLES:
        return True
    if len(cleaned) < 2 or _PUNCT_ONLY_RE.match(cleaned) is not None:
        return True
    if is_procedural_title(cleaned):
        return True
    return is_question_like_title(cleaned)


def clean_semantic_title(title: str) -> str:
    """Normalize one title and drop obviously non-semantic wrappers."""

    cleaned = normalize_semantic_whitespace(title)
    cleaned = strip_question_range_suffix(cleaned)
    cleaned = strip_outline_number_prefix(cleaned)
    if is_generic_semantic_title(cleaned):
        return ""
    return cleaned[:80]


def extract_semantic_path_segments(
    header_path: str,
    *,
    fallback_title: str = "",
) -> list[str]:
    """Extract cleaned semantic segments from a header path/title pair."""

    raw_path = header_path or fallback_title
    raw_segments = [
        segment
        for segment in _HEADER_PATH_SPLIT_RE.split(raw_path)
        if normalize_semantic_whitespace(segment)
    ]
    if not raw_segments and fallback_title:
        raw_segments = [fallback_title]

    cleaned_segments: list[str] = []
    seen: set[str] = set()
    for raw in raw_segments:
        cleaned = clean_semantic_title(raw)
        if not cleaned:
            continue
        normalized = normalize_name(cleaned)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        cleaned_segments.append(cleaned)
    return cleaned_segments


def _extract_subject_label(subject_context: str | None) -> str:
    if not subject_context:
        return ""
    prefixes = ("subject:", "domain:", "\u5b66\u79d1\uff1a", "\u9886\u57df\uff1a")
    for line in subject_context.splitlines():
        normalized = normalize_semantic_whitespace(line)
        if not normalized:
            continue
        lowered = normalized.lower()
        for prefix in prefixes:
            if lowered.startswith(prefix.lower()):
                return normalized[len(prefix) :].split(">")[0].strip()[:20]
    return ""


def choose_semantic_topic_path(
    *,
    header_path: str,
    fallback_title: str,
    chapter_topic_hints: list[str] | None = None,
    extracted_terms: list[str] | None = None,
    subject_context: str | None = None,
    question_mode: bool = False,
) -> list[str]:
    """Choose a usable semantic topic path for docs/knowledge graph fallbacks."""

    segments = extract_semantic_path_segments(
        header_path,
        fallback_title=fallback_title,
    )
    if segments:
        return segments

    hint_segments = [clean_semantic_title(hint) for hint in chapter_topic_hints or []]
    hint_segments = [hint for hint in hint_segments if hint]
    if hint_segments:
        return [hint_segments[0]]

    cleaned_terms = [clean_semantic_title(term) for term in extracted_terms or []]
    cleaned_terms = [term for term in cleaned_terms if term]
    if cleaned_terms:
        return [cleaned_terms[0]]

    subject_label = _extract_subject_label(subject_context)
    if question_mode:
        return [DEFAULT_QUESTION_TOPIC if not subject_label else f"{subject_label}{DEFAULT_QUESTION_TOPIC}"]
    if subject_label:
        return [f"{subject_label}{DEFAULT_STUDY_TOPIC}"]
    return [DEFAULT_STUDY_TOPIC]


__all__ = [
    "DEFAULT_QUESTION_TOPIC",
    "DEFAULT_STUDY_TOPIC",
    "choose_semantic_topic_path",
    "clean_semantic_title",
    "extract_semantic_path_segments",
    "is_generic_semantic_title",
    "is_procedural_title",
    "is_question_like_title",
    "normalize_semantic_whitespace",
    "strip_outline_number_prefix",
    "strip_question_range_suffix",
]
