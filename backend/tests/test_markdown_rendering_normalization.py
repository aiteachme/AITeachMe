import asyncio

from app.shared.infra.tools.builtin.latex_processing import normalize_math_delimiters, validate_latex
from app.shared.infra.tools.builtin.markdown_processing import (
    find_markdown_presentation_issues,
    find_markdown_rendering_issues,
    normalize_markdown_rendering,
    normalize_mermaid_blocks,
    summarize_markdown_presentation,
    validate_single_file_html,
)
from app.workflows.digest.docgen.lib.html_sidecar import normalize_single_file_html
from app.workflows.digest.docgen.lib.models import ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.lib.public_markdown import sanitize_public_markdown
from app.workflows.digest.docgen.lib.repair import repair_or_route_review_actions
from app.workflows.digest.docgen.lib.textbook_style import (
    clean_heading_focus,
    normalize_educational_callouts,
    normalize_textbook_headings,
)


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


def test_display_math_absolute_value_pipes_do_not_trigger_table_boundary() -> None:
    raw = "\n".join(
        [
            "$$",
            r"|PA| = \sqrt{|PC|^2 - r^2} = \sqrt{25 - 9} = 4",
            "$$",
            "",
            "## 下一节",
        ]
    )

    fixed = normalize_markdown_rendering(raw)

    assert r"|PA| = \sqrt{|PC|^2 - r^2}" in fixed
    assert "$$\n## 下一节" not in fixed
    issues = find_markdown_rendering_issues(fixed)
    assert "display math 分隔符数量不成对。" not in issues
    assert "display math 疑似吞入 Markdown 正文。" not in issues


def test_blockquote_after_closed_display_math_is_valid() -> None:
    raw = "\n".join(
        [
            "$$",
            r"P(\text{红桃}) = \frac{13}{52} = \frac{1}{4}",
            "$$",
            "> 答案：$\\frac{1}{4}$。",
        ]
    )

    assert "display math 内混入 blockquote 前缀。" not in find_markdown_rendering_issues(raw)


def test_normalize_drops_orphan_display_math_before_markdown_blocks() -> None:
    raw = "\n".join(
        [
            "正文",
            "",
            "$$",
            "## 高频考点总结与易错边界",
            "| 考点类别 | 推荐策略 |",
            "| --- | --- |",
            r"| 弦长计算 | 几何法优先：$ |AB|=2\sqrt{r^2-d^2} $ |",
            "",
            "> $$",
            "```mermaid",
            "flowchart LR",
            "A --> B",
            "```",
        ]
    )

    fixed = normalize_markdown_rendering(raw)

    assert "$$\n## 高频考点总结与易错边界" not in fixed
    assert "> $$\n```mermaid" not in fixed
    assert "## 高频考点总结与易错边界" in fixed
    assert r"$\lvert AB\rvert=2\sqrt{r^2-d^2}$" in fixed
    issues = find_markdown_rendering_issues(fixed)
    assert "display math 分隔符数量不成对。" not in issues
    assert "display math 疑似吞入 Markdown 正文。" not in issues


def test_generated_chapter_math_and_table_snippets_normalize_cleanly() -> None:
    chapter_02_snippet = "\n".join(
        [
            "### 综合应用：构造直角三角形求解",
            "",
            "$$",
            r"|PA| = \sqrt{|PC|^2 - r^2} = \sqrt{25 - 9} = \sqrt{16} = 4",
            "$$",
            "",
            "---",
            "",
            "$$",
            "## 高频考点总结与易错边界",
            "| 考点类别 | 高频题型 | 易错边界 | 推荐策略 |",
            "| --- | --- | --- | --- |",
            r"| 弦长计算 | 已知直线与圆，求弦长 | 忘记 $d \leq r$ | 几何法优先：$ |AB|=2\sqrt{r^2-d^2} $ |",
            "```mermaid",
            "flowchart LR",
            "A[图形与几何] --> B[圆]",
            "```",
        ]
    )
    chapter_04_snippet = "\n".join(
        [
            "$$",
            r"|A \cup B| = |A| + |B| - |A \cap B|",
            "$$",
            "",
            "$$",
            "## 常见应用问题类型",
            "| 类型 | 策略 |",
            "| --- | --- |",
            "| 集合计数 | 先画图再代数化 |",
        ]
    )

    for raw in (chapter_02_snippet, chapter_04_snippet):
        fixed = normalize_markdown_rendering(raw)
        issues = find_markdown_rendering_issues(fixed)
        assert "display math 分隔符数量不成对。" not in issues
        assert "display math 疑似吞入 Markdown 正文。" not in issues


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


