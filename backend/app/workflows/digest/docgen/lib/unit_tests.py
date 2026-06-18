"""Chapter-end unit test generation and rendering."""

from __future__ import annotations

import re
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.shared.infra.llm_support import acompletion_with_fallback
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.lib.models import (
    ChapterDraft,
    ChapterGenerationTask,
    DocGenBaseModel,
    clean_string_list,
    clean_text,
)
from app.workflows.digest.docgen.prompts.chapter_unit_tests import build_chapter_unit_test_messages


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
_CHOICE_FALLBACK_OPTIONS = ["条件成立", "条件缺失", "只适合特例", "无法判断"]
_MATH_SPAN_RE = re.compile(r"(\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])")
_RAW_LATEX_FRAGMENT_RE = re.compile(
    r"(?<![$\\])"
    r"(?P<formula>"
    r"(?:[A-Za-z0-9_+\-*/=<>≤≥^{}()[\],. ]|\\[A-Za-z]+|\\[{}])+"
    r"\\(?:sqrt|frac|lim|sin|cos|tan|cot|ln|log|sum|int|Delta|delta|epsilon|varepsilon|theta|pi|infty|cdot|times|leq|geq|neq|to|sim)"
    r"(?:[A-Za-z0-9_+\-*/=<>≤≥^{}()[\],. ]|\\[A-Za-z]+|\\[{}])*"
    r")"
    r"(?![$])"
)


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
        text = clean_text(item)
        match = _CHOICE_LABEL_RE.match(text)
        if match:
            text = match.group("text").strip()
        if not text:
            continue
        if len(text) > 28:
            text = text[:27].rstrip(" ，,。；;、") + "…"
        key = _compact_label(text)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= 4:
            break
    for fallback in _CHOICE_FALLBACK_OPTIONS:
        if len(cleaned) >= 4:
            break
        key = _compact_label(fallback)
        if key not in seen:
            cleaned.append(fallback)
            seen.add(key)
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
    def _fallback_fields(self) -> "ChapterUnitTestItem":
        self.type = _normalize_question_type(self.type)
        self.difficulty = _normalize_difficulty(self.difficulty)
        self.options = _normalize_choice_options(self.options)
        if not self.target:
            self.target = "本章要点"
        if not self.stem:
            self.stem = f"说明“{self.target}”的关键判断。"
        if not self.answer:
            self.answer = "见本章对应知识点。"
        if not self.basis:
            self.basis = "能说清条件、步骤和结论即可。"
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
    text = " ".join(str(value or "").strip().split())
    if limit is not None and len(text) > limit:
        text = text[: max(1, limit - 1)].rstrip(" ，,。；;、") + "…"
    return _wrap_raw_latex_fragments(text)


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


def _ordered_unique(values: list[str], order: list[str]) -> list[str]:
    order_index = {value: index for index, value in enumerate(order)}
    return sorted(set(values), key=lambda value: (order_index.get(value, 999), value))


def _minimum_question_type_count(item_count: int) -> int:
    if item_count <= 1:
        return 1
    if item_count <= 3:
        return item_count
    if item_count <= 5:
        return 4
    if item_count <= 8:
        return 5
    return 6


def _type_counts(items: list[ChapterUnitTestItem]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        question_type = _normalize_question_type(item.type)
        counts[question_type] = counts.get(question_type, 0) + 1
    return counts


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
    prepared = _dedupe_unit_test_items(list(items or []))[:limit]
    if len(prepared) < min_items:
        prepared.extend(_fallback_items(title=title, targets=fallback_targets, count=min_items - len(prepared)))
    prepared = prepared[:limit]

    required_type_count = min(_minimum_question_type_count(len(prepared)), limit)
    counts = _type_counts(prepared)
    if len(counts) >= required_type_count:
        return prepared

    fallback_pool = _fallback_items(
        title=title,
        targets=fallback_targets or [item.target for item in prepared if item.target],
        count=len(_QUESTION_TYPE_ORDER),
    )
    for candidate in fallback_pool:
        question_type = _normalize_question_type(candidate.type)
        if question_type in counts:
            continue
        if len(prepared) < limit:
            prepared.append(candidate)
        else:
            counts = _type_counts(prepared)
            replace_index = next(
                (
                    index
                    for index in range(len(prepared) - 1, -1, -1)
                    if counts.get(_normalize_question_type(prepared[index].type), 0) > 1
                ),
                -1,
            )
            if replace_index < 0:
                break
            prepared[replace_index] = candidate
        counts = _type_counts(prepared)
        if len(counts) >= required_type_count:
            break
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
            "> [!PRACTICE]",
            f"> **{len(items)} 题覆盖**：{coverage_text or '本章核心考点'}",
            f"> **题型与难度**：{type_text}；{difficulty_text}",
        ]
    )


