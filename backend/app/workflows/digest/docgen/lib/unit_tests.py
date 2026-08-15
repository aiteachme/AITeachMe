"""Chapter-end unit test generation and rendering."""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.workflows.digest.docgen.lib.models import (
    DocGenBaseModel,
    clean_string_list,
    clean_text,
)


_BODY_TEST_OR_RECAP_HEADING_RE = re.compile(r"(?ms)^##\s+(?P<title>[^\n]+?)\s*\n.*?(?=^##\s+|\Z)")
_HEADING_NUMBER_PREFIX_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s*)+")
_UNIT_TEST_TABLE_HEADER_RE = re.compile(
    r"(?m)^\|\s*题号\s*\|\s*训练点\s*\|\s*题目\s*/\s*任务\s*\|\s*答案与判定依据\s*\|"
)
_UNIT_TEST_HTML_BLOCK_RE = re.compile(r'(?ms)<div\s+class="atm-unit-tests"[^>]*>.*?(?=^##\s+|\Z)')
_STANDARD_UNIT_TEST_HEADING_RE = re.compile(r"(?m)^##\s+单元测试\s*$")
_H3_BODY_TEST_OR_RECAP_HEADING_RE = re.compile(r"(?ms)^###\s+(?P<title>[^\n]+?)\s*\n.*?(?=^#{2,3}\s+|\Z)")

_QUESTION_TYPE_ALIASES: dict[str, str] = {
    "判断": "概念判断",
    "判断题": "概念判断",
    "概念题": "概念判断",
    "truefalse": "概念判断",
    "true_false": "概念判断",
    "单选": "选择题",
    "单选题": "选择题",
    "选择": "选择题",
    "choice": "选择题",
    "single_choice": "选择题",
    "填空": "填空题",
    "填空题": "填空题",
    "计算": "填空题",
    "计算题": "填空题",
    "步骤": "步骤排序",
    "排序": "步骤排序",
    "流程": "步骤排序",
    "步骤排序题": "步骤排序",
    "错因": "错因辨析",
    "易错": "错因辨析",
    "辨析": "错因辨析",
    "错因辨析题": "错因辨析",
    "短答": "短答题",
    "简答": "短答题",
    "问答": "短答题",
    "short_answer": "短答题",
    "应用": "应用迁移",
    "迁移": "应用迁移",
    "案例": "应用迁移",
    "应用题": "应用迁移",
    "图表": "图表读取",
    "图示": "图表读取",
    "图像": "图表读取",
    "推导": "推导证明",
    "证明": "推导证明",
    "证明题": "推导证明",
}
_QUESTION_TYPE_ORDER = ["概念判断", "选择题", "填空题", "步骤排序", "错因辨析", "短答题", "应用迁移", "图表读取", "推导证明"]
_DIFFICULTY_ALIASES = {
    "easy": "基础",
    "basic": "基础",
    "基础题": "基础",
    "medium": "进阶",
    "normal": "进阶",
    "标准": "进阶",
    "hard": "挑战",
    "challenge": "挑战",
    "困难": "挑战",
    "提升": "挑战",
}
_DIFFICULTY_ORDER = ["基础", "进阶", "挑战"]
_CHOICE_LABEL_RE = re.compile(r"^\s*(?:[A-Da-d][.)、:：]\s*)?(?P<text>.+?)\s*$")
_MATH_SPAN_RE = re.compile(r"(\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])")
_RAW_LATEX_FRAGMENT_RE = re.compile(
    r"(?<![$\\])"
    r"(?P<formula>"
    r"(?:[A-Za-z0-9_+\-*/=<>≤≥^{}()[\],. ]|\\[A-Za-z]+|\\[{}])*"
    r"\\(?:sqrt|frac|lim|sin|cos|tan|cot|ln|log|sum|int|Delta|delta|epsilon|varepsilon|theta|pi|infty|cdot|times|leq|geq|neq|to|sim)(?![A-Za-z])"
    r"(?:[A-Za-z0-9_+\-*/=<>≤≥^{}()[\],. ]|\\[A-Za-z]+|\\[{}])*"
    r")"
    r"(?![$])"
)
_MATH_HINT_RE = re.compile(
    r"(\${1,2}|\\\(|\\\[|\\(?:sqrt|frac|lim|sin|cos|tan|cot|ln|log|sum|int|Delta|delta|epsilon|varepsilon|theta|pi|infty|cdot|times|leq|geq|neq|to|sim)\b)"
)
_LEADING_TABLE_PIPE_BEFORE_MATH_RE = re.compile(
    r"(?m)(^|[\s(（])(?:\\\||\|)+\s*(?=(?:\\?\${1,2}|\\\(|\\\[|\\(?:sqrt|frac|lim|sin|cos|tan|ln|log|sum|int)\b))"
)
_ESCAPED_MATH_DOLLAR_RE = re.compile(r"\\(\${1,2})")
_UNIT_TEST_CALLOUT_START_RE = re.compile(
    r"^\s*>\s*\[!(?P<kind>QUESTION|ANSWER)\](?P<rest>.*)$",
    re.IGNORECASE,
)
_UNIT_TEST_QUESTION_HEADER_RE = re.compile(
    r"\*\*Q(?P<number>\d+)\s*[｜|]\s*(?P<type>[^｜|*]+)\s*[｜|]",
    re.IGNORECASE,
)
_UNIT_TEST_OPTION_LINE_RE = re.compile(
    r"^\s*(?:[-*+]\s*)?(?:\*\*)?(?P<label>[A-Da-d])(?:\*\*)?[.)、:：]\s*(?P<value>\S.*)$"
)
_UNIT_TEST_FIELD_ONLY_RE = re.compile(
    r"^\s*(?:\*\*)?(?:题目|题干|选项|答案|解析|解析步骤|判定依据)(?:\*\*)?\s*(?:[:：])?\s*$"
)


