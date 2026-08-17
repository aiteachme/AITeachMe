from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.shared.infra.execution import TracedExecutionContext
from app.workflows.digest.docgen.lib import chapter_enhancement
from app.workflows.digest.docgen.lib.asset_rendering import MermaidSkipped, _sanitize_mermaid_body
from app.workflows.digest.docgen.lib.asset_requests import strip_asset_requests
from app.workflows.digest.docgen.lib.models import ChapterDraft
from app.workflows.digest.docgen.lib.presentation_policy import (
    find_docgen_presentation_issues,
    normalize_docgen_presentation,
)


def test_docgen_presentation_escapes_inline_code_pipes_in_tables() -> None:
    raw = (
        "# 运算符\n\n"
        "| 类别 | 运算符 | 说明 |\n"
        "|---|---|---|\n"
        "| 逻辑 | `&& || !` | 与、或、非 |\n"
    )

    fixed = normalize_docgen_presentation(raw)

    assert "`&& \\|\\| !`" in fixed
    assert "Markdown 表格行列数不一致。" not in find_docgen_presentation_issues(fixed)


def test_docgen_presentation_ignores_equality_operators_inside_code() -> None:
    markdown = (
        "# 指针与数组\n\n"
        "此时 `p == &a[0]`，并且 `a[i] == *(p+i)`。\n\n"
        "```c\nif (x == 0) return;\n```\n"
    )

    assert "Markdown 高亮标记 == 未成对闭合。" not in find_docgen_presentation_issues(markdown)


def test_docgen_presentation_keeps_real_unpaired_highlight_visible() -> None:
    markdown = "# 标题\n\n这里有一个 ==未闭合重点。\n"

    assert "Markdown 高亮标记 == 未成对闭合。" in find_docgen_presentation_issues(markdown)


def test_docgen_presentation_deduplicates_question_and_answer_as_one_block() -> None:
    exercise = (
        "> [!QUESTION] **练习 1**\n>\n> 计算 $1+1$。\n\n"
        "> [!ANSWER]\n>\n> **答案**\n>\n> 2。\n>\n"
        "> **解析步骤**\n>\n> 由加法定义可得 2。"
    )
    markdown = f"# 加法\n\n## 练习\n\n{exercise}\n\n{exercise}\n"

    fixed = normalize_docgen_presentation(markdown)

    assert fixed.count("[!QUESTION]") == 1
    assert fixed.count("[!ANSWER]") == 1
    assert fixed.count("由加法定义可得 2。") == 1


def test_docgen_presentation_preserves_conflicting_answers_for_review() -> None:
    question = "> [!QUESTION] **练习 1**\n>\n> 计算 $1+1$。"
    first = f"{question}\n\n> [!ANSWER]\n>\n> **答案**\n>\n> 2。"
    second = f"{question}\n\n> [!ANSWER]\n>\n> **答案**\n>\n> 3。"

    fixed = normalize_docgen_presentation(f"# 加法\n\n{first}\n\n{second}\n")

    assert fixed.count("[!QUESTION]") == 2
    assert fixed.count("[!ANSWER]") == 2
    assert "> 2。" in fixed
    assert "> 3。" in fixed


def test_docgen_presentation_ignores_html_like_syntax_inside_code() -> None:
    markdown = (
        "# C 语言头文件\n\n"
        "行内写法是 `#include <stdio.h>`。\n\n"
        "```c\n#include <stdio.h>\nint main(void) { return 0; }\n```\n"
    )

    assert "Markdown 正文包含不受控 HTML 标签。" not in find_docgen_presentation_issues(markdown)
    assert "Markdown 正文包含不受控 HTML 标签。" in find_docgen_presentation_issues(
        markdown + "\n<section>正文 HTML</section>\n"
    )


def test_docgen_presentation_ignores_comparison_syntax_across_inline_math() -> None:
    markdown = (
        "# 左右极限\n\n"
        "左极限只考察 $x<a$ 的点，右极限只考察 $x>a$ 的点。\n"
    )

    assert "Markdown 正文包含不受控 HTML 标签。" not in find_docgen_presentation_issues(markdown)


def test_empty_mermaid_response_is_treated_as_skip() -> None:
    with pytest.raises(MermaidSkipped):
        _sanitize_mermaid_body("", topic="formula expansion")


def test_chapter_enhancement_preserves_mermaid_after_blockquote_code_fence(monkeypatch) -> None:
    class FakeAssetRuntime:
        def __init__(self, _context) -> None:
            pass

        async def process_mermaid_placeholders_with_reports(self, markdown: str):
            body = strip_asset_requests(markdown).rstrip()
            return (
                body + "\n\n```mermaid\nflowchart TD\n  A[条件] --> B[执行]\n```\n",
                [{"status": "rendered"}],
            )

    monkeypatch.setattr(chapter_enhancement, "DocGenAssetRuntime", FakeAssetRuntime)
    monkeypatch.setattr(
        chapter_enhancement,
        "get_settings",
        lambda: SimpleNamespace(docgen=SimpleNamespace(generate_interactive_html=False)),
    )
    draft = ChapterDraft(
        chapter_index=2,
        title="流程控制",
        markdown=(
            "# 流程控制\n\n## 条件分支\n\n"
            "> [!EXAMPLE]\n> ```c\n> int x = 1;\n> ```\n"
        ),
        placeholder_requests=[{"kind": "mermaid", "description": "条件分支执行流程"}],
    )

    enhanced, _assets, _practice = asyncio.run(
        chapter_enhancement.enhance_chapter_draft(
            draft,
            traced_context=TracedExecutionContext(course_id="course_test", build_session_id="build_test"),
            digest_mode="sprint",
        )
    )

    assert "```mermaid\nflowchart TD" in enhanced.markdown
    assert enhanced.markdown.count("```") % 2 == 0
    assert "```text\nflowchart TD" not in enhanced.markdown


def test_chapter_enhancement_preserves_math_code_and_callouts(monkeypatch) -> None:
    class FakeAssetRuntime:
        def __init__(self, _context) -> None:
            pass

    monkeypatch.setattr(chapter_enhancement, "DocGenAssetRuntime", FakeAssetRuntime)
    monkeypatch.setattr(
        chapter_enhancement,
        "get_settings",
        lambda: SimpleNamespace(docgen=SimpleNamespace(generate_interactive_html=False)),
    )
    draft = ChapterDraft(
        chapter_index=2,
        title="流程控制",
        markdown=(
            "# 流程控制\n\n## 分段函数\n\n"
            "\\[\n"
            "y=\\begin{cases}\n"
            "x+1,&x<0\\\\\n"
            "2x,&x\\ge 0\n"
            "\\end{cases}\n"
            "\\]\n\n"
            "```c\n#include <stdio.h>\nif (x < 0) y = x + 1;\n```\n\n"
            "> [!TIP]\n>\n> 先判断区间边界。\n"
        ),
    )

    enhanced, _assets, _practice = asyncio.run(
        chapter_enhancement.enhance_chapter_draft(
            draft,
            traced_context=TracedExecutionContext(course_id="course_test", build_session_id="build_test"),
            digest_mode="sprint",
        )
    )

    assert r"\begin{cases}" in enhanced.markdown
    assert r"\end{cases}" in enhanced.markdown
    assert "```c\n#include <stdio.h>" in enhanced.markdown
    assert "```text" not in enhanced.markdown
    assert "> [!TIP]" in enhanced.markdown
    assert find_docgen_presentation_issues(enhanced.markdown) == []