def _render_unit_test_item_markdown(item: ChapterUnitTestItem, *, index: int) -> str:
    question_type = _normalize_question_type(item.type)
    difficulty = _normalize_difficulty(item.difficulty)
    lines = [
        f"> [!PRACTICE] **Q{index:02d}｜{question_type}｜{difficulty}｜考点：{_markdown_text(item.target, limit=36)}**",
        ">",
        f"> {_markdown_text(item.stem, limit=420)}",
    ]
    lines.extend([">", "> **选项**"])
    lines.extend([f"> - {label}. {_markdown_text(option, limit=42)}" for label, option in zip("ABCD", item.options)])
    lines.extend(
        [
            ">",
            f"> **答案与依据**：{_markdown_text(item.answer, limit=360)}",
            f"> **判定依据**：{_markdown_text(item.basis, limit=360)}",
        ]
    )
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


async def generate_chapter_unit_tests(
    *,
    draft: ChapterDraft,
    task: ChapterGenerationTask | None,
    digest_mode: str,
    min_items: int,
    max_items: int,
    trace_metadata: dict[str, object] | None = None,
) -> ChapterUnitTestSet:
    """Generate structured unit tests for one chapter with local fallback."""

    task = task or ChapterGenerationTask(chapter_index=draft.chapter_index, confirmed_title=draft.title)
    required_elements = _task_targets(task)
    chapter_end_practice_plan = list((task.practice_seed_policy or {}).get("chapter_end_practice_plan") or task.chapter_end_practice_plan or [])
    messages = build_chapter_unit_test_messages(
        chapter_title=draft.title,
        digest_mode=digest_mode,
        required_elements=required_elements,
        chapter_end_practice_plan=chapter_end_practice_plan,
        markdown=strip_existing_unit_test_sections(draft.markdown),
        min_items=min_items,
        max_items=max_items,
    )
    try:
        response = await acompletion_with_fallback(
            messages,
            response_model=ChapterUnitTestSet,
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.UNIT_TESTS,
                digest_mode=digest_mode,
                extra_metadata=trace_metadata or {},
                chapter_index=draft.chapter_index,
                substep="chapter_unit_tests",
            ),
        )
        result = response if isinstance(response, ChapterUnitTestSet) else ChapterUnitTestSet.model_validate(response)
    except Exception:
        result = ChapterUnitTestSet(chapter_index=draft.chapter_index)
    result.chapter_index = draft.chapter_index
    if not result.items:
        result.items = _fallback_items(title=draft.title, targets=required_elements, count=min_items)
    result.items = _prepare_unit_test_items(
        result.items,
        title=draft.title,
        min_items=min_items,
        max_items=max_items,
        fallback_targets=required_elements,
    )
    return result


def _task_targets(task: ChapterGenerationTask) -> list[str]:
    return clean_string_list(
        [
            *task.content_points,
            *task.concept_targets,
            *task.definition_targets,
            *task.formula_targets,
            *task.example_targets,
            *task.pitfall_targets,
            *task.required_elements,
        ],
        limit=12,
    )


