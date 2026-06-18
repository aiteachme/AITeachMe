"""Student-facing textbook style policies for DocGen.

The writer/review pipeline may reason in terms of review, recap, coverage,
or repair. Those words are useful internally, but they should not leak into
the final Markdown as section titles. This module only cleans structural
noise; it must not invent semantic section titles that should have been
chosen by the model from chapter content.
"""

from __future__ import annotations

from collections.abc import Iterable
import re


_HEADING_LINE_RE = re.compile(r"^(?P<prefix>#{1,6})\s+(?P<title>.+?)\s*$")
_BOLD_LABEL_LINE_RE = re.compile(r"^\s*\*\*(?P<title>[^*\n]{1,30})\*\*\s*$")
_BLOCKQUOTE_LINE_RE = re.compile(r"^\s*>\s?(?P<body>.*)$")
_CALLOUT_MARKER_RE = re.compile(
    r"^\s*\[!(?P<kind>NOTE|TIP|IMPORTANT|WARNING|CAUTION|EXAMPLE|PRACTICE|QUESTION)\]",
    re.IGNORECASE,
)
_MARKDOWN_DECORATION_RE = re.compile(r"[#*_`>{}\[\]()]")
_INLINE_MATH_RE = re.compile(r"\$[^$\n]+\$")
_KU_ANCHOR_RE = re.compile(r"\{#ku_[\w-]+\}|<!--\s*ATM_KU:\s*ku_[\w-]+\s*-->")
_TAG_RE = re.compile(r"\[(?:type|prerequisite|related):[^\]]+\]", re.IGNORECASE)
_HEADING_NUMBER_TOKEN_RE = r"(?:\d+(?:\.\d+)*|[一二三四五六七八九十百千万]+|[ivxlcdm]+)"
_HEADING_CHAPTER_PREFIX_RE = re.compile(
    rf"^\s*第\s*{_HEADING_NUMBER_TOKEN_RE}\s*[章节讲节篇部分]\s*[.)）．、:：\s]*",
    re.IGNORECASE,
)
_HEADING_OUTLINE_PREFIX_RE = re.compile(
    rf"^\s*(?:[（(]\s*{_HEADING_NUMBER_TOKEN_RE}\s*[)）]\s*[.)）．、:：\s]*|"
    rf"{_HEADING_NUMBER_TOKEN_RE}(?:\s*[.)）．、:：]\s*|\s+))",
    re.IGNORECASE,
)

_FOCUS_ACTION_CLAUSE_RE = re.compile(
    r"[，,]\s*(?:先|再|并|同时|然后|从而|因此|以便|便于|通过|围绕|"
    r"学会|明确|减少|进入|形成|覆盖|整理|把|用|帮助|让|能够).*$"
)
_TRAILING_ACTION_CONNECTOR_RE = re.compile(
    r"(?:[，,、\s]+(?:先|再|并|同时|然后|从而|因此|以便|便于|通过|围绕|把|用))+$"
)
_MALFORMED_HEADING_CONNECTOR_RE = re.compile(
    r"[，,]\s*(?:先|再|并|同时|然后|从而|因此|以便|便于|通过|围绕|把|用)\s*的"
)