def test_normalize_restores_overescaped_long_inline_math() -> None:
    raw = (
        r"- 计算：\$b = \lim_{x \to \infty}(f(x)-x)"
        r" = \lim_{x \to \infty}\left(\frac{x^2+1}{x-1}-x\right)"
        r" = \lim_{x \to \infty}\frac{x^2+1-x(x-1)}{x-1}"
        r" = \lim_{x \to \infty}\frac{x+1}{x-1}=1\$，所以斜渐近线为 $y=x+1$。"
    )

    fixed = normalize_markdown_rendering(raw)

    assert r"\$b =" not in fixed
    assert r"$b = \lim_{x \to \infty}" in fixed
    assert r"$y=x+1$" in fixed
    assert "内联公式疑似吞入 Markdown 正文。" not in find_markdown_rendering_issues(fixed)


def test_normalize_mermaid_quotes_flowchart_labels_with_comparison_symbols() -> None:
    raw = "\n".join(
        [
            "```mermaid",
            "flowchart LR",
            "A[导数应用] --> B1[一阶导数正负]",
            "B1 --> B2[递增: f'(x) > 0]",
            "B1 -->|f'(x) < 0| B3[递减]",
            "classDef core fill:#f9f,stroke:#333,stroke-width:1px;",
            "class A,B1 core",
            "```",
        ]
    )

    fixed = normalize_mermaid_blocks(raw)

    assert 'A["导数应用"] --> B1["一阶导数正负"]' in fixed
    assert 'B1 --> B2["递增: f\'(x) 大于 0"]' in fixed
    assert "B1 -->|f'(x) 小于 0| B3[\"递减\"]" in fixed
    assert "classDef core fill:#f9f,stroke:#333,stroke-width:1px;" in fixed


def test_normalize_mermaid_wraps_plain_flowchart_lines_with_hex_values() -> None:
    raw = "\n".join(
        [
            "```mermaid",
            "flowchart TB PC: 0xFFFF0 → 0x00000",
            "A[入口] --> B[执行]",
            "```",
        ]
    )

    fixed = normalize_mermaid_blocks(raw)

    assert "flowchart TB" in fixed
    assert '["PC: 0xFFFF0 → 0x00000"]' in fixed
    assert 'A["入口"] --> B["执行"]' in fixed


def test_normalize_mermaid_compacts_class_node_lists() -> None:
    raw = "\n".join(
        [
            "```mermaid",
            "flowchart TB",
            "C[概念] --> D[方法]",
            "G[练习]",
            "classDef method fill:#eef,stroke:#88f;",
            "class C, D, G method",
            "```",
        ]
    )

    fixed = normalize_mermaid_blocks(raw)

    assert "class C,D,G method" in fixed
    assert "class C, D, G method" not in fixed
    assert "classDef method fill:#eef,stroke:#88f;" in fixed


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


def test_normalize_splits_adjacent_quoted_callouts_without_blank_line() -> None:
    raw = "\n".join(
        [
            "> [!WARNING]",
            ">",
            "> ⚠️ 易错边界：忽视字母的取值范围。",
            "> 例如，十位数字不能为 0。",
            "> [!NOTE]",
            ">",
            "> 🔗 本章定位：这是代数思维的起点。",
        ]
    )

    fixed = normalize_markdown_rendering(raw)

    assert "> 例如，十位数字不能为 0。\n\n> [!NOTE]" in fixed
    assert "> [!NOTE]\n>\n> 🔗 本章定位：这是代数思维的起点。" in fixed