def _fallback_items(*, title: str, targets: list[str], count: int) -> list[ChapterUnitTestItem]:
    targets = clean_string_list(targets, limit=max(1, count)) or [title or "本章核心内容"]
    items: list[ChapterUnitTestItem] = []
    templates = [
        ("概念判断", "基础", "关于“{target}”的关键判断，哪一项正确？", "能对应本章定义、对象、条件和结论。"),
        ("选择题", "基础", "关于“{target}”，哪一项最符合本章结论？", "应选择符合本章定义、条件或结论的选项。"),
        ("填空题", "基础", "补全“{target}”的关键条件，哪一项最合适？", "答案应补到本章强调的核心条件、步骤或表达式。"),
        ("步骤排序", "进阶", "解决“{target}”时，哪一种步骤顺序更合理？", "顺序应先检查条件，再执行方法，最后验证结论。"),
        ("错因辨析", "进阶", "学习“{target}”时，哪一项最可能是错误原因？", "能识别限制条件、常见错因或反例。"),
        ("应用迁移", "挑战", "把“{target}”换到新情境时，第一步应做什么？", "先判断适用条件，再选择本章方法迁移。"),
        ("短答题", "进阶", "哪一句最能解释“{target}”的作用？", "回答要包含原因、方法和结论。"),
        ("图表读取", "进阶", "如果“{target}”出现在图表中，应优先确认哪项？", "应能定位关键量、关系或边界条件。"),
        ("推导证明", "挑战", "推导“{target}”时，哪个入口最稳妥？", "推导应从已知条件出发，连接到本章结论。"),
    ]
    for index in range(max(1, count)):
        target = targets[index % len(targets)]
        item_type, difficulty, stem_template, basis = templates[index % len(templates)]
        options = _fallback_options_for_type(item_type, target)
        items.append(
            ChapterUnitTestItem(
                type=item_type,
                difficulty=difficulty,
                target=target,
                stem=stem_template.format(target=target),
                options=options,
                answer=f"A. {options[0]}",
                basis=basis,
            )
        )
    return items


def _fallback_options_for_type(item_type: str, target: str) -> list[str]:
    if item_type == "步骤排序":
        return _normalize_choice_options(
            [
                "先判条件，再选方法，最后验结论",
                "先套公式，再补条件，最后猜结论",
                "先看答案，再反推题目条件",
                "只写结论，省略判断过程",
            ]
        )
    if item_type == "错因辨析":
        return _normalize_choice_options(
            [
                "忽略适用条件或边界",
                "把定义直接当作结论",
                "只替换数字不看结构",
                "把无关信息当主线",
            ]
        )
    if item_type == "应用迁移":
        return _normalize_choice_options(
            [
                f"先判断“{target}”是否仍适用",
                "直接照抄原题答案",
                "只换符号不检查条件",
                "跳过模型或关系确认",
            ]
        )
    if item_type == "图表读取":
        return _normalize_choice_options(
            [
                "先读关键量、关系和边界",
                "先看图形颜色和装饰",
                "只读标题不看条件",
                "跳过比例、单位或方向",
            ]
        )
    if item_type == "推导证明":
        return _normalize_choice_options(
            [
                "从已知条件连接核心结论",
                "先写结论再补理由",
                "只列公式不说明条件",
                "用无关定理替代推导",
            ]
        )
    if item_type == "填空题":
        return _normalize_choice_options(
            [
                f"补全“{target}”的必要条件",
                "只补最终答案",
                "补无关记忆点",
                "省略限制范围",
            ]
        )
    if item_type == "短答题":
        return _normalize_choice_options(
            [
                f"说明“{target}”如何连接条件与结论",
                "只复述题干关键词",
                "只给结果不讲原因",
                "讲无关背景信息",
            ]
        )
    return _normalize_choice_options(
        [
            f"{target}的定义和适用条件要同时满足",
            "只记结论即可，不必看条件",
            "任意情境都能直接套用",
            "与本章方法没有关系",
        ]
    )


__all__ = [
    "ChapterUnitTestItem",
    "ChapterUnitTestSet",
    "append_unit_test_markdown",
    "generate_chapter_unit_tests",
    "normalize_published_unit_test_sections",
    "render_unit_test_markdown",
    "strip_existing_unit_test_sections",
]
