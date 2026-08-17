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
_NUMBER_TOKEN = r"(?:\d{1,2}|[一二两三四五六七八九十]{1,4})"
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
_NEGATIVE_ORDINAL_PREFIX_RE = re.compile(
    r"(?:不(?:得|要|可|应)?|勿|别|禁止|避免)(?:再|继续)?"
    r"(?:增加|添加|生成|扩展|拆分|安排|设置|写入|写|有)?\s*$"
)
_EXPLICIT_COURSE_TITLE_RE = re.compile(
    r"(?:我想|我要|希望|计划|准备|请帮我|帮我|给我|请)?\s*"
    r"(?:构建|创建|生成|设计|做)\s*(?:一门|一个)?\s*"
    r"(?P<title>[^，,。；;：:\n]{2,40}?)(?:课程|课)"
    r"(?=[，,。；;：:\n]|$)"
)
_TOPIC_PATTERNS = (
    re.compile(
        r"(?:基于|根据)\s*(?:用户)?\s*(?:上传|提供|给出)?\s*的?\s*"
        r"(?P<topic>[^，,。；;：:\n]{2,24}?)\s*(?:资料|材料|教材|课件)"
    ),
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
_GENERIC_TOPICS = {
    "内容",
    "学习内容",
    "学习方案",
    "学习计划",
    "方案",
    "材料",
    "知识",
    "知识点",
    "课程",
    "课程内容",
    "课程方案",
    "资料",
}
_TOPIC_TAIL_RE = re.compile(r"(?:\s*(?:请|并|按|拆成|生成|构建|做成|包含|每章|适合).*)$")
_DIAGNOSIS_FEEDBACK_PREFIXES = (
    "前置诊断选择：",
    "前置诊断选择:",
    "跳过前置诊断，请按当前学习目标和资料继续生成可确认的学习方案。",
)
_CHAPTER_STRUCTURE_TARGET = (
    rf"(?:章节|大纲)(?:的)?(?:结构|顺序|划分|框架)|{_NUMBER_TOKEN}\s*章(?:的)?(?:结构|顺序|划分|框架)"
)
_KNOWLEDGE_BOUNDARY_TARGET = r"(?:知识点边界|知识边界|知识点范围|知识范围|覆盖范围)"
_PRESERVE_PREFIX = r"(?:保持|保留|维持|沿用|原样保留)"
_PRESERVE_SUFFIX = r"(?:保持不变|不变|不调整|不修改|原样保留)"
_PRESERVE_CHAPTER_STRUCTURE_PATTERNS = (
    re.compile(rf"{_PRESERVE_PREFIX}[^。；;\n]{{0,20}}(?:{_CHAPTER_STRUCTURE_TARGET})"),
    re.compile(rf"(?:{_CHAPTER_STRUCTURE_TARGET})[^。；;\n]{{0,10}}{_PRESERVE_SUFFIX}"),
    re.compile(r"不(?:增删|调整|改变|修改)[^。；;\n]{0,8}(?:章节|大纲)"),
)
_PRESERVE_KNOWLEDGE_BOUNDARY_PATTERNS = (
    re.compile(rf"{_PRESERVE_PREFIX}[^。；;\n]{{0,24}}{_KNOWLEDGE_BOUNDARY_TARGET}"),
    re.compile(rf"{_KNOWLEDGE_BOUNDARY_TARGET}[^。；;\n]{{0,10}}{_PRESERVE_SUFFIX}"),
    re.compile(r"不(?:增删|调整|改变|修改)[^。；;\n]{0,8}(?:知识点|覆盖范围)"),
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().split())


def _is_diagnosis_feedback(value: Any) -> bool:
    text = _text(value)
    return any(text.startswith(prefix) for prefix in _DIAGNOSIS_FEEDBACK_PREFIXES)


def resolve_planner_revision_feedback(
    feedback_message: Any,
    message_history: list[str] | None = None,
) -> str:
    """Resolve the revision request that owns structure locks across a diagnosis round."""

    current = _text(feedback_message)
    if not _is_diagnosis_feedback(current):
        return current
    for raw_message in reversed(message_history or []):
        message = str(raw_message or "").strip()
        match = re.match(r"^用户\s*[:：]\s*(?P<content>.*)$", message, re.S)
        if not match:
            continue
        content = _text(match.group("content"))
        if content and not _is_diagnosis_feedback(content):
            return content
    return current


def requests_preserved_chapter_structure(value: Any) -> bool:
    text = _text(value)
    return bool(text and any(pattern.search(text) for pattern in _PRESERVE_CHAPTER_STRUCTURE_PATTERNS))


def requests_preserved_knowledge_boundaries(value: Any) -> bool:
    text = _text(value)
    return bool(text and any(pattern.search(text) for pattern in _PRESERVE_KNOWLEDGE_BOUNDARY_PATTERNS))


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


def extract_explicit_course_title(value: Any) -> str:
    """Return a course title explicitly stated in phrases such as ``构建一门高数复习课``."""

    text = _text(value)
    if not text:
        return ""
    match = _EXPLICIT_COURSE_TITLE_RE.search(text)
    if not match:
        return ""
    title = _clean_heading(match.group("title"))
    if re.fullmatch(rf"{_NUMBER_TOKEN}\s*{_CHAPTER_UNIT}", title):
        return ""
    return title if title not in _GENERIC_TOPICS and 2 <= len(title) <= 16 else ""


def extract_explicit_learning_topic(value: Any) -> str:
    """Return a directly stated learning object such as ``初中函数``."""

    text = _text(value)
    if not text:
        return ""
    explicit_course_title = extract_explicit_course_title(text)
    if explicit_course_title:
        return explicit_course_title

    def normalize_topic(raw_topic: Any) -> str:
        topic = _TOPIC_TAIL_RE.sub("", _text(raw_topic))
        topic = topic.strip().strip("\"'“”‘’`，,。；;:：.．、 ")
        if topic in _GENERIC_TOPICS:
            return ""
        return topic if 2 <= len(topic) <= 16 else ""

    for pattern in _TOPIC_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        topic = normalize_topic(match.group("topic"))
        if topic:
            return topic

    return ""


def extract_explicit_chapter_titles(value: Any) -> list[str]:
    """Return titles from requests like ``第 1 章 A，第 2 章 B``."""

    text = str(value or "").strip()
    if not text:
        return []
    result: list[str] = []
    seen: set[str] = set()
    seen_ordinals: set[int] = set()

    def add_title(raw: str) -> None:
        title = _clean_heading(raw)
        key = title.casefold()
        if not title or key in seen:
            return
        seen.add(key)
        result.append(title)

    for match in _ORDINAL_CHAPTER_RE.finditer(text):
        prefix = text[max(0, match.start() - 12) : match.start()]
        if _NEGATIVE_ORDINAL_PREFIX_RE.search(prefix):
            continue
        ordinal = _parse_small_number(match.group("number"))
        if ordinal is None or ordinal in seen_ordinals:
            continue
        previous_count = len(result)
        add_title(match.group("title"))
        if len(result) > previous_count:
            seen_ordinals.add(ordinal)
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
    explicit_count: int | None = None
    for match in _EXPLICIT_CHAPTER_COUNT_RE.finditer(text):
        prefix = text[max(0, match.start() - 4) : match.start()]
        if "第" in prefix:
            continue
        parsed = _parse_small_number(match.group("count"))
        if parsed is not None:
            explicit_count = parsed
    if explicit_count is not None:
        return explicit_count
    titles = extract_explicit_chapter_titles(text)
    return len(titles) if titles else None


__all__ = [
    "extract_explicit_chapter_titles",
    "extract_explicit_course_title",
    "extract_explicit_learning_topic",
    "extract_requested_chapter_count",
    "requests_preserved_chapter_structure",
    "requests_preserved_knowledge_boundaries",
    "resolve_planner_revision_feedback",
]
