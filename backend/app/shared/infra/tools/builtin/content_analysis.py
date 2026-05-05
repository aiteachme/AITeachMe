"""Reusable content-analysis helpers for teaching and doc generation."""

from __future__ import annotations

import re
from collections.abc import Iterable

_MULTISPACE_RE = re.compile(r"\s+")
_MARKDOWN_DECORATION_RE = re.compile(r"[#*_`>]+")
_CN_METHOD_RE = re.compile(
    r"([\u4e00-\u9fff]{2,10}(?:法|定理|公式|定律|原理|准则|方程|变换|分解|展开|判别|不等式))"
)
_CN_TERM_RE = re.compile(r"([\u4e00-\u9fff]{2,8}(?:的[\u4e00-\u9fff]{2,6})?)")
_EN_PHRASE_RE = re.compile(r"\b([a-zA-Z][a-zA-Z0-9+-]*(?:\s+[a-zA-Z][a-zA-Z0-9+-]*){0,2})\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?;；])|\n+")
_STOPWORDS = frozenset(
    {
        "核心内容",
        "快速回顾",
        "本章导读",
        "本章要点",
        "题型拆解",
        "易错提醒",
        "知识文档",
        "学习目标",
        "系统课",
        "速成课",
        "important",
        "tip",
        "chapter",
        "knowledge",
        "document",
        "overview",
    }
)


def _normalize_text(text: str) -> str:
    cleaned = _MARKDOWN_DECORATION_RE.sub(" ", str(text or ""))
    return _MULTISPACE_RE.sub(" ", cleaned).strip()


def _dedupe_terms(terms: Iterable[str], *, limit: int | None = None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in terms:
        term = _normalize_text(item)
        if not term:
            continue
        key = term.casefold()
        if key in seen or key in _STOPWORDS:
            continue
        seen.add(key)
        normalized.append(term)
        if limit is not None and len(normalized) >= limit:
            break
    return normalized


def _looks_like_term(candidate: str) -> bool:
    text = _normalize_text(candidate)
    if len(text) < 2 or len(text) > 32:
        return False
    if text.casefold() in _STOPWORDS:
        return False
    if re.fullmatch(r"[0-9.\-+/%]+", text):
        return False
    return True


def extract_key_terms(
    text: str,
    *,
    seed_terms: list[str] | None = None,
    limit: int = 8,
) -> list[str]:
    """Extract reusable concept-like terms from mixed markdown/text."""

    normalized = _normalize_text(text)
    if not normalized:
        return _dedupe_terms(seed_terms or [], limit=limit)

    terms: list[str] = []
    if seed_terms:
        terms.extend(seed_terms)

    for match in _CN_METHOD_RE.finditer(normalized):
        terms.append(match.group(1))

    for match in re.finditer(r"(?:定义|定理|性质|公式|概念|原理)\s*[：:]\s*([\u4e00-\u9fff]{2,10})", normalized):
        terms.append(match.group(1))

    for match in _CN_TERM_RE.finditer(normalized):
        candidate = match.group(1)
        if _looks_like_term(candidate):
            terms.append(candidate)

    for match in _EN_PHRASE_RE.finditer(normalized):
        candidate = match.group(1).strip()
        word_count = len(candidate.split())
        if word_count == 1 and len(candidate) < 5:
            continue
        if _looks_like_term(candidate):
            terms.append(candidate)

    return _dedupe_terms(terms, limit=limit)


def extract_term_excerpts(
    text: str,
    terms: list[str],
    *,
    excerpt_char_limit: int = 96,
) -> dict[str, str]:
    """Locate a short supporting excerpt for each term."""

    normalized = _normalize_text(text)
    if not normalized:
        return {}

    segments = [
        _normalize_text(item)
        for item in _SENTENCE_SPLIT_RE.split(str(text or ""))
        if _normalize_text(item)
    ]
    excerpts: dict[str, str] = {}
    for term in _dedupe_terms(terms):
        lowered = term.casefold()
        for segment in segments:
            if lowered not in segment.casefold():
                continue
            excerpt = segment
            if len(excerpt) > excerpt_char_limit:
                excerpt = excerpt[: excerpt_char_limit - 1].rstrip("，。；：,. ") + "…"
            excerpts[term] = excerpt
            break
    return excerpts


def build_term_coverage(
    text: str,
    required_terms: list[str],
) -> list[dict[str, object]]:
    """Check whether required terms are covered by the given content."""

    haystack = _normalize_text(text).casefold()
    rows: list[dict[str, object]] = []
    for term in _dedupe_terms(required_terms):
        covered = term.casefold() in haystack if haystack else False
        rows.append(
            {
                "term": term,
                "covered": covered,
                "status": "covered" if covered else "missing",
            }
        )
    return rows


def find_missing_terms(text: str, required_terms: list[str]) -> list[str]:
    """Return required terms not yet covered by the text."""

    return [
        str(item["term"])
        for item in build_term_coverage(text, required_terms)
        if not bool(item["covered"])
    ]


__all__ = [
    "build_term_coverage",
    "extract_key_terms",
    "extract_term_excerpts",
    "find_missing_terms",
]
