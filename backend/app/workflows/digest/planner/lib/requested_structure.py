"""Extract explicit planner structure from the user's request."""

from __future__ import annotations

import re
from typing import Any


_CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_NUMBER_TOKEN = r"\d{1,2}|[一二两三四五六七八九十]{1,4}"
_CHAPTER_UNIT = r"(?:个\s*)?(?:章节|章)"
_EXPLICIT_CHAPTER_COUNT_RE = re.compile(
    rf"(?P<count>{_NUMBER_TOKEN})\s*{_CHAPTER_UNIT}(?:\s*(?:课程|课|大纲|方案|内容))?"
)
_ORDINAL_CHAPTER_RE = re.compile(
    rf"第\s*(?P<number>{_NUMBER_TOKEN})\s*章\s*(?P<title>.*?)(?=(?:[，,；;。.!！?？]\s*)?第\s*{_NUMBER_TOKEN}\s*章|[。.!！?？\n]|$)",
    re.S,
)
_INLINE_CHAPTER_LIST_RE = re.compile(
    rf"(?:按|按照)\s*(?P<items>[^。.!！?？\n]{{3,180}}?)\s*"
    rf"(?:分成|分为|划分为|划分成|拆成|拆为)\s*"
    rf"(?:(?P<count>{_NUMBER_TOKEN})\s*)?{_CHAPTER_UNIT}",
    re.S,
)
_INLINE_TITLE_SPLIT_RE = re.compile(r"\s*(?:、|，|,|；|;)\s*")
_TITLE_TAIL_RE = re.compile(
    r"(?:，|,|；|;)\s*(?:每章|每个章节|并且|同时|要求|需要|要有|包含|适合|用于|请).*$",
    re.S,
)
_TOPIC_PATTERNS = (
    re.compile(
        r"(?:我想|我要|希望|计划|准备|请帮我|帮我|给我)?\s*"
        r"(?:系统地?|重新|重点)?\s*"
        r"(?:学习|复习|掌握|梳理)\s*"
        r"(?P<topic>[^，,。；;：:\n]{2,40})"
    ),
    re.compile(
        r"(?:我想|我要|希望|计划|准备|请帮我|帮我|给我)\s*把\s*"
        r"(?P<topic>[^，,。；;：:\n]{2,40})"
        r"(?:整理|构建|做成|变成)"
    ),
)
_TOPIC_TAIL_RE = re.compile(r"(?:\s*(?:请|并|按|拆成|生成|构建|做成|包含|每章|适合).*)$")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _parse_small_number(value: str) -> int | None:
    token = str(value or "").strip()
    if not token:
        return None
    if token.isdigit():
        parsed = int(token)
        return parsed if 1 <= parsed <= 30 else None
    if "十" not in token:
        if len(token) == 1 and token in _CHINESE_DIGITS:
            return _CHINESE_DIGITS[token]
        return None
    left, _, right = token.partition("十")
    tens = _CHINESE_DIGITS.get(left, 1) if left else 1
    ones = _CHINESE_DIGITS.get(right, 0) if right else 0
    parsed = tens * 10 + ones
    return parsed if 1 <= parsed <= 30 else None


def _clean_heading(value: str) -> str:
    text = _text(value)
    text = _TITLE_TAIL_RE.sub("", text)
    text = text.strip().strip("\"'“”‘’`，,。；;:：.．、-— ")
    text = re.sub(r"^\s*(?:[-*•]|\d+[.)、])\s*", "", text)
    return text[:40].rstrip("，,。；;:：.．、 ")


def extract_explicit_learning_topic(value: Any) -> str:
    """Return a directly stated learning object such as ``初中函数``."""

    text = _text(value)
    if not text:
        return ""
    for pattern in _TOPIC_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        topic = _TOPIC_TAIL_RE.sub("", _text(match.group("topic")))
        topic = topic.strip().strip("\"'“”‘’`，,。；;:：.．、 ")
        if 2 <= len(topic) <= 16:
            return topic
    return ""


def extract_explicit_chapter_titles(value: Any) -> list[str]:
    """Return titles from requests like ``第 1 章 A，第 2 章 B``."""

    text = str(value or "").strip()
    if not text:
        return []
    result: list[str] = []
    seen: set[str] = set()

    def add_title(raw: str) -> None:
        title = _clean_heading(raw)
        key = title.casefold()
        if not title or key in seen:
            return
        seen.add(key)
        result.append(title)

    for match in _ORDINAL_CHAPTER_RE.finditer(text):
        add_title(match.group("title"))
    if result:
        return result

    for match in _INLINE_CHAPTER_LIST_RE.finditer(text):
        raw_items = _clean_heading(match.group("items"))
        titles = [
            _clean_heading(part)
            for part in _INLINE_TITLE_SPLIT_RE.split(raw_items)
            if _clean_heading(part)
        ]
        count = _parse_small_number(match.group("count") or "")
        if count is not None and len(titles) != count:
            continue
        if len(titles) < 2:
            continue
        for title in titles:
            add_title(title)
        if result:
            return result
    return result


def extract_requested_chapter_count(value: Any) -> int | None:
    """Return an exact chapter count stated by the user."""

    text = str(value or "")
    if not text.strip():
        return None
    titles = extract_explicit_chapter_titles(text)
    if titles:
        return len(titles)
    for match in _EXPLICIT_CHAPTER_COUNT_RE.finditer(text):
        prefix = text[max(0, match.start() - 4) : match.start()]
        if "第" in prefix:
            continue
        parsed = _parse_small_number(match.group("count"))
        if parsed is not None:
            return parsed
    return None


__all__ = [
    "extract_explicit_chapter_titles",
    "extract_explicit_learning_topic",
    "extract_requested_chapter_count",
]
