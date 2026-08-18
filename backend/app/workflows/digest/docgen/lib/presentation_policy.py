"""DocGen presentation policy and deterministic presentation checks."""

from __future__ import annotations

import re
from typing import Any

from app.shared.infra.tools.builtin.markdown_processing import (
    find_markdown_presentation_issues,
    normalize_markdown_rendering,
    normalize_mermaid_blocks,
    summarize_markdown_presentation,
)
from app.workflows.digest.docgen.lib.textbook_style import (
    normalize_educational_callouts,
    normalize_textbook_headings,
)
from app.workflows.digest.docgen.lib.mode_profiles import get_docgen_mode_profile

LEARNING_ROLE_LABELS = {
    "topic": "主题模块",
    "concept": "概念术语",
    "principle": "原理性质",
    "formula_model": "公式模型",
    "procedure": "方法步骤",
    "skill": "解题技能",
    "misconception": "易错辨析",
    "application_case": "应用案例",
}

RELATION_LABELS = {
    "part_of": "归属",
    "prerequisite_for": "前置",
    "derives_to": "推导",
    "applies_to": "应用",
    "uses_method": "用方法",
    "assesses": "考察",
    "explains": "解释",
    "remediates": "补救",
    "confuses_with": "易混",
    "similar_to": "相似",
    "extends_to": "拓展",
}

_INLINE_CODE_SPAN_RE = re.compile(r"(?P<ticks>`+)(?P<body>[^`\n]*?)(?P=ticks)")
_FENCE_OPEN_RE = re.compile(r"(?P<marker>`{3,}|~{3,})")
_TABLE_SEPARATOR_CELL_RE = re.compile(r"\s*:?-{3,}:?\s*")
_UNPAIRED_HIGHLIGHT_ISSUE = "Markdown 高亮标记 == 未成对闭合。"
_UNCONTROLLED_HTML_ISSUE = "Markdown 正文包含不受控 HTML 标签。"
_RAW_HTML_TAG_RE = re.compile(r"</?(?!mark\b|br\b)[A-Za-z][^>\n]{0,120}>", re.IGNORECASE)
_HEADING_ESCAPED_MATH_RE = re.compile(
    r"\\\s+(?P<body>.+?)\\(?=\s+(?:型|轴|方向|平面|坐标|$))"
)
_INLINE_MATH_SPAN_RE = re.compile(r"(?<!\$)\$(?!\$)(?P<body>[^$\n]+)\$(?!\$)")
_QUESTION_CALLOUT_START_RE = re.compile(r"^\s*>\s*\[!QUESTION\]", re.IGNORECASE)
_ANSWER_CALLOUT_START_RE = re.compile(r"^\s*>\s*\[!ANSWER\]", re.IGNORECASE)
_ANY_CALLOUT_START_RE = re.compile(r"^\s*>\s*\[![A-Z]+\]", re.IGNORECASE)
_BODY_ANSWER_START_RE = re.compile(
    r"^\s*(?:>\s*)?(?:\*\*)?(?:答案|参考答案)(?:\*\*)?\s*[:：]?",
    re.IGNORECASE,
)
_BODY_SOLUTION_START_RE = re.compile(
    r"^\s*(?:>\s*)?(?:\*\*)?(?:答案|参考答案|解析|解析步骤|解答|判定依据)"
    r"(?:\*\*)?\s*[:：]?",
    re.IGNORECASE,
)
_BODY_EXPLANATION_START_RE = re.compile(
    r"^\s*(?:>\s*)?(?:\*\*)?(?:解析(?:步骤)?|解法|步骤|判定依据|易错点|错因)"
    r"(?:\*\*)?\s*[:：]?",
    re.IGNORECASE,
)


def _split_unescaped_table_cells(line: str) -> list[str]:
    stripped = str(line or "").strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return re.split(r"(?<!\\)\|", stripped) if "|" in stripped else []


def _is_table_separator_line(line: str) -> bool:
    cells = _split_unescaped_table_cells(line)
    return len(cells) >= 2 and all(_TABLE_SEPARATOR_CELL_RE.fullmatch(cell or "") for cell in cells)


def _is_table_row(line: str) -> bool:
    stripped = str(line or "").strip()
    return bool(stripped and (stripped.startswith("|") or stripped.endswith("|")) and len(_split_unescaped_table_cells(stripped)) >= 2)