_CALLOUT_EMOJI_KIND = {
    "💡": "TIP",
    "📌": "TIP",
    "🎯": "TIP",
    "🔍": "TIP",
    "🧩": "TIP",
    "🚀": "TIP",
    "✨": "TIP",
    "✅": "IMPORTANT",
    "🔥": "IMPORTANT",
    "⭐": "IMPORTANT",
    "⚠": "WARNING",
    "❗": "WARNING",
    "❌": "WARNING",
    "⛔": "WARNING",
    "🚫": "WARNING",
    "📝": "NOTE",
    "🔗": "NOTE",
    "📚": "NOTE",
}
_CALLOUT_LEADING_ICON_RE = re.compile(
    r"^\s*(?:(?:💡|📌|🎯|🔍|🧩|🚀|✨|✅|🔥|⭐|⚠️?|❗|❌|⛔|🚫|📝|🔗|📚)\s*)+"
)
_ANSWER_FIELD_LABEL_RE = re.compile(
    r"^(?:\*\*)?\s*(?:参考|标准|正确)?答案(?:\s*[/／]\s*结论)?\s*(?:\*\*)?\s*[:：]"
)
_LONG_CALLOUT_VISIBLE_CHAR_LIMIT = 260
_PLAIN_CALLOUT_TITLES = {
    "NOTE": "补充",
    "TIP": "提示",
    "IMPORTANT": "重点",
    "WARNING": "易错提醒",
    "CAUTION": "注意",
    "EXAMPLE": "例题",
    "PRACTICE": "练习",
    "QUESTION": "题目",
}
_GENERIC_VISIBLE_FOCUS_TITLES = {
    "未命名章节",
    "未命名",
    "本章",
    "本章内容",
    "当前章节",
    "Untitled Chapter",
}
_GENERIC_TEXTBOOK_HEADING_LABELS = {
    "学习目标": "本章目标",
    "目标": "本章目标",
    "核心概念": "知识点速览",
    "知识点": "知识点速览",
    "学习目标与核心概念": "本章目标与知识点",
    "核心概念与学习目标": "本章目标与知识点",
    "典型例题": "例题",
    "典型例题回顾": "例题回顾",
    "典型方法与例题": "方法与例题",
    "典型题的完整思路": "典型题思路",
    "典型题型与解题主线": "题型主线",
    "例题": "例题",
    "课后练习": "练习",
    "章末练习": "练习",
    "章末测试": "练习",
    "课后练习与自测": "练习",
    "章末练习与自测": "练习",
    "练习": "练习",
    "学习大纲": "学习大纲",
    "快速检查这章是否学会了": "自查",
    "常见错因与修正方法": "错因修正",
    "典型误区清单": "易错点",
    "阶段测验": "练习",
    "章节练习": "练习",
    "章末短练习": "练习",
    "相邻内容合": "前后联系",
    "易错点整理": "易错点",
    "核心概念与复习主线": "知识主线",
    "本章高频规则清单": "高频规则",
    "高频规则清单": "高频规则",
    "本章小结": "小结",
    "章末小结": "小结",
    "小结": "小结",
    "常见任务": "常见任务",
    "易错点": "易错点",
    "易错提醒": "易错点",
    "最容易错在哪里": "易错点",
}
_GENERIC_TEXTBOOK_HEADING_PREFIX_RE = re.compile(
    r"^\s*(?P<label>学习目标与核心概念|核心概念与学习目标|学习目标|目标|核心概念|知识点|"
    r"典型例题回顾|典型例题|典型方法与例题|典型题的完整思路|典型题型与解题主线|"
    r"例题|课后练习与自测|章末练习与自测|课后练习|章末练习|章末测试|练习|学习大纲|"
    r"快速检查这章是否学会了|常见错因与修正方法|易错点整理|核心概念与复习主线|"
    r"典型误区清单|阶段测验|章节练习|章末短练习|相邻内容合|"
    r"本章高频规则清单|高频规则清单|本章小结|章末小结|小结|常见任务|易错点|易错提醒|"
    r"最容易错在哪里)\s*[:：]\s*(?P<rest>.+)$"
)


def clean_heading_focus(value: str, *, max_chars: int = 18) -> str:
    """Return a compact content phrase suitable for a visible heading."""

    text = str(value or "")
    text = _KU_ANCHOR_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = strip_heading_number_prefix(text)
    text = re.sub(r"^[\s\-*]*(?:目标|要求|覆盖点|知识点)\s*[:：]\s*", "", text)
    text = re.sub(r"[：:；;。！？!?].*$", "", text)
    text = _FOCUS_ACTION_CLAUSE_RE.sub("", text)
    protected_math: list[str] = []

    def protect_math(match: re.Match[str]) -> str:
        protected_math.append(match.group(0))
        return f" ATMMATH{len(protected_math) - 1}TOKEN "

    text = _INLINE_MATH_RE.sub(protect_math, text)
    text = _MARKDOWN_DECORATION_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" ：:，,。；;|-")
    for index, formula in enumerate(protected_math):
        text = text.replace(f"ATMMATH{index}TOKEN", formula)
    text = re.sub(r"\s+", " ", text).strip(" ：:，,。；;|-")
    text = re.sub(r"([，,：:；;。！？!?])\s+(\$)", r"\1\2", text)
    text = _TRAILING_ACTION_CONNECTOR_RE.sub("", text).strip(" ：:，,。；;|-")
    if not text:
        return ""
    if len(text) > max_chars:
        candidate = text[:max_chars].rstrip(" ：:，,。；;|-")
        next_char = text[max_chars : max_chars + 1]
        if next_char and re.match(r"[\w\u4e00-\u9fff]", next_char):
            last_delimiter = max(candidate.rfind("、"), candidate.rfind("，"), candidate.rfind(","))
            if last_delimiter >= max_chars - 6:
                candidate = candidate[:last_delimiter]
        text = _TRAILING_ACTION_CONNECTOR_RE.sub("", candidate).strip(" ：:，,。；;|-")
    return text


