import asyncio

from app.shared.infra.tools.builtin.latex_processing import normalize_math_delimiters, validate_latex
from app.shared.infra.tools.builtin.markdown_processing import (
    find_markdown_rendering_issues,
    normalize_markdown_rendering,
)
from app.workflows.digest.docgen.lib.models import ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.lib.public_markdown import sanitize_public_markdown
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
    assert "\n> [!TIP]\n>\n> 快速转换技巧" in fixed
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


def test_normalize_trims_inline_math_padding_inside_callout() -> None:
    raw = "> [!WARNING]\n> **易错点：误算为 $ 35 \\times 86 = 3010 $，再除以 10 得 301。**"

    fixed = normalize_markdown_rendering(raw)

    assert fixed.startswith("> [!WARNING]\n>\n> **易错点")
    assert "$35 \\times 86 = 3010$" in fixed
    assert "$ 35 \\times 86 = 3010 $" not in fixed


def test_normalize_ignores_dollars_inside_inline_code() -> None:
    raw = "\n".join(
        [
            "- `$P`：当前盘符",
            "- `$G`：大于号 `>`",
            "`PROMPT $P$G` 的输出结果是 `C>`。",
            "普通公式仍应修剪：$ 1 + 1 = 2 $。",
        ]
    )

    fixed = normalize_markdown_rendering(raw)

    assert "`$P`" in fixed
    assert "`$G`" in fixed
    assert "`PROMPT $P$G`" in fixed
    assert "`\\$P`" not in fixed
    assert "$1 + 1 = 2$" in fixed
    assert "存在未成对的单美元内联公式分隔符。" not in find_markdown_rendering_issues(fixed)


def test_latex_processing_ignores_dos_prompt_dollars_inside_inline_code() -> None:
    raw = "\n".join(
        [
            "- `$$`：显示 `$` 符号。",
            "- 示例：`PROMPT $P$G` 显示为 `C>`。",
            "普通块公式仍应保留：$$x + 1$$",
        ]
    )

    fixed = validate_latex(normalize_math_delimiters(raw))

    assert "- `$$`：显示 `$` 符号。" in fixed
    assert "`PROMPT $P$G`" in fixed
    assert "- `\n$$" not in fixed
    assert "$$\nx + 1\n$$" in fixed


def test_normalize_repairs_previous_inline_code_dollar_corruption() -> None:
    raw = "\n".join(
        [
            "### PROMPT 命令：提示符自定义",
            "- **常用参数**：",
            "  - `",
            "$$",
            "`：显示 `$` 符号。$",
            "$$",
            "- **示例**：",
            "$$",
            "```dos",
            "PROMPT $P$G",
            "```",
            "显示为 `C>`。",
            "[!TIP]",
            "记忆口诀：组合即得标准提示符。",
        ]
    )

    fixed = normalize_markdown_rendering(raw)

    assert "  - `$$`：显示 `$` 符号。" in fixed
    assert "- **示例**：\n```dos\nPROMPT $P$G\n```" in fixed
    assert "> [!TIP]\n>\n> 记忆口诀：组合即得标准提示符。" in fixed
    assert "> **自测例题**" not in fixed
    assert "display math 疑似吞入 Markdown 正文。" not in find_markdown_rendering_issues(fixed)
    assert "display math 分隔符数量不成对。" not in find_markdown_rendering_issues(fixed)
    assert "GitHub callout 未使用 blockquote 语法。" not in find_markdown_rendering_issues(fixed)


def test_public_markdown_hides_source_debug_and_post_reading_note() -> None:
    raw = "\n".join(
        [
            "# DOS 命令",
            "",
            "正文内容。",
            "",
            "读完《DOS 命令》后，可以把剩下的注意力收回到几个容易漏掉的连接点上。",
            "本章目标仍然是：掌握 DOS 命令。",
            "",
            "可以回看材料中的两条线索：",
            "- LLM 预选的本地资料切片",
            "- 来源切片：计算机基础.pdf / DOS (L1-L3)",
            "",
            "复习时优先检查这些点是否已经能用自己的话讲清：",
            "- **PROMPT**：掌握提示符格式。",
            "",
            "## 典型例题",
            "",
            "`PROMPT $P$G` 显示为 `C>`。",
            "",
            "## LLM 预选的本地资料切片",
            "",
            "### 来源切片：计算机基础.pdf / DOS (L1-L3)",
            "- 切片摘要：DOS 提示符。",
            "",
            "原文摘录：",
            "1 PROMPT $P$G",
            "",
            "## 参考资料与延伸阅读",
            "",
            "- 计算机基础.pdf (docgen_source_slice)",
        ]
    )

    fixed = sanitize_public_markdown(normalize_markdown_rendering(raw))

    assert "读完《" not in fixed
    assert "LLM 预选" not in fixed
    assert "来源切片" not in fixed
    assert "参考资料与延伸阅读" not in fixed
    assert "计算机基础.pdf" not in fixed
    assert "## 典型例题" in fixed
    assert "`PROMPT $P$G`" in fixed


def test_public_markdown_hides_legacy_mermaid_placeholder() -> None:
    raw = "# 函数\n\n<!-- [MERMAID: 函数的整体知识脉络图] -->\n\n正文。"

    fixed = sanitize_public_markdown(raw)

    assert "MERMAID:" not in fixed
    assert "<!--" not in fixed
    assert "正文。" in fixed


def test_normalize_keeps_github_callout_marker_as_separate_quote_paragraph() -> None:
    raw = "\n".join(
        [
            "> [!IMPORTANT]",
            "> 从方程到函数的转化，本质是从点态求解转向整体建模。",
            "",
            "> [!WARNING] 不要把无实数根误判为无解。",
        ]
    )

    fixed = normalize_markdown_rendering(raw)

    assert "> [!IMPORTANT]\n>\n> 从方程到函数的转化" in fixed
    assert "> [!WARNING]\n>\n> 不要把无实数根误判为无解。" in fixed


def test_normalize_keeps_loose_display_math_inside_callout() -> None:
    raw = "\n".join(
        [
            "> [!IMPORTANT]",
            ">",
            "> 浮点数标准形式为：",
            "$$",
            "(-1)^S \\times M \\times 2^E",
            "$$",
            "> 其中 $S$ 为符号位，$M$ 为尾数，$E$ 为阶码。",
        ]
    )

    fixed = normalize_markdown_rendering(raw)

    assert "> [!IMPORTANT]\n>\n> 浮点数标准形式为：" in fixed
    assert "> $$\n> (-1)^S \\times M \\times 2^E\n> $$" in fixed
    assert "> 其中 $S$ 为符号位，$M$ 为尾数，$E$ 为阶码。" in fixed
    assert "display math 内混入 blockquote 前缀。" not in find_markdown_rendering_issues(fixed)


def test_normalize_flattens_headings_inside_list_items() -> None:
    raw = "- # 数与代数：从运算到表达式的思维跃迁\n1. ### 章节复盘"

    fixed = normalize_markdown_rendering(raw)

    assert "- 数与代数：从运算到表达式的思维跃迁" in fixed
    assert "1. 章节复盘" in fixed
    assert "- #" not in fixed
    assert "1. ###" not in fixed


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
    assert "\n> [!WARNING]\n>\n> 不要把提示块写成裸标记" in repaired[0].markdown