class ChapterUnitTestGenerationError(RuntimeError):
    """Raised when the unit-test model does not produce usable visible questions."""


def _compact_label(value: str) -> str:
    return re.sub(r"[\s_\-：:，,。；;、/]+", "", str(value or "").strip()).lower()


def _normalize_question_type(value: str) -> str:
    text = clean_text(value)
    compact = _compact_label(text)
    if not compact:
        return "短答题"
    return _QUESTION_TYPE_ALIASES.get(compact) or _QUESTION_TYPE_ALIASES.get(text) or text[:12]


def _normalize_difficulty(value: str) -> str:
    text = clean_text(value)
    compact = _compact_label(text)
    if not compact:
        return "基础"
    return _DIFFICULTY_ALIASES.get(compact) or _DIFFICULTY_ALIASES.get(text) or (text if text in _DIFFICULTY_ORDER else "进阶")


def _normalize_choice_options(value: Any) -> list[str]:
    if value is None:
        raw_items: list[Any] = []
    elif isinstance(value, dict):
        raw_items = [value[key] for key in sorted(value)]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_text = str(value or "")
        raw_items = [item for item in re.split(r"\n|[;；]", raw_text) if item.strip()]

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = _sanitize_unit_test_math_text(item)
        match = _CHOICE_LABEL_RE.match(text)
        if match:
            text = match.group("text").strip()
        if not text:
            continue
        key = _compact_label(text)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= 4:
            break
    return cleaned[:4]


def _is_body_generated_test_or_recap_heading(title: str) -> bool:
    """Identify body-writer test/recap H2 blocks removed before the unit-test node appends one."""

    normalized = _HEADING_NUMBER_PREFIX_RE.sub("", str(title or "")).strip(" ：:，,。；; ")
    compact = re.sub(r"\s+", "", normalized)
    if not compact:
        return False
    if any(label in compact for label in ("单元测试", "单元小测", "章末测试", "章末小测", "章末练习")):
        return True
    if any(label in compact for label in ("快速自测", "小结式检查清单")):
        return True
    if "小结" in compact and "检查清单" in compact:
        return True
    if compact in {"本章收口", "本章回看", "本章回顾", "本章总结", "本章复盘"}:
        return True
    if compact.startswith("本章") and any(label in compact for label in ("收口", "回看", "回顾", "总结", "复盘")):
        return True
    if compact.startswith("章末") and any(label in compact for label in ("收口", "回看", "回顾", "总结", "复盘")):
        return True
    return False