def test_textbook_style_promotes_educational_emoji_quotes_to_callouts() -> None:
    raw = "\n".join(
        [
            "> 💡 **速判技巧**：看到平方差就先想共轭或因式分解。",
            "",
            "> ✅ **高频考点**：先抓题目条件，再选公式。",
            "",
            "> ⚠️ **易错点**：不要把定义域限制漏掉。",
            "",
            "> ✅ **答案**：5",
            "",
            "> 这是一段普通引用，后面会提醒注意事项。",
            "",
            "> 普通引用不应变化。",
        ]
    )

    fixed = normalize_educational_callouts(raw)

    assert "> [!TIP]\n>\n> **速判技巧**：看到平方差就先想共轭或因式分解。" in fixed
    assert "> [!IMPORTANT]\n>\n> **高频考点**：先抓题目条件，再选公式。" in fixed
    assert "> [!WARNING]\n>\n> **易错点**：不要把定义域限制漏掉。" in fixed
    assert "> ✅ **答案**：5" in fixed
    assert "> [!IMPORTANT]\n>\n> ✅ **答案**：5" not in fixed
    assert "> 这是一段普通引用，后面会提醒注意事项。" in fixed
    assert "> [!WARNING]\n>\n> 这是一段普通引用" not in fixed
    assert "> 普通引用不应变化。" in fixed


def test_textbook_headings_remove_generic_untitled_example_prefix() -> None:
    raw = "\n".join(
        [
            "# 未命名章节",
            "",
            "### 未命名章节的典型例题解析",
            "",
            "正文。",
        ]
    )

    fixed = normalize_textbook_headings(
        raw,
        digest_mode="sprint",
        fallback_title="未命名章节",
        focus_items=[],
    )

    assert "### 典型例题解析" in fixed
    assert "未命名章节的典型例题解析" not in fixed


def test_textbook_heading_focus_drops_trailing_action_clause() -> None:
    assert (
        clean_heading_focus(
            "建立极限的基本语言与常见题型入口，先会识别题目属于哪类极限问题。",
            max_chars=32,
        )
        == "建立极限的基本语言与常见题型入口"
    )
    assert clean_heading_focus("理解多元函数、偏导数、全微分、方向导数等基础概念") == "理解多元函数、偏导数、全微分"


def test_textbook_heading_normalization_repairs_malformed_sprint_titles() -> None:
    raw = "\n".join(
        [
            "## 区分不定积分、定积分及其几何意义，先的边界说明",
            "### 解题步骤",
            "### 题目条件",
            "### 易错诊断",
            "## 理解多元函数、偏导数、全微分、方向导的判定规则",
        ]
    )

    fixed = normalize_textbook_headings(
        raw,
        digest_mode="sprint",
        fallback_title="多元函数的偏导数、全微分与方向导数",
        focus_items=[
            "区分不定积分、定积分及其几何意义，先建立概念边界",
        ],
    )

    assert "区分不定积分、定积分及其几何意义，先的" not in fixed
    assert "区分不定积分、定积分及其几何意义的边界说明" in fixed
    assert "### 解题步骤" in fixed
    assert "### 题目条件" in fixed
    assert "### 易错诊断" in fixed
    assert "方向导的判定规则" not in fixed
    assert "方向导数的判定规则" in fixed


def test_textbook_heading_normalization_drops_repeated_visible_titles() -> None:
    raw = "\n".join(
        [
            "### 极限题型入口",
            "第一题。",
            "### 极限题型入口",
            "第二题。",
            "### 极限公式判定",
            "清单一。",
            "### 极限公式判定",
            "清单二。",
        ]
    )

    fixed = normalize_textbook_headings(
        raw,
        digest_mode="sprint",
        fallback_title="极限、连续与常见极限题的计算方法",
        focus_items=[],
    )

    assert fixed.count("### 极限题型入口") == 1
    assert fixed.count("### 极限公式判定") == 1
    assert "第一题。" in fixed
    assert "第二题。" in fixed
    assert "清单一。" in fixed
    assert "清单二。" in fixed


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


def test_presentation_validator_catches_style_contract_issues() -> None:
    raw = "\n".join(
        [
            "## 跳级开头",
            "",
            "这里有 **未闭合的重点。",
            "",
            "| 项目 | 内容 |",
            "| --- | --- |",
            "| A | B | C |",
            "",
            "```",
            "print('missing language')",
            "```",
            "",
            "<div>不受控 HTML</div>",
        ]
    )

    issues = find_markdown_presentation_issues(raw)

    assert "Markdown 首个标题不是一级标题。" in issues
    assert "Markdown 加粗标记 ** 未成对闭合。" in issues
    assert "Markdown 表格行列数不一致。" in issues
    assert "Markdown 代码块缺少语言标记。" in issues
    assert "Markdown 正文包含不受控 HTML 标签。" in issues


