import asyncio

from app.shared.infra.tools.builtin.markdown_processing import (
    find_markdown_rendering_issues,
    normalize_markdown_rendering,
)
from app.workflows.digest.docgen.lib.models import ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.lib.repair import repair_or_route_review_actions


def test_normalize_closes_display_math_before_markdown_and_callout() -> None:
    raw = "\n".join(
        [
            "$$",
            "1110111.11_2 = 1 \\times 2^6 + 1 \\times 2^5",
            "= 64 + 32 = 96_{10}",
            "- **十进制 -> 二进制**：分整数与小数部分处理",
            "[!TIP] 快速转换技巧",
        ]
    )

    issues = find_markdown_rendering_issues(raw)
    assert "display math 分隔符数量不成对。" in issues
    assert "display math 疑似吞入 Markdown 正文。" in issues
    assert "GitHub callout 未使用 blockquote 语法。" in issues

    fixed = normalize_markdown_rendering(raw)

    assert "\n$$\n- **十进制 -> 二进制**" in fixed
    assert "\n> [!TIP]\n> 快速转换技巧" in fixed
    assert "display math 疑似吞入 Markdown 正文。" not in find_markdown_rendering_issues(fixed)
    assert "GitHub callout 未使用 blockquote 语法。" not in find_markdown_rendering_issues(fixed)


def test_normalize_escapes_inline_math_that_swallows_markdown() -> None:
    raw = "$- **十进制 -> 二进制**：`1110111` ### 高级题型$"

    issues = find_markdown_rendering_issues(raw)
    assert "内联公式疑似吞入 Markdown 正文。" in issues

    fixed = normalize_markdown_rendering(raw)

    assert fixed.startswith(r"\$- **十进制 -> 二进制**")
    assert fixed.rstrip().endswith(r"\$")
    assert "内联公式疑似吞入 Markdown 正文。" not in find_markdown_rendering_issues(fixed)


def test_review_surface_patch_applies_deterministic_markdown_repair() -> None:
    raw = "\n".join(
        [
            "$$",
            "x = 1",
            "- **错误吞入的列表**：应回到正文",
            "[!WARNING] 不要把提示块写成裸标记",
        ]
    )
    chapter = ReviewedChapterDraft(chapter_index=1, title="测试章节", markdown=raw)
    action = ReviewAction(
        action_id="review_ch01_surface_rendering",
        action_type="surface_patch",
        chapter_index=1,
        reason="Markdown 渲染结构异常：display math 疑似吞入 Markdown 正文。",
        target_anchor="测试章节",
    )

    repaired, actions, unresolved, trace = asyncio.run(
        repair_or_route_review_actions(
            reviewed_chapters=[chapter],
            review_actions=[action],
        )
    )

    assert not unresolved
    assert actions[0].status == "applied"
    assert trace[0].changed is True
    assert "\n$$\n- **错误吞入的列表**" in repaired[0].markdown
    assert "\n> [!WARNING]\n> 不要把提示块写成裸标记" in repaired[0].markdown