def _is_standard_unit_test_heading(title: str) -> bool:
    normalized = _HEADING_NUMBER_PREFIX_RE.sub("", str(title or "")).strip(" ：:，,。；; ")
    return re.sub(r"\s+", "", normalized) == "单元测试"


class ChapterUnitTestItem(DocGenBaseModel):
    """One compact item for the rendered chapter-end unit test cards."""

    type: str = "短答题"
    difficulty: str = "基础"
    target: str = ""
    stem: str = ""
    options: list[str] = Field(default_factory=list)
    answer: str = ""
    basis: str = ""

    @field_validator("type", "difficulty", "target", "stem", "answer", "basis", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @field_validator("options", mode="before")
    @classmethod
    def _options(cls, value: Any) -> list[str]:
        return _normalize_choice_options(value)

    @model_validator(mode="after")
    def _normalize_fields(self) -> "ChapterUnitTestItem":
        self.type = _normalize_question_type(self.type)
        self.difficulty = _normalize_difficulty(self.difficulty)
        self.options = _normalize_choice_options(self.options)
        answer_label = re.fullmatch(
            r"(?:选项\s*)?([A-Da-d])(?:[.、:：]\s*(.*))?",
            self.answer.strip(),
        )
        if answer_label is not None:
            answer_index = ord(answer_label.group(1).upper()) - ord("A")
            answer_suffix = clean_text(answer_label.group(2) or "")
            if 0 <= answer_index < len(self.options):
                option = self.options[answer_index]
                if not answer_suffix or _compact_label(answer_suffix) == _compact_label(option):
                    self.answer = option
        if not _is_choice_unit_test_type(self.type):
            self.options = []
        return self


class ChapterUnitTestSet(DocGenBaseModel):
    """Structured LLM result for one chapter's unit test."""

    chapter_index: int = 1
    items: list[ChapterUnitTestItem] = Field(default_factory=list)

    @field_validator("items", mode="before")
    @classmethod
    def _items(cls, value: Any) -> list[Any]:
        return value if isinstance(value, list) else []


def strip_existing_unit_test_sections(markdown: str) -> str:
    """Remove unit-test H2 blocks that the body writer may have generated."""

    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = _BODY_TEST_OR_RECAP_HEADING_RE.sub(
        lambda match: "" if _is_body_generated_test_or_recap_heading(match.group("title")) else match.group(0),
        text,
    )
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"


def _markdown_text(value: str, *, limit: int | None = None) -> str:
    text = " ".join(_sanitize_unit_test_math_text(value).strip().split())
    text = _wrap_raw_latex_fragments(text)
    if limit is not None and len(text) > limit and not _MATH_HINT_RE.search(text):
        text = text[: max(1, limit - 1)].rstrip(" ，,。；;、") + "…"
    return text


def _markdown_explanation_lines(value: str, *, limit: int = 520) -> list[str]:
    text = _markdown_text(value, limit=limit)
    if not text:
        return []
    numbered_parts = re.split(r"(?:^|\s+)(?=\d+[.、]\s+)", text)
    if len([part for part in numbered_parts if part.strip()]) > 1:
        return [re.sub(r"^\d+[.、]\s*", "", part).strip() for part in numbered_parts if part.strip()]
    parts = [
        part.strip()
        for part in re.split(r"[；;]\s*|(?<=[。！？!?])\s+", text)
        if part.strip()
    ]
    return parts if len(parts) > 1 else [text]


def _wrap_raw_latex_fragments(text: str) -> str:
    """Wrap obvious raw LaTeX snippets so MarkdownViewer can hand them to KaTeX."""

    value = str(text or "")
    if "\\" not in value:
        return value

    parts = _MATH_SPAN_RE.split(value)
    for index, part in enumerate(parts):
        if not part or _MATH_SPAN_RE.fullmatch(part):
            continue

        def replace(match: re.Match[str]) -> str:
            formula = match.group("formula").strip()
            if not formula or any("\u4e00" <= char <= "\u9fff" for char in formula):
                return match.group(0)
            return f"${formula}$"

        parts[index] = _RAW_LATEX_FRAGMENT_RE.sub(replace, part)
    return "".join(parts)


def _sanitize_unit_test_math_text(value: Any) -> str:
    """Fix common model artifacts before Markdown/KaTeX rendering."""

    text = clean_text(value)
    if not text:
        return ""
    text = _ESCAPED_MATH_DOLLAR_RE.sub(r"\1", text)
    text = _LEADING_TABLE_PIPE_BEFORE_MATH_RE.sub(r"\1", text)
    return text.strip()


def _ordered_unique(values: list[str], order: list[str]) -> list[str]:
    order_index = {value: index for index, value in enumerate(order)}
    return sorted(set(values), key=lambda value: (order_index.get(value, 999), value))


def _is_choice_unit_test_type(question_type: str) -> bool:
    return _normalize_question_type(question_type) == "选择题"


def _unit_test_section(markdown: str) -> tuple[list[str], list[str]]:
    lines = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    h2_indices = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^##\s+单元测试\s*$", line.strip())
    ]
    if not h2_indices:
        return [], ["缺少固定的章末 `## 单元测试` 模块。"]
    if len(h2_indices) > 1:
        return [], ["存在重复的 `## 单元测试` 模块。"]
    start = h2_indices[0]
    next_h2 = next(
        (
            index
            for index in range(start + 1, len(lines))
            if re.match(r"^##\s+\S", lines[index].strip())
        ),
        len(lines),
    )
    if next_h2 < len(lines):
        return lines[start + 1 : next_h2], ["`## 单元测试` 必须是本章最后一个二级标题。"]
    return lines[start + 1 :], []


