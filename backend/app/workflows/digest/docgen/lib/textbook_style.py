"""Student-facing textbook style policies for DocGen.

The writer/review pipeline may reason in terms of review, recap, coverage,
or repair. Those words are useful internally, but they should not leak into
the final Markdown as section titles. This module is the single place that
turns internal teaching intent into visible textbook-like headings and worked
example blocks.
"""

from __future__ import annotations

from collections.abc import Iterable
import re
from typing import Any


_HEADING_LINE_RE = re.compile(r"^(?P<prefix>#{1,6})\s+(?P<title>.+?)\s*$")
_BLOCKQUOTE_LINE_RE = re.compile(r"^\s*>\s?(?P<body>.*)$")
_CALLOUT_MARKER_RE = re.compile(r"^\s*\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]", re.IGNORECASE)
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

_CONTENT_HEADING_TERMS = (
    "定义",
    "概念",
    "性质",
    "定理",
    "公式",
    "判定",
    "计算",
    "证明",
    "推导",
    "方法",
    "结构",
    "关系",
    "分布",
    "概率",
    "期望",
    "方差",
    "矩阵",
    "向量",
    "函数",
    "方程",
    "系统",
    "进程",
    "线程",
    "内存",
    "文件",
    "调度",
    "I/O",
    "IO",
    "例题",
    "题型",
    "应用",
    "实验",
    "误差",
    "估计",
    "检验",
)

_LOW_INFORMATION_HEADING_MARKERS = (
    "本章",
    "这一",
    "这章",
    "这些",
    "关键",
    "重点",
    "内容",
    "要点",
    "目标",
    "清单",
)
_ACTION_STYLE_RE = re.compile(
    r"(?:先|再|最后|优先|应该|需要|必须|可以|怎么|如何|为什么|什么|哪些|"
    r"看|问|记|补|抓|拿|学|做|掌握|检查|确认|串联|整理)"
)
_QUESTION_STYLE_RE = re.compile(r"(?:吗|呢|么|怎么|如何|为什么|什么|哪些|？|\?)")

_KIND_SUFFIX = {
    "coverage": "补充讲解",
    "points": "核心要点",
    "questions": "典型判断问题",
    "links": "知识联系",
    "summary": "核心总结",
    "examples": "典型例题解析",
    "practice": "练习与巩固",
    "structure": "知识结构",
    "quickref": "公式与判定速查",
}
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


def clean_heading_focus(value: str, *, max_chars: int = 18) -> str:
    """Return a compact content phrase suitable for a visible heading."""

    text = str(value or "")
    text = _KU_ANCHOR_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = strip_heading_number_prefix(text)
    text = re.sub(r"^[\s\-*]*(?:目标|要求|覆盖点|知识点)\s*[:：]\s*", "", text)
    text = re.sub(r"[：:；;。！？!?].*$", "", text)
    text = _MARKDOWN_DECORATION_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip(" ：:，,。；;|-")
    if not text:
        return ""
    if len(text) > max_chars:
        text = text[:max_chars].rstrip(" ：:，,。；;|-")
    return text


def choose_heading_focus(items: Iterable[str], *, fallback: str = "", max_chars: int = 18) -> str:
    """Pick a content-specific focus phrase and avoid internal scaffold words."""

    fallback_focus = clean_heading_focus(fallback, max_chars=max_chars)
    for item in items:
        focus = clean_heading_focus(str(item), max_chars=max_chars)
        if not focus:
            continue
        if _looks_like_non_content_phrase(focus):
            continue
        return focus
    return fallback_focus


