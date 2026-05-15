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
_BLOCKQUOTE_LINE_RE = re.compile(r"^\s*>\s?(?P<body>.*)$")
_CALLOUT_MARKER_RE = re.compile(r"^\s*\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION|EXAMPLE|PRACTICE)\]", re.IGNORECASE)
_MARKDOWN_DECORATION_RE = re.compile(r"[#*_`>{}\[\]()]")
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
    r"(?:[，,、\s]*(?:先|再|并|同时|然后|从而|因此|以便|便于|通过|围绕|把|用))+$"
)
_MALFORMED_HEADING_CONNECTOR_RE = re.compile(
    r"[，,]\s*(?:先|再|并|同时|然后|从而|因此|以便|便于|通过|围绕|把|用)\s*的"
)

_CALLOUT_WARNING_START_RE = re.compile(
    r"^\s*(?:⚠️?|❗|❌|⛔|🚫)?\s*(?:\*\*)?"
    r"(?:易错|误区|陷阱|警示|注意|不能|不要|失分|关键区别|使用前提|混淆|风险|坑点|防坑|常见错误|限制)",
)
_CALLOUT_TIP_START_RE = re.compile(
    r"^\s*(?:💡|📌|🎯|🔍|🧩|🚀|✨)?\s*(?:\*\*)?"
    r"(?:技巧|速判|口诀|模板|题眼|捷径|快速|实战|应用提示|转化技巧|快捷|定位|冲刺策略|快速抓手|关键线索|处理模板|操作要领|实践提示|案例提示)",
)
_CALLOUT_IMPORTANT_START_RE = re.compile(
    r"^\s*(?:✅|🔥|⭐)?\s*(?:\*\*)?"
    r"(?:核心|关键|重点|高频|结论|前提|原理|价值|判断标准|正确逻辑|正确判断|本章定位|高价值|必备|主线|核心判断)",
)
_CALLOUT_NOTE_START_RE = re.compile(
    r"^\s*(?:📝|🔗|📚|📌)?\s*(?:\*\*)?"
    r"(?:补充|延伸|联系|学习价值|提示|应用价值|背景|拓展|小贴士)",
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
_GENERIC_VISIBLE_FOCUS_TITLES = {
    "未命名章节",
    "未命名",
    "本章",
    "本章内容",
    "当前章节",
    "Untitled Chapter",
}


def clean_heading_focus(value: str, *, max_chars: int = 18) -> str:
    """Return a compact content phrase suitable for a visible heading."""

    text = str(value or "")
    text = _KU_ANCHOR_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = strip_heading_number_prefix(text)
    text = re.sub(r"^[\s\-*]*(?:目标|要求|覆盖点|知识点)\s*[:：]\s*", "", text)
    text = re.sub(r"[：:；;。！？!?].*$", "", text)
    text = _FOCUS_ACTION_CLAUSE_RE.sub("", text)
    text = _MARKDOWN_DECORATION_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" ：:，,。；;|-")
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
    for line in str(markdown or "").splitlines():
        if line.lstrip().startswith("```"):
            in_code_fence = not in_code_fence
            lines.append(line)
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
        lines.append(_drop_repeated_visible_heading_line(rewritten, seen_visible_headings))
    return "\n".join(lines)


def _infer_callout_kind(body_lines: Iterable[str]) -> str:
    first_line = next((str(item or "").strip() for item in body_lines if str(item or "").strip()), "")
    if not first_line:
        return ""
    if "答案" in first_line and not any(marker in first_line for marker in ("题眼", "易错", "技巧", "结论", "前提")):
        return ""
    if _CALLOUT_WARNING_START_RE.search(first_line):
        return "WARNING"
    if _CALLOUT_TIP_START_RE.search(first_line):
        return "TIP"
    if _CALLOUT_IMPORTANT_START_RE.search(first_line):
        return "IMPORTANT"
    if _CALLOUT_NOTE_START_RE.search(first_line):
        return "NOTE"
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
    if _CALLOUT_MARKER_RE.match(first_nonempty):
        stripped_body = _strip_first_callout_body_icon(body_lines)
        if stripped_body == body_lines:
            return block_lines
        return [f"> {line}" if line.strip() else ">" for line in stripped_body]

    kind = _infer_callout_kind(body_lines)
    if not kind:
        return block_lines

    body_lines = _strip_first_callout_body_icon(body_lines)
    normalized = [f"> [!{kind}]", ">"]
    normalized.extend(f"> {line}" if line.strip() else ">" for line in body_lines)
    return normalized


def normalize_educational_callouts(markdown: str) -> str:
    """Promote legacy emoji blockquotes into GitHub-style teaching callouts.

    Writer models often produce useful learner-facing blocks such as
    ``> ✅ **速判技巧**`` or ``> ⚠️ **易错点**``. The frontend only renders
    first-class callouts for ``> [!TIP]`` / ``> [!WARNING]`` markers, so this
    deterministic pass adds the stable marker expected by the renderer and
    removes redundant leading icons from the visible body.
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