def _callout_visible_lines(lines: list[str], *, marker_rest: str) -> tuple[list[str], bool]:
    visible: list[str] = []
    has_floating_line = False
    if marker_rest.strip():
        visible.append(marker_rest.strip())
    for line in lines:
        if not line.strip():
            continue
        if not re.match(r"^\s*>", line):
            has_floating_line = True
            visible.append(line.strip())
            continue
        visible.append(re.sub(r"^\s*>\s?", "", line).strip())
    return visible, has_floating_line


def unit_test_structure_issues(markdown: str) -> list[str]:
    """Validate the deterministic QUESTION/ANSWER publication contract.

    This parser only checks the Markdown protocol.  It does not infer teaching
    semantics or attempt to reconstruct malformed questions locally.
    """

    section_lines, issues = _unit_test_section(markdown)
    if issues:
        return issues

    blocks: list[tuple[str, str, list[str]]] = []
    current_kind = ""
    current_rest = ""
    current_lines: list[str] = []
    for line in section_lines:
        marker = _UNIT_TEST_CALLOUT_START_RE.match(line)
        if marker is not None:
            if current_kind:
                blocks.append((current_kind, current_rest, current_lines))
            current_kind = marker.group("kind").upper()
            current_rest = marker.group("rest")
            current_lines = []
            continue
        if current_kind:
            current_lines.append(line)
    if current_kind:
        blocks.append((current_kind, current_rest, current_lines))

    if not blocks:
        return ["单元测试没有使用 QUESTION/ANSWER 题答块。"]
    if len(blocks) % 2 or any(
        block[0] != ("QUESTION" if index % 2 == 0 else "ANSWER")
        for index, block in enumerate(blocks)
    ):
        issues.append("单元测试存在未配对的 QUESTION 或 ANSWER 块。")

    question_numbers: set[str] = set()
    normalized_answers: set[str] = set()
    question_ordinal = 0
    for block_index, question in enumerate(blocks):
        if question[0] != "QUESTION":
            if block_index == 0 or blocks[block_index - 1][0] != "QUESTION":
                issues.append("检测到没有对应 QUESTION 的游离 ANSWER 块。")
            continue
        question_ordinal += 1
        answer = blocks[block_index + 1] if block_index + 1 < len(blocks) else None
        if answer is None or answer[0] != "ANSWER":
            issues.append(f"第 {question_ordinal} 题没有按 QUESTION 后紧跟 ANSWER 的顺序排列。")

        question_lines, question_has_floating = _callout_visible_lines(
            question[2],
            marker_rest=question[1],
        )
        answer_lines: list[str] = []
        answer_has_floating = False
        if answer is not None and answer[0] == "ANSWER":
            answer_lines, answer_has_floating = _callout_visible_lines(
                answer[2],
                marker_rest=answer[1],
            )
        if question_has_floating or answer_has_floating:
            issues.append(f"第 {question_ordinal} 题有内容跑出 QUESTION/ANSWER 引用块。")

        question_text = "\n".join(question_lines)
        header = _UNIT_TEST_QUESTION_HEADER_RE.search(question_text)
        if header is None:
            issues.append(f"第 {question_ordinal} 题缺少 `Qxx｜题型｜难度｜考点` 标头。")
            question_type = ""
        else:
            number = header.group("number")
            question_type = _normalize_question_type(header.group("type"))
            if number in question_numbers:
                issues.append(f"题号 Q{number} 重复。")
            question_numbers.add(number)

        if any(re.search(r"(?:\*\*)?(?:答案|正确答案|参考答案)(?:\*\*)?\s*[:：]?", line) for line in question_lines):
            issues.append(f"第 {question_ordinal} 题把答案写进了 QUESTION 块。")

        option_labels = [
            match.group("label").upper()
            for line in question_lines
            if (match := _UNIT_TEST_OPTION_LINE_RE.match(line)) is not None
        ]
        option_values = [
            match.group("value").strip()
            for line in question_lines
            if (match := _UNIT_TEST_OPTION_LINE_RE.match(line)) is not None
        ]
        stem_lines = [
            line
            for line in question_lines
            if line
            and _UNIT_TEST_QUESTION_HEADER_RE.search(line) is None
            and _UNIT_TEST_FIELD_ONLY_RE.match(line) is None
            and _UNIT_TEST_OPTION_LINE_RE.match(line) is None
        ]
        if not stem_lines:
            issues.append(f"第 {question_ordinal} 题题干为空。")
        if question_type == "选择题":
            if option_labels != ["A", "B", "C", "D"]:
                issues.append(f"第 {question_ordinal} 道选择题必须且只能包含 A-D 四个选项。")
        elif option_labels:
            issues.append(f"第 {question_ordinal} 道非选择题不应显示 A-D 选项。")

        answer_label_indices = [
            index
            for index, line in enumerate(answer_lines)
            if re.match(r"^\s*\*\*答案\*\*\s*$", line)
        ]
        answer_label_index = answer_label_indices[0] if answer_label_indices else None
        if answer_label_index is None:
            issues.append(f"第 {question_ordinal} 题的 ANSWER 块缺少独立 `**答案**` 字段。")
            answer_value_lines: list[str] = []
        else:
            if len(answer_label_indices) > 1:
                issues.append(f"第 {question_ordinal} 题的 ANSWER 块重复出现 `**答案**` 字段。")
            answer_value_lines = []
            for line in answer_lines[answer_label_index + 1 :]:
                if _UNIT_TEST_FIELD_ONLY_RE.match(line):
                    break
                if line:
                    answer_value_lines.append(line)
        if not answer_value_lines:
            issues.append(f"第 {question_ordinal} 题答案为空。")
        normalized_answer = _compact_label("".join(answer_value_lines))
        if question_type == "选择题" and normalized_answer:
            normalized_options = {_compact_label(value) for value in option_values}
            if normalized_answer not in normalized_options:
                issues.append(f"第 {question_ordinal} 道选择题的答案必须与 A-D 中某个完整选项一致。")
        if normalized_answer:
            if normalized_answer in normalized_answers:
                issues.append(f"第 {question_ordinal} 题与前题出现完全重复的答案与解析。")
            normalized_answers.add(normalized_answer)

    return clean_string_list(issues, limit=24)