def build_textbook_heading(
    kind: str,
    *,
    digest_mode: str,
    focus: str = "",
    fallback_title: str = "",
    level: int = 2,
) -> str:
    """Build a student-facing heading from a semantic kind and content focus."""

    prefix = "#" * max(2, min(6, int(level or 2)))
    normalized_mode = str(digest_mode or "systematic").strip().lower()
    resolved_focus = clean_heading_focus(focus) or clean_heading_focus(fallback_title)
    suffix = _KIND_SUFFIX.get(kind, "核心内容")
    if kind == "examples":
        suffix = "典型例题解析" if normalized_mode == "sprint" else "例题与迁移"
    if kind == "practice":
        return f"{prefix} 练习与巩固"
    if kind == "questions" and not resolved_focus:
        return f"{prefix} 典型判断问题"
    if kind == "points" and not resolved_focus:
        return f"{prefix} 核心要点"
    if not resolved_focus:
        return f"{prefix} {suffix}"
    return f"{prefix} {resolved_focus}的{suffix}"


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
    return cleaned or default


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
    numberless_title = strip_heading_number_prefix(raw_title)
    level = match.group("prefix").count("#")
    if level == 1:
        if numberless_title and numberless_title != raw_title:
            return f"{match.group('prefix')} {numberless_title}"
        if not numberless_title and fallback_title:
            return f"{match.group('prefix')} {_numberless_fallback_title(fallback_title, default='未命名章节')}"
        return line

    heading_title = clean_heading_focus(numberless_title, max_chars=80)
    if not heading_title:
        if numberless_title != raw_title:
            return f"{match.group('prefix')} {_numberless_fallback_title(fallback_title, default='本章内容')}"
        return line
    focus = choose_heading_focus(focus_items, fallback=fallback_title)
    kind = _classify_non_textbook_heading(heading_title)
    if kind:
        return build_textbook_heading(
            kind,
            digest_mode=digest_mode,
            focus=focus,
            fallback_title=fallback_title,
            level=level,
        )
    if numberless_title and numberless_title != raw_title:
        return f"{match.group('prefix')} {numberless_title}"
    return line


def _classify_non_textbook_heading(title: str) -> str:
    """Classify non-textbook headings by quality signals instead of title rewrites."""

    cleaned = str(title or "").strip()
    if not cleaned:
        return ""
    has_content_term = any(term in cleaned for term in _CONTENT_HEADING_TERMS)
    if re.search(r"(?:例题|题型|练习|解析|变式)", cleaned):
        if len(cleaned) <= 8 or _looks_like_non_content_phrase(cleaned):
            return "examples"
        return ""
    if "公式" in cleaned or "速查" in cleaned or "结论" in cleaned:
        return "" if has_content_term else "quickref"
    if "关系" in cleaned or "联系" in cleaned:
        return "" if has_content_term else "links"
    if _looks_like_non_content_phrase(cleaned):
        if "要点" in cleaned:
            return "points"
        if "问题" in cleaned:
            return "questions"
        if _QUESTION_STYLE_RE.search(cleaned):
            return "questions"
        if re.search(r"(?:补|缺|覆盖|关键|重点)", cleaned):
            return "coverage"
        if re.search(r"(?:总结|整理|归纳|小结|带走)", cleaned):
            return "summary"
        return "structure"
    if cleaned.startswith(("第", "本节", "本章", "这一章", "这章")) and not has_content_term:
        return "structure"
    return ""


def _looks_like_non_content_phrase(text: str) -> bool:
    """Return true when a heading/focus phrase is instructional wording, not a topic."""

    cleaned = str(text or "").strip()
    if not cleaned:
        return True
    has_content_term = any(term in cleaned for term in _CONTENT_HEADING_TERMS)
    if has_content_term:
        return False
    marker_count = sum(1 for marker in _LOW_INFORMATION_HEADING_MARKERS if marker in cleaned)
    has_action_style = bool(_ACTION_STYLE_RE.search(cleaned))
    if marker_count and has_action_style:
        return True
    if _QUESTION_STYLE_RE.search(cleaned):
        return True
    if len(cleaned) <= 8 and (marker_count or has_action_style):
        return True
    if cleaned.startswith(("第", "本节", "本章", "这一章", "这章")):
        return True
    return False


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
    for line in str(markdown or "").splitlines():
        if line.lstrip().startswith("```"):
            in_code_fence = not in_code_fence
            lines.append(line)
            continue
        if in_code_fence:
            lines.append(line)
            continue
        lines.append(
            rewrite_textbook_heading_line(
                line,
                digest_mode=digest_mode,
                fallback_title=fallback_title,
                focus_items=focus_items,
            )
        )
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


