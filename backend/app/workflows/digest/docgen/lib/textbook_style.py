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


_HEADING_LINE_RE = re.compile(r"^(?P<prefix>#{2,6})\s+(?P<title>.+?)\s*$")
_MARKDOWN_DECORATION_RE = re.compile(r"[#*_`>{}\[\]()]")
_KU_ANCHOR_RE = re.compile(r"\{#ku_[\w-]+\}|<!--\s*ATM_KU:\s*ku_[\w-]+\s*-->")
_TAG_RE = re.compile(r"\[(?:type|prerequisite|related):[^\]]+\]", re.IGNORECASE)

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


def clean_heading_focus(value: str, *, max_chars: int = 18) -> str:
    """Return a compact content phrase suitable for a visible heading."""

    text = str(value or "")
    text = _KU_ANCHOR_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = re.sub(r"^[\s\-*]*[一二三四五六七八九十\d]+[、.．]\s*", "", text)
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
    heading_title = clean_heading_focus(match.group("title"), max_chars=80)
    if not heading_title:
        return line
    focus = choose_heading_focus(focus_items, fallback=fallback_title)
    kind = _classify_non_textbook_heading(heading_title)
    if kind:
        return build_textbook_heading(
            kind,
            digest_mode=digest_mode,
            focus=focus,
            fallback_title=fallback_title,
            level=match.group("prefix").count("#"),
        )
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

    lines = [
        rewrite_textbook_heading_line(
            line,
            digest_mode=digest_mode,
            fallback_title=fallback_title,
            focus_items=focus_items,
        )
        for line in str(markdown or "").splitlines()
    ]
    return "\n".join(lines)


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
    "normalize_textbook_headings",
    "rewrite_textbook_heading_line",
]