def _is_usable_unit_test_item(item: ChapterUnitTestItem) -> bool:
    if not item.target.strip() or not item.stem.strip() or not item.answer.strip() or not item.basis.strip():
        return False
    if _is_choice_unit_test_type(item.type):
        options = _normalize_choice_options(item.options)
        return len(options) == 4 and _compact_label(item.answer) in {
            _compact_label(option) for option in options
        }
    return True


def _dedupe_unit_test_items(items: list[ChapterUnitTestItem]) -> list[ChapterUnitTestItem]:
    deduped: list[ChapterUnitTestItem] = []
    seen: set[str] = set()
    for item in items:
        key = _compact_label(f"{item.type}|{item.target}|{item.stem}")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _prepare_unit_test_items(
    items: list[ChapterUnitTestItem],
    *,
    title: str,
    min_items: int,
    fallback_targets: list[str],
    max_items: int | None = None,
) -> list[ChapterUnitTestItem]:
    limit = max_items if max_items is not None else max(min_items, len(items))
    limit = max(min_items, min(int(limit or min_items), 12))
    prepared = [item for item in _dedupe_unit_test_items(list(items or [])) if _is_usable_unit_test_item(item)][:limit]
    if len(prepared) < min_items:
        raise ChapterUnitTestGenerationError(
            f"unit-test model returned {len(prepared)} usable items, expected at least {min_items} for {title}"
        )
    return prepared[:limit]