def test_presentation_normalizes_safe_highlight_spacing_and_summarizes() -> None:
    raw = "# 标题\n\n这是 == 关键结论 ==，也可以 <mark> 条件 </mark>。"

    fixed = normalize_markdown_rendering(raw)
    summary = summarize_markdown_presentation(fixed)

    assert "==关键结论==" in fixed
    assert "<mark>条件</mark>" in fixed
    assert summary["highlight_count"] == 2
    assert summary["issue_count"] == 0


def test_single_file_html_validator_reports_sidecar_risks() -> None:
    html = (
        "<html><head><style>@import \"https://example.com/x.css\";"
        ".hero{background-image:url(https://example.com/a.png)}</style></head>"
        "<body><script src=\"https://example.com/x.js\"></script><script>localStorage.getItem('x')</script></body></html>"
    )

    issues = validate_single_file_html(html)

    assert "HTML sidecar 缺少 <!doctype html>。" in issues
    assert "HTML sidecar 包含外部脚本引用。" in issues
    assert "HTML sidecar 包含外部样式 import。" in issues
    assert "HTML sidecar 包含远程样式资源。" in issues
    assert "HTML sidecar 包含不允许的联网或持久化 API。" in issues


def test_single_file_html_validator_rejects_remote_resource_attributes() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>demo</title>
</head>
<body>
  <iframe src="https://example.com/embed"></iframe>
  <object data="//cdn.example.com/diagram.svg"></object>
  <video poster="https://example.com/poster.png"></video>
  <img srcset="local.png 1x, https://example.com/remote.png 2x" alt="" />
</body>
</html>"""

    issues = validate_single_file_html(html)

    assert "HTML sidecar 包含远程资源 URL。" in issues


def test_single_file_html_validator_ignores_script_resource_string_literals() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>demo</title>
</head>
<body>
  <script>
    const sample = '<iframe src="https://example.com/embed"></iframe>';
    const link = '<object data="//cdn.example.com/diagram.svg"></object>';
  </script>
</body>
</html>"""

    assert validate_single_file_html(html) == []


def test_single_file_html_validator_ignores_script_and_style_literals() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>demo</title>
  <style>.note::before{content:"<head> text";}</style>
</head>
<body>
  <script>const sample = "<head><body></body></head>";</script>
</body>
</html>"""

    assert validate_single_file_html(html) == []


def test_single_file_html_validator_does_not_count_header_as_head() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>demo</title>
</head>
<body>
  <header><h1>函数图像交互演示</h1></header>
  <main><section>正文</section></main>
</body>
</html>"""

    assert validate_single_file_html(html) == []


def test_normalize_single_file_html_rebuilds_nested_document_shells() -> None:
    raw = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /><title>旧标题</title></head>
<body>
  <main>正文</main>
  <script>const sample = "<head><body></body></head>";</script>
  <head><title>重复标题</title><style>.lost{color:red}</style></head>
</body>
</html>"""

    cleaned = normalize_single_file_html(raw, title="交互演示", allow_scripts=True)

    assert validate_single_file_html(cleaned) == []
    assert cleaned.split("<body>", 1)[0].lower().count("<head") == 1
    assert "<main>正文</main>" in cleaned
    assert 'const sample = "<head><body></body></head>";' in cleaned


def test_normalize_single_file_html_keeps_forbidden_apis_rejectable() -> None:
    raw = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /></head>
<body>
  <button id="load">加载</button>
  <script>
    document.getElementById("load").addEventListener("click", () => {
      fetch("/api/demo").then(() => localStorage.setItem("x", "1"));
    });
  </script>
</body>
</html>"""

    cleaned = normalize_single_file_html(raw, title="交互演示", allow_scripts=True)

    assert "fetch(" in cleaned
    assert "localStorage.setItem" in cleaned
    assert "HTML sidecar 包含不允许的联网或持久化 API。" in validate_single_file_html(cleaned)
