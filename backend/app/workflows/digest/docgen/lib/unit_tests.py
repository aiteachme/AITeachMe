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
_STANDARD_UNIT_TEST_HEADING_RE = re.compile(r"(?m)^##\s+单元测试\s*$")
_H3_BODY_TEST_OR_RECAP_HEADING_RE = re.compile(r"(?ms)^###\s+(?P<title>[^\n]+?)\s*\n.*?(?=^#{2,3}\s+|\Z)")


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
    """One compact item for the rendered chapter-end unit test table."""

    type: str = "短答"
    target: str = ""
    stem: str = ""
    answer: str = ""
    basis: str = ""

    @field_validator("type", "target", "stem", "answer", "basis", mode="before")
    @classmethod
    def _text(cls, value: Any) -> str:
        return clean_text(value)

    @model_validator(mode="after")
    def _fallback_fields(self) -> "ChapterUnitTestItem":
        if not self.type:
            self.type = "短答"
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


def _markdown_cell(value: str, *, limit: int = 120) -> str:
    text = " ".join(str(value or "").strip().split())
    text = text.replace("|", " / ").replace("\n", " ")
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "..."
    return text


def render_unit_test_markdown(
    result: ChapterUnitTestSet,
    *,
    title: str,
    min_items: int,
    fallback_targets: list[str],
) -> str:
    """Render unit tests as a compact Markdown table instead of heading spam."""

    items = list(result.items or [])
    if len(items) < min_items:
        items.extend(_fallback_items(title=title, targets=fallback_targets, count=min_items - len(items)))
    items = items[: max(min_items, len(items))]
    lines = [
        "## 单元测试",
        "",
        "| 题号 | 训练点 | 题目 / 任务 | 答案与判定依据 |",
        "| --- | --- | --- | --- |",
    ]
    for index, item in enumerate(items, start=1):
        answer = item.answer
        if item.basis and item.basis not in answer:
            answer = f"{answer}；依据：{item.basis}"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _markdown_cell(item.target, limit=32),
                    _markdown_cell(item.stem, limit=120),
                    _markdown_cell(answer, limit=140),
                ]
            )
            + " |"
        )
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
        table_match = _UNIT_TEST_TABLE_HEADER_RE.search(unit_block)
        if table_match is not None:
            table_start = unit_start + table_match.start()
            table_block = _extract_markdown_table(cleaned, table_start)
            cleaned = prefix + "\n\n## 单元测试\n\n" + table_block
        else:
            cleaned = prefix + "\n\n" + unit_block.strip()
    else:
        table_match = _UNIT_TEST_TABLE_HEADER_RE.search(cleaned)
        if table_match is not None:
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
        ("概念判断", "用一句话说明“{target}”的核心含义。", "能说清对象、条件和结论。"),
        ("方法应用", "给出“{target}”的一步关键处理方法。", "步骤要与本章讲解一致。"),
        ("易错辨析", "指出学习“{target}”时最容易忽略的限制。", "能写出限制条件或反例即可。"),
        ("迁移检查", "把“{target}”换到一个新例子中，应先检查什么？", "先检查适用条件，再执行方法。"),
    ]
    for index in range(max(1, count)):
        target = targets[index % len(targets)]
        item_type, stem_template, basis = templates[index % len(templates)]
        items.append(
            ChapterUnitTestItem(
                type=item_type,
                target=target,
                stem=stem_template.format(target=target),
                answer=f"围绕“{target}”按本章定义、条件和步骤作答。",
                basis=basis,
            )
        )
    return items


__all__ = [
    "ChapterUnitTestItem",
    "ChapterUnitTestSet",
    "append_unit_test_markdown",
    "generate_chapter_unit_tests",
    "normalize_published_unit_test_sections",
    "render_unit_test_markdown",
    "strip_existing_unit_test_sections",
]