def _render_unit_test_overview_markdown(items: list[ChapterUnitTestItem]) -> str:
    types = _ordered_unique([_normalize_question_type(item.type) for item in items], _QUESTION_TYPE_ORDER)
    difficulties = _ordered_unique([_normalize_difficulty(item.difficulty) for item in items], _DIFFICULTY_ORDER)
    type_text = " / ".join(types[:5]) + (" ..." if len(types) > 5 else "")
    difficulty_text = " / ".join(difficulties)
    targets = clean_string_list([item.target for item in items], limit=8)
    coverage_text = "、".join(targets[:6]) + ("…" if len(targets) > 6 else "")
    return "\n".join(
        [
            f"**{len(items)} 题覆盖**：{coverage_text or '本章核心考点'}",
            f"**题型与难度**：{type_text}；{difficulty_text}",
        ]
    )


def _render_unit_test_item_markdown(item: ChapterUnitTestItem, *, index: int) -> str:
    question_type = _normalize_question_type(item.type)
    difficulty = _normalize_difficulty(item.difficulty)
    lines = [
        f"> [!QUESTION] **Q{index:02d}｜{question_type}｜{difficulty}｜考点：{_markdown_text(item.target, limit=48)}**",
        ">",
        "> **题目**",
        ">",
        f"> {_markdown_text(item.stem, limit=720)}",
    ]
    if _is_choice_unit_test_type(question_type) and item.options:
        lines.extend([">", "> **选项**", ">"])
        lines.extend([f"> - {label}. {_markdown_text(option, limit=160)}" for label, option in zip("ABCD", item.options)])
    explanation_lines = _markdown_explanation_lines(item.basis, limit=720)
    lines.extend(["", "> [!ANSWER]", ">", "> **答案**", ">"])
    answer_text = _markdown_text(item.answer, limit=720) or "见解析。"
    lines.append(f"> {answer_text}")
    if explanation_lines:
        lines.extend([">", "> **解析步骤**", ">"])
        if len(explanation_lines) == 1:
            lines.append(f"> {explanation_lines[0]}")
        else:
            lines.extend(f"> {step}. {line}" for step, line in enumerate(explanation_lines[:5], start=1))
    return "\n".join(lines).strip()


def render_unit_test_markdown(
    result: ChapterUnitTestSet,
    *,
    title: str,
    min_items: int,
    fallback_targets: list[str],
    max_items: int | None = None,
) -> str:
    """Render unit tests as native Markdown so math and typography stay consistent."""

    items = _prepare_unit_test_items(
        list(result.items or []),
        title=title,
        min_items=min_items,
        max_items=max_items,
        fallback_targets=fallback_targets,
    )
    lines = [
        "## 单元测试",
        "",
        _render_unit_test_overview_markdown(items),
    ]
    for index, item in enumerate(items, start=1):
        lines.extend(["", _render_unit_test_item_markdown(item, index=index)])
    return "\n".join(lines).strip() + "\n"