def _normalize_blockquote_callout(block_lines: list[str]) -> list[str]:
    body_lines: list[str] = []
    for line in block_lines:
        match = _BLOCKQUOTE_LINE_RE.match(line)
        if match is None:
            return block_lines
        body_lines.append(str(match.group("body") or "").rstrip())

    first_nonempty = next((line.strip() for line in body_lines if line.strip()), "")
    if not first_nonempty or _CALLOUT_MARKER_RE.match(first_nonempty):
        return block_lines

    kind = _infer_callout_kind(body_lines)
    if not kind:
        return block_lines

    normalized = [f"> [!{kind}]", ">"]
    normalized.extend(f"> {line}" if line.strip() else ">" for line in body_lines)
    return normalized


def normalize_educational_callouts(markdown: str) -> str:
    """Promote legacy emoji blockquotes into GitHub-style teaching callouts.

    Writer models often produce useful learner-facing blocks such as
    ``> ✅ **速判技巧**`` or ``> ⚠️ **易错点**``. The frontend only renders
    first-class callouts for ``> [!TIP]`` / ``> [!WARNING]`` markers, so this
    deterministic pass preserves the original emoji text while adding the
    stable marker expected by the renderer.
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


def has_worked_example_section(markdown: str) -> bool:
    return bool(
        re.search(
            r"(?m)^##\s+.*(?:例题|题型|解析|练习|迁移).*$",
            str(markdown or ""),
        )
    )


def format_worked_example_section(
    examples: list[dict[str, Any]],
    *,
    digest_mode: str,
    fallback_title: str,
    focus_items: Iterable[str] = (),
) -> str:
    """Render examples as a textbook-style worked-example section."""

    if not examples:
        return ""
    focus = choose_heading_focus(focus_items, fallback=fallback_title)
    lines = [
        build_textbook_heading(
            "examples",
            digest_mode=digest_mode,
            focus=focus,
            fallback_title=fallback_title,
        ),
        "",
    ]
    for index, item in enumerate(examples, start=1):
        label = clean_heading_focus(str(item.get("label") or item.get("type") or ""), max_chars=24)
        stem = str(item.get("stem") or item.get("question") or "").strip()
        analysis_steps = [
            str(step).strip()
            for step in list(item.get("analysis_steps") or [])
            if str(step).strip()
        ]
        pitfall = str(item.get("pitfall") or "").strip()
        if not stem:
            continue
        title = f"例题 {index}" + (f"：{label}" if label else "")
        lines.extend([f"### {title}", "", f"**题目**：{stem}", "", "**解析**："])
        if analysis_steps:
            lines.extend(f"{step_index}. {step}" for step_index, step in enumerate(analysis_steps, start=1))
        else:
            lines.extend(
                [
                    "1. 先识别题目给出的对象、条件和要求。",
                    "2. 再选择本章对应的定义、公式或判定方法。",
                    "3. 最后检查结论是否满足题目条件和单位/范围要求。",
                ]
            )
        if pitfall:
            lines.extend(["", f"**易错点**：{pitfall}"])
        lines.append("")
    return "\n".join(lines).strip()


__all__ = [
    "build_textbook_heading",
    "choose_heading_focus",
    "clean_heading_focus",
    "format_worked_example_section",
    "has_worked_example_section",
    "normalize_educational_callouts",
    "normalize_textbook_headings",
    "rewrite_textbook_heading_line",
    "strip_heading_number_prefix",
]