def _looks_like_generic_visible_focus(value: str) -> bool:
    cleaned = clean_heading_focus(value, max_chars=80)
    if not cleaned:
        return False
    if cleaned in _GENERIC_VISIBLE_FOCUS_TITLES:
        return True
    return bool(re.fullmatch(r"第\s*[\d一二三四五六七八九十百千万]+\s*章", cleaned))


def _strip_generic_visible_heading_prefix(value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        return ""
    for generic in sorted(_GENERIC_VISIBLE_FOCUS_TITLES, key=len, reverse=True):
        for connector in ("的", "：", ":", " "):
            prefix = f"{generic}{connector}"
            if cleaned.startswith(prefix):
                return cleaned[len(prefix):].strip(" ：:，,。；;|-")
    match = re.match(r"^第\s*[\d一二三四五六七八九十百千万]+\s*章\s*的?\s*(.+)$", cleaned)
    if match is not None:
        return match.group(1).strip(" ：:，,。；;|-")
    return cleaned


def _demote_generic_textbook_heading(value: str) -> str:
    cleaned = re.sub(r"\s+", "", str(value or "").strip(" ：:，,。；;|-"))
    return _GENERIC_TEXTBOOK_HEADING_LABELS.get(cleaned, "")


def strip_heading_number_prefix(value: str) -> str:
    """Remove display numbering from the beginning of a visible heading title."""

    cleaned = str(value or "").strip()
    for _ in range(3):
        next_cleaned = _HEADING_CHAPTER_PREFIX_RE.sub("", cleaned, count=1)
        next_cleaned = _HEADING_OUTLINE_PREFIX_RE.sub("", next_cleaned, count=1).strip()
        if next_cleaned == cleaned:
            break
        cleaned = next_cleaned
    return cleaned.strip()


def _numberless_fallback_title(fallback_title: str, *, default: str) -> str:
    cleaned = strip_heading_number_prefix(fallback_title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip("：:，,。；; ")
    if _looks_like_generic_visible_focus(cleaned):
        return default
    return cleaned or default


def _repair_malformed_textbook_heading_title(value: str, *, fallback_title: str = "") -> str:
    title = str(value or "").strip()
    if not title:
        return ""
    title = _MALFORMED_HEADING_CONNECTOR_RE.sub("的", title)
    title = _TRAILING_ACTION_CONNECTOR_RE.sub("", title).strip(" ：:，,。；;|-")
    if "方向导的" in title and "方向导数" in str(fallback_title or ""):
        title = title.replace("方向导的", "方向导数的")
    return title


def rewrite_textbook_heading_line(
    line: str,
    *,
    digest_mode: str,
    fallback_title: str = "",
    focus_items: Iterable[str] = (),
) -> str:
    """Rewrite one Markdown heading line if it leaks internal wording."""

    match = _HEADING_LINE_RE.match(str(line or "").strip())
    if match is None:
        return line
    raw_title = match.group("title").strip()
    numberless_title = _repair_malformed_textbook_heading_title(
        strip_heading_number_prefix(raw_title),
        fallback_title=fallback_title,
    )
    level = match.group("prefix").count("#")
    if level == 1:
        if numberless_title and numberless_title != raw_title:
            return f"{match.group('prefix')} {numberless_title}"
        if not numberless_title and fallback_title:
            fallback = _numberless_fallback_title(fallback_title, default="")
            return f"{match.group('prefix')} {fallback}" if fallback else line
        return line

    demoted = _demote_generic_textbook_heading(numberless_title)
    if demoted:
        return f"**{demoted}**"

    prefix_match = _GENERIC_TEXTBOOK_HEADING_PREFIX_RE.match(numberless_title)
    if prefix_match is not None:
        rest = clean_heading_focus(prefix_match.group("rest"), max_chars=36)
        if rest:
            return f"{match.group('prefix')} {rest}"
        label = _GENERIC_TEXTBOOK_HEADING_LABELS.get(prefix_match.group("label"), "")
        return f"**{label}**" if label else ""

    heading_title = _strip_generic_visible_heading_prefix(clean_heading_focus(numberless_title, max_chars=80))
    if not heading_title:
        return "" if numberless_title != raw_title else line
    if heading_title and heading_title != numberless_title:
        return f"{match.group('prefix')} {heading_title}"
    if numberless_title and numberless_title != raw_title:
        return f"{match.group('prefix')} {numberless_title}"
    return line


def _drop_repeated_visible_heading_line(line: str, seen_titles: set[str]) -> str:
    match = _HEADING_LINE_RE.match(str(line or "").strip())
    if match is None:
        return line
    if match.group("prefix").count("#") <= 1:
        return line
    title = strip_heading_number_prefix(match.group("title").strip())
    title = re.sub(r"\s+", "", title).casefold()
    if not title:
        return line
    if title in seen_titles:
        return ""
    seen_titles.add(title)
    return line


def _bold_label_key(line: str) -> str:
    match = _BOLD_LABEL_LINE_RE.match(str(line or "").strip())
    if match is None:
        return ""
    return re.sub(r"\s+", "", match.group("title")).casefold()


def _clamp_heading_level_jump(line: str, *, previous_level: int | None) -> str:
    match = _HEADING_LINE_RE.match(str(line or "").strip())
    if match is None or previous_level is None:
        return line
    level = match.group("prefix").count("#")
    if level <= previous_level + 1:
        return line
    return f"{'#' * (previous_level + 1)} {match.group('title').strip()}"


def normalize_textbook_headings(
    markdown: str,
    *,
    digest_mode: str,
    fallback_title: str = "",
    focus_items: Iterable[str] = (),
) -> str:
    """Normalize all visible Markdown headings to the textbook style policy."""

    lines: list[str] = []
    in_code_fence = False
    seen_visible_headings: set[str] = set()
    previous_heading_level: int | None = None
    last_standalone_label_key = ""
    for line in str(markdown or "").splitlines():
        if line.lstrip().startswith("```"):
            in_code_fence = not in_code_fence
            lines.append(line)
            last_standalone_label_key = ""
            continue
        if in_code_fence:
            lines.append(line)
            continue
        rewritten = rewrite_textbook_heading_line(
            line,
            digest_mode=digest_mode,
            fallback_title=fallback_title,
            focus_items=focus_items,
        )
        match_before_dedupe = _HEADING_LINE_RE.match(str(rewritten or "").strip())
        if match_before_dedupe is not None and match_before_dedupe.group("prefix").count("#") == 1:
            seen_visible_headings.clear()
        rewritten = _drop_repeated_visible_heading_line(rewritten, seen_visible_headings)
        rewritten = _clamp_heading_level_jump(rewritten, previous_level=previous_heading_level)
        match = _HEADING_LINE_RE.match(str(rewritten or "").strip())
        if match is not None:
            previous_heading_level = match.group("prefix").count("#")
        label_key = _bold_label_key(rewritten)
        if label_key:
            if label_key == last_standalone_label_key:
                rewritten = ""
            else:
                last_standalone_label_key = label_key
        elif str(rewritten or "").strip():
            last_standalone_label_key = ""
        lines.append(rewritten)
    return "\n".join(lines)


def _infer_callout_kind(body_lines: Iterable[str]) -> str:
    first_line = next((str(item or "").strip() for item in body_lines if str(item or "").strip()), "")
    if not first_line:
        return ""
    answer_candidate = _CALLOUT_LEADING_ICON_RE.sub("", first_line, count=1).lstrip()
    if _ANSWER_FIELD_LABEL_RE.match(answer_candidate):
        return ""
    first_char = first_line[0]
    if first_char in _CALLOUT_EMOJI_KIND and re.search(r"(?:\*\*|[:：])", first_line):
        return _CALLOUT_EMOJI_KIND[first_char]
    return ""


def _strip_callout_leading_icons(line: str) -> str:
    return _CALLOUT_LEADING_ICON_RE.sub("", str(line or ""), count=1).lstrip()


def _strip_first_callout_body_icon(body_lines: list[str]) -> list[str]:
    normalized = list(body_lines)
    for index, line in enumerate(normalized):
        stripped = line.strip()
        if not stripped or _CALLOUT_MARKER_RE.match(stripped):
            continue
        normalized[index] = _strip_callout_leading_icons(line)
        break
    return normalized


def _callout_content_lines(body_lines: list[str]) -> list[str]:
    content: list[str] = []
    marker_skipped = False
    for line in body_lines:
        if not marker_skipped and _CALLOUT_MARKER_RE.match(line.strip()):
            marker_skipped = True
            continue
        content.append(line.rstrip())
    while content and not content[0].strip():
        content.pop(0)
    while content and not content[-1].strip():
        content.pop()
    return _strip_first_callout_body_icon(content)


def _visible_callout_char_count(content_lines: Iterable[str]) -> int:
    visible = " ".join(str(line or "").strip() for line in content_lines if str(line or "").strip())
    visible = _MARKDOWN_DECORATION_RE.sub("", visible)
    return len(re.sub(r"\s+", "", visible))


def _should_flatten_callout(kind: str, content_lines: list[str]) -> bool:
    normalized_kind = kind.strip().upper()
    if normalized_kind == "QUESTION":
        return False
    return normalized_kind in {"EXAMPLE", "PRACTICE"} or (
        _visible_callout_char_count(content_lines) > _LONG_CALLOUT_VISIBLE_CHAR_LIMIT
    )


def _flatten_callout(kind: str, content_lines: list[str]) -> list[str]:
    title = _PLAIN_CALLOUT_TITLES.get(kind.strip().upper(), "提示")
    if not content_lines:
        return [f"**{title}**"]
    return [f"**{title}**", "", *content_lines]


def _normalize_blockquote_callout(block_lines: list[str]) -> list[str]:
    body_lines: list[str] = []
    for line in block_lines:
        match = _BLOCKQUOTE_LINE_RE.match(line)
        if match is None:
            return block_lines
        body_lines.append(str(match.group("body") or "").rstrip())

    first_nonempty = next((line.strip() for line in body_lines if line.strip()), "")
    if not first_nonempty:
        return block_lines
    marker_match = _CALLOUT_MARKER_RE.match(first_nonempty)
    if marker_match is not None:
        kind = marker_match.group("kind").upper()
        content_lines = _callout_content_lines(body_lines)
        if _should_flatten_callout(kind, content_lines):
            return _flatten_callout(kind, content_lines)
        stripped_body = _strip_first_callout_body_icon(body_lines)
        if stripped_body == body_lines:
            return block_lines
        return [f"> {line}" if line.strip() else ">" for line in stripped_body]

    kind = _infer_callout_kind(body_lines)
    if not kind:
        return block_lines

    body_lines = _strip_first_callout_body_icon(body_lines)
    if _should_flatten_callout(kind, body_lines):
        return _flatten_callout(kind, body_lines)
    normalized = [f"> [!{kind}]", ">"]
    normalized.extend(f"> {line}" if line.strip() else ">" for line in body_lines)
    return normalized


def normalize_educational_callouts(markdown: str) -> str:
    """Promote legacy emoji blockquotes into GitHub-style teaching callouts.

    Writer models may produce learner-facing blockquotes with an explicit
    leading icon instead of a GitHub-style marker. The frontend only renders
    first-class callouts for ``> [!TIP]`` / ``> [!WARNING]`` markers, so this
    deterministic pass uses the icon as a presentational signal and removes it
    from the visible body.
    """

    text = str(markdown or "")
    if ">" not in text:
        return text

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output: list[str] = []
    in_fence = False
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            output.append(line)
            index += 1
            continue

        if in_fence or _BLOCKQUOTE_LINE_RE.match(line) is None:
            output.append(line)
            index += 1
            continue

        block: list[str] = []
        while index < len(lines) and _BLOCKQUOTE_LINE_RE.match(lines[index]) is not None:
            block.append(lines[index])
            index += 1
        output.extend(_normalize_blockquote_callout(block))

    return "\n".join(output)


__all__ = [
    "clean_heading_focus",
    "normalize_educational_callouts",
    "normalize_textbook_headings",
    "rewrite_textbook_heading_line",
    "strip_heading_number_prefix",
]