def append_unit_test_markdown(markdown: str, unit_test_markdown: str) -> str:
    """Append a single final unit-test section to body-only chapter markdown."""

    body = strip_existing_unit_test_sections(markdown)
    return body.rstrip() + "\n\n" + unit_test_markdown.strip() + "\n"


def _strip_body_generated_h3_recap_sections(markdown: str) -> str:
    return _H3_BODY_TEST_OR_RECAP_HEADING_RE.sub(
        lambda match: "" if _is_body_generated_test_or_recap_heading(match.group("title")) else match.group(0),
        markdown,
    )


def _extract_markdown_table(markdown: str, start: int) -> str:
    table_lines: list[str] = []
    for line in markdown[start:].splitlines():
        if table_lines and not line.lstrip().startswith("|"):
            break
        if line.lstrip().startswith("|"):
            table_lines.append(line.rstrip())
    return "\n".join(table_lines).strip() + "\n"


def _extract_unit_test_html_block(markdown: str, start: int) -> str:
    match = _UNIT_TEST_HTML_BLOCK_RE.search(markdown, start)
    return match.group(0).strip() + "\n" if match is not None else ""


def normalize_published_unit_test_sections(markdown: str) -> str:
    """Keep the published chapter to one standard final ``## 单元测试`` section."""

    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    matches = list(_BODY_TEST_OR_RECAP_HEADING_RE.finditer(text))
    kept_standard_start = -1
    for match in reversed(matches):
        if _is_standard_unit_test_heading(match.group("title")):
            kept_standard_start = match.start()
            break

    def replace_match(match: re.Match[str]) -> str:
        title = match.group("title")
        if match.start() == kept_standard_start:
            return match.group(0)
        if _is_body_generated_test_or_recap_heading(title):
            return ""
        return match.group(0)

    cleaned = _BODY_TEST_OR_RECAP_HEADING_RE.sub(replace_match, text)
    standard_matches = list(_STANDARD_UNIT_TEST_HEADING_RE.finditer(cleaned))
    if standard_matches:
        unit_start = standard_matches[-1].start()
        prefix = cleaned[:unit_start].rstrip()
        unit_block = cleaned[unit_start:]
        html_block = _extract_unit_test_html_block(cleaned, unit_start)
        table_match = _UNIT_TEST_TABLE_HEADER_RE.search(unit_block)
        if html_block:
            cleaned = prefix + "\n\n## 单元测试\n\n" + html_block
        elif table_match is not None:
            table_start = unit_start + table_match.start()
            table_block = _extract_markdown_table(cleaned, table_start)
            cleaned = prefix + "\n\n## 单元测试\n\n" + table_block
        else:
            cleaned = prefix + "\n\n" + unit_block.strip()
    else:
        html_block = _extract_unit_test_html_block(cleaned, 0)
        table_match = _UNIT_TEST_TABLE_HEADER_RE.search(cleaned)
        if html_block:
            prefix = _strip_body_generated_h3_recap_sections(cleaned[: cleaned.index(html_block.strip())])
            cleaned = prefix.rstrip() + "\n\n## 单元测试\n\n" + html_block
        elif table_match is not None:
            prefix = _strip_body_generated_h3_recap_sections(cleaned[: table_match.start()])
            table_block = _extract_markdown_table(cleaned, table_match.start())
            cleaned = prefix.rstrip() + "\n\n## 单元测试\n\n" + table_block
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"


__all__ = [
    "ChapterUnitTestGenerationError",
    "ChapterUnitTestItem",
    "ChapterUnitTestSet",
    "append_unit_test_markdown",
    "normalize_published_unit_test_sections",
    "render_unit_test_markdown",
    "strip_existing_unit_test_sections",
    "unit_test_structure_issues",
]