def _escape_inline_code_pipes(line: str) -> str:
    def replace_span(match: re.Match[str]) -> str:
        body = re.sub(r"(?<!\\)\|", r"\\|", match.group("body"))
        return f"{match.group('ticks')}{body}{match.group('ticks')}"

    return _INLINE_CODE_SPAN_RE.sub(replace_span, line)


def _protect_docgen_table_inline_code(markdown: str) -> str:
    """Escape pipes inside inline code while traversing GFM table rows."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    fence_state: tuple[str, int] | None = None
    in_table = False
    for index, line in enumerate(lines):
        fence_state, is_fence_boundary = _advance_fence_state(line, fence_state)
        if is_fence_boundary:
            in_table = False
            fixed.append(line)
            continue
        if fence_state is not None:
            fixed.append(line)
            continue
        next_line = lines[index + 1] if index + 1 < len(lines) else ""
        if _is_table_row(line) and _is_table_separator_line(next_line):
            in_table = True
            fixed.append(_escape_inline_code_pipes(line))
            continue
        if in_table and (_is_table_row(line) or _is_table_separator_line(line)):
            fixed.append(_escape_inline_code_pipes(line))
            continue
        in_table = False
        fixed.append(line)
    return "\n".join(fixed)


def _advance_fence_state(
    line: str,
    state: tuple[str, int] | None,
) -> tuple[tuple[str, int] | None, bool]:
    boundary = str(line or "").strip()
    while boundary.startswith(">"):
        boundary = boundary[1:].lstrip()

    if state is None:
        opening = _FENCE_OPEN_RE.match(boundary)
        if opening is None:
            return None, False
        marker = opening.group("marker")
        return (marker[0], len(marker)), True

    marker, length = state
    if re.fullmatch(rf"{re.escape(marker)}{{{length},}}", boundary):
        return None, True
    return state, False


def _normalize_heading_math_artifacts(markdown: str) -> str:
    fixed: list[str] = []
    fence_state: tuple[str, int] | None = None
    for line in str(markdown or "").splitlines():
        fence_state, is_fence_boundary = _advance_fence_state(line, fence_state)
        if is_fence_boundary or fence_state is not None or not re.match(r"^\s*#{1,6}\s+", line):
            fixed.append(line)
            continue

        def replace(match: re.Match[str]) -> str:
            body = match.group("body").strip()
            has_math_signal = bool(
                len(body) == 1
                or re.search(r"[0-9=+*/^_{}]|\\[A-Za-z]+", body)
            )
            return f"${body}$" if body and len(body) <= 80 and has_math_signal else match.group(0)

        fixed.append(_HEADING_ESCAPED_MATH_RE.sub(replace, line))
    return "\n".join(fixed)


def _normalize_inline_math_connectors(markdown: str) -> str:
    def replace(match: re.Match[str]) -> str:
        body = match.group("body")
        if "且" not in body or r"\text{" in body:
            return match.group(0)
        parts = [part.strip() for part in body.split("且")]
        if len(parts) <= 1 or any(not part for part in parts):
            return match.group(0)
        return " 且 ".join(f"${part}$" for part in parts)

    fixed: list[str] = []
    fence_state: tuple[str, int] | None = None
    for line in str(markdown or "").splitlines():
        fence_state, is_fence_boundary = _advance_fence_state(line, fence_state)
        if is_fence_boundary:
            fixed.append(line)
            continue
        if fence_state is not None:
            fixed.append(line)
            continue

        parts: list[str] = []
        cursor = 0
        for code_span in _INLINE_CODE_SPAN_RE.finditer(line):
            parts.append(_INLINE_MATH_SPAN_RE.sub(replace, line[cursor : code_span.start()]))
            parts.append(code_span.group(0))
            cursor = code_span.end()
        parts.append(_INLINE_MATH_SPAN_RE.sub(replace, line[cursor:]))
        fixed.append("".join(parts))
    return "\n".join(fixed)


def _is_plain_solution_boundary(line: str) -> bool:
    return bool(
        _ANY_CALLOUT_START_RE.match(line)
        or re.match(r"^\s*(?:#{1,6}\s+\S|(?:---|\*\*\*|___)\s*$)", line)
    )


def _plain_solution_span(lines: list[str], start: int) -> tuple[int, bool]:
    """Return a complete body-style solution span only when its boundary is unambiguous."""

    cursor = start
    while cursor < len(lines):
        label = _BODY_SOLUTION_START_RE.match(lines[cursor])
        if label is None:
            return cursor, False
        inline_value = lines[cursor][label.end() :].strip(" \t*_：:")
        cursor += 1

        if not inline_value:
            while cursor < len(lines) and not lines[cursor].strip():
                cursor += 1
            if (
                cursor >= len(lines)
                or _is_plain_solution_boundary(lines[cursor])
                or _BODY_SOLUTION_START_RE.match(lines[cursor])
            ):
                return cursor, False
            paragraph_start = cursor
            while cursor < len(lines) and lines[cursor].strip():
                if _is_plain_solution_boundary(lines[cursor]) or _BODY_SOLUTION_START_RE.match(lines[cursor]):
                    break
                cursor += 1
            if cursor == paragraph_start:
                return cursor, False
        else:
            while cursor < len(lines) and lines[cursor].strip():
                if _is_plain_solution_boundary(lines[cursor]) or _BODY_SOLUTION_START_RE.match(lines[cursor]):
                    break
                cursor += 1

        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        if cursor >= len(lines) or _is_plain_solution_boundary(lines[cursor]):
            return cursor, True
        if _BODY_SOLUTION_START_RE.match(lines[cursor]) is None:
            return cursor, False
    return cursor, has_answer


def _dedupe_exact_question_callouts(markdown: str) -> str:
    lines = str(markdown or "").splitlines()
    fixed: list[str] = []
    seen: set[str] = set()
    fence_state: tuple[str, int] | None = None
    index = 0
    while index < len(lines):
        fence_state, is_fence_boundary = _advance_fence_state(lines[index], fence_state)
        if is_fence_boundary or fence_state is not None:
            fixed.append(lines[index])
            index += 1
            continue
        if not _QUESTION_CALLOUT_START_RE.match(lines[index]):
            fixed.append(lines[index])
            index += 1
            continue

        question_end = index + 1
        while question_end < len(lines) and lines[question_end].lstrip().startswith(">"):
            question_end += 1
        atomic_end = question_end
        can_dedupe = True
        followup = question_end
        while followup < len(lines) and not lines[followup].strip():
            followup += 1
        if followup < len(lines) and _ANSWER_CALLOUT_START_RE.match(lines[followup]):
            atomic_end = followup + 1
            while atomic_end < len(lines) and lines[atomic_end].lstrip().startswith(">"):
                atomic_end += 1
        elif followup < len(lines) and _BODY_SOLUTION_START_RE.match(lines[followup]):
            atomic_end, can_dedupe = _plain_solution_span(lines, followup)
            if not can_dedupe:
                atomic_end = question_end
        signature_end = atomic_end
        has_answer = bool(
            followup < atomic_end
            and (
                _ANSWER_CALLOUT_START_RE.match(lines[followup])
                or _BODY_ANSWER_START_RE.match(lines[followup])
            )
        )
        for candidate in range(followup, atomic_end):
            if _BODY_ANSWER_START_RE.match(lines[candidate]):
                has_answer = True
            if has_answer and _BODY_EXPLANATION_START_RE.match(lines[candidate]):
                signature_end = candidate
                break
        signature_lines = [*lines[index:question_end], *lines[followup:signature_end]]
        signature = re.sub(
            r"\s+",
            "",
            "\n".join(
                re.sub(r"^\s*>\s?", "", line)
                for line in signature_lines
            ),
        )
        if not can_dedupe or len(signature) < 24 or signature not in seen:
            fixed.extend(lines[index:atomic_end])
            if can_dedupe and len(signature) >= 24:
                seen.add(signature)
        index = atomic_end
    return "\n".join(fixed)


def _docgen_text_without_code(markdown: str) -> str:
    """Return prose used for highlight validation, excluding code and math."""

    visible: list[str] = []
    in_fence = False
    in_math = False
    for raw_line in str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        stripped = raw_line.strip()
        boundary = stripped.removeprefix(">").strip()
        if boundary.startswith("```"):
            in_fence = not in_fence
            continue
        if boundary == "$$":
            in_math = not in_math
            continue
        if in_fence or in_math:
            continue
        without_code = _INLINE_CODE_SPAN_RE.sub("", raw_line)
        visible.append(_INLINE_MATH_SPAN_RE.sub("", without_code))
    return "\n".join(visible)


def _has_unpaired_docgen_highlight(markdown: str) -> bool:
    markers = re.findall(r"(?<!\\)==", _docgen_text_without_code(markdown))
    return len(markers) % 2 != 0


def build_presentation_policy(*, digest_mode: str = "") -> dict[str, Any]:
    """Return the stable student-facing style contract used by DocGen."""

    profile = get_docgen_mode_profile(digest_mode)
    return {
        "schema_version": 1,
        "source": "docgen.presentation_policy",
        "digest_mode": profile.mode,
        "markdown": {
            "heading_levels": "一级标题只用于章节标题，二/三级标题按内容层级展开，不跳级。",
            "emphasis": "核心概念、关键条件、结论、易错边界可加粗；不要整段加粗。",
            "highlight": "只对短关键句使用 ==...== 或受控 <mark>...</mark>，不要大量高亮。",
            "callouts": ["NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION", "QUESTION", "ANSWER"],
            "callout_usage": "每个较长章节自然放 3-4 个短提示块；至少覆盖关键前提/结论、快速抓手和易错边界，避免堆成长段彩块。",
            "tables": "表格用于对比、分类、步骤、公式汇总、错因分析和学习路径；建议 3-5 列。",
            "visual_grouping": "定义、公式、步骤、例题、易错点和高频规则清单要有清晰边界，避免连续大段正文把不同学习功能混在一起。",
            "formulas": "行内公式用 $...$，多步推导或长公式用 $$...$$，变量和适用条件要解释。",
            "code_blocks": "代码、配置、命令、伪代码必须使用 fenced code block 并标注语言。",
            "mermaid": "Mermaid 必须放在 ```mermaid 代码块；知识图谱关系标签只使用受控关系类型。",
            "html_sidecar": "交互内容只允许独立单文件 HTML sidecar，正文 Markdown 不内嵌任意 HTML。",
        },
        "reader_experience_checks": {
            "long_paragraphs": "避免连续长段正文；长解释要拆成步骤、表格、公式块、例题或短提示。",
            "learning_callout_fields": "正文题干或短练习可用 QUESTION 题块，解析和答案保持普通正文；章末单元测试逐题使用 QUESTION，并把答案与解析放入紧随其后的 ANSWER 折叠块。",
            "reading_blocks": "长章节需要有短提示、表格、公式、图示、代码块或例题等阅读分组，避免整章只有正文和列表。",
            "list_rhythm": "长列表要拆分成小节、表格或练习块，避免学生扫读疲劳。",
        },
        "learning_roles": LEARNING_ROLE_LABELS,
        "relation_labels": RELATION_LABELS,
        "mode_focus": {
            "prompt_label": profile.prompt_label,
            "example_density_policy": dict(profile.example_density_policy),
            "content_mix_policy": dict(profile.content_mix_policy),
            "coverage_policy": list(profile.coverage_policy),
        },
    }


def build_presentation_contract_prompt(*, digest_mode: str = "") -> str:
    """Compact prompt fragment distilled from the full style/check specs."""

    profile = get_docgen_mode_profile(digest_mode)
    relation_text = "、".join(RELATION_LABELS.values())
    if profile.is_sprint:
        structure_line = "- 结构：`# 章节标题` -> 考点速览表（考点/重要程度/题型或任务/抓手） -> `## 01 短考点名`。"
        section_line = "- 紧凑节奏小节先讲具体方法或判断口径，再用例题、任务、解析结论和错因边界落地；标题按内容命名。"
    else:
        structure_line = "- 结构：`# 章节标题` -> 3-5 行导航表 -> `## 01 具体知识点名`。"
        section_line = "- 每个知识点小节包含解释、条件步骤、例题任务、解析结论和易错边界；标题按内容命名。"
    return f"""
Markdown 表达：
{structure_line}
- 二级标题写本章具体知识、方法、任务或场景；三级标题只服务同一小节下的并列子主题。
{section_line}
- 段落短，长列表改成表格、步骤或任务块；表格优先用于对比、分类、步骤和错因。
  - 重点可加粗或少量高亮；每章自然安排 3-4 个短 `> [!IMPORTANT]` / `> [!TIP]` / `> [!WARNING]`，至少覆盖关键前提/结论、快速抓手和易错边界；正文题干或短练习可用 `> [!QUESTION]`，章末单元测试逐题使用 QUESTION，并把答案与解析放入紧随其后的 `> [!ANSWER]` 折叠块。
- 公式、代码、Mermaid 使用可渲染 Markdown；Mermaid 关系标签限：{relation_text}。
- 需要图形辅助时，优先请求 Mermaid：只画靠文字不直观的概念关系、方法流程、几何/坐标/结构关系、对比或实验路径。
- 不要为公式展开、三步文字清单、单条数轴/箭头或纯标签说明生成图；能用一句话讲清的内容用正文和提示块。
- {profile.prompt_label}：紧凑节奏重例题、任务和错误诊断；系统节奏重概念、推理和例子覆盖。
""".strip()


def normalize_docgen_presentation(
    markdown: str,
    *,
    digest_mode: str = "",
    title: str = "",
    focus_items: list[str] | None = None,
) -> str:
    """Run the deterministic presentation normalizers used at DocGen boundaries."""

    cleaned = _protect_docgen_table_inline_code(markdown)
    cleaned = normalize_mermaid_blocks(normalize_markdown_rendering(cleaned))
    cleaned = normalize_textbook_headings(
        cleaned,
        digest_mode=digest_mode,
        fallback_title=title,
        focus_items=focus_items or [],
    )
    cleaned = normalize_educational_callouts(cleaned)
    cleaned = _normalize_heading_math_artifacts(cleaned)
    cleaned = _normalize_inline_math_connectors(cleaned)
    cleaned = _dedupe_exact_question_callouts(cleaned)
    cleaned = normalize_markdown_rendering(cleaned)
    return cleaned


def find_docgen_presentation_issues(markdown: str) -> list[str]:
    issues = find_markdown_presentation_issues(markdown)
    if _UNPAIRED_HIGHLIGHT_ISSUE in issues and not _has_unpaired_docgen_highlight(markdown):
        issues = [issue for issue in issues if issue != _UNPAIRED_HIGHLIGHT_ISSUE]
    if _UNCONTROLLED_HTML_ISSUE in issues and not _RAW_HTML_TAG_RE.search(_docgen_text_without_code(markdown)):
        issues = [issue for issue in issues if issue != _UNCONTROLLED_HTML_ISSUE]
    return issues


def summarize_docgen_presentation(markdown: str) -> dict[str, object]:
    summary = summarize_markdown_presentation(markdown)
    issues = find_docgen_presentation_issues(markdown)
    summary["issues"] = issues[:20]
    summary["issue_count"] = len(issues)
    return summary


def summarize_docgen_presentation_collection(
    chapters: list[dict[str, Any]],
    *,
    merged_markdown: str = "",
    digest_mode: str = "",
) -> dict[str, object]:
    chapter_summaries = [
        {
            "chapter_index": int(chapter.get("chapter_index", 0) or 0),
            "title": str(chapter.get("title") or chapter.get("resolved_title") or ""),
            **summarize_docgen_presentation(str(chapter.get("markdown") or "")),
        }
        for chapter in chapters
    ]
    all_issues = [
        issue
        for summary in chapter_summaries
        for issue in list(summary.get("issues") or [])
        if str(issue).strip()
    ]
    merged_summary = summarize_docgen_presentation(merged_markdown) if merged_markdown else {}
    return {
        "policy": build_presentation_policy(digest_mode=digest_mode),
        "chapter_count": len(chapter_summaries),
        "chapter_issue_count": sum(int(summary.get("issue_count", 0) or 0) for summary in chapter_summaries),
        "merged_issue_count": int(merged_summary.get("issue_count", 0) or 0),
        "top_issues": list(dict.fromkeys(all_issues))[:20],
        "chapters": chapter_summaries,
        "merged": merged_summary,
    }


__all__ = [
    "build_presentation_contract_prompt",
    "build_presentation_policy",
    "find_docgen_presentation_issues",
    "normalize_docgen_presentation",
    "summarize_docgen_presentation",
    "summarize_docgen_presentation_collection",
]
