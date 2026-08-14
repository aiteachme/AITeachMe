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


def test_normalize_repairs_reversed_code_fence_language_markers() -> None:
    raw = """## Hello Python脚本格式

下面是一份完整的 **Hello Python脚本**：
```python

### 交互式运行示例

终端输入：
```
python
```text

进入后，屏幕上通常会出现版本信息，并在最后显示交互式提示符，例如：
```
Python 3.x.x (...)
>
```text

如果把同样的语句保存到脚本文件中，只写这一行即可：
```
print("Hello")
```text

[!NOTE]

这里先按“能运行、能辨认错误”的口径学习。

# 这是我的第一个 Python 脚本
print("Hello Python")
print("我正在学习运行脚本")
```
"""

    fixed = normalize_markdown_rendering(raw)

    assert "```python\n\n### 交互式运行示例" not in fixed
    assert "### 交互式运行示例" in fixed
    assert "```bash\npython\n```" in fixed
    assert "```python\nprint(\"Hello\")\n```" in fixed
    assert "```python\n# 这是我的第一个 Python 脚本\nprint(\"Hello Python\")" in fixed
    assert fixed.count("```") % 2 == 0


def test_normalize_unwraps_prose_trapped_in_python_fence() -> None:
    raw = """```python

`print(name)` 这里只用于观察变量 `name` 当前引用的值；后续示例里的文本会用引号表示，`#` 后面的短句只作为代码说明，不参与变量赋值和取值。

个人信息卡程序请重点检查三件事：变量名要先赋值再使用，前后拼写要完全一致；在 f-string 中，`{变量名}` 会取出变量当前引用的值参与输出。

---

程序从键盘接收输入时，常使用 `input()`。在本节示例中，`input()` 得到的内容先按字符串 `str` 处理；如果要参与半径、温度等数值计算，需要再用 `int()` 或 `float()` 转换。

```
```python
radius = input("请输入圆的半径：")
print(type(radius))
```

# 保存用户姓名
name = "小明"
```python
print(name)
```
"""

    fixed = normalize_markdown_rendering(raw)

    assert "```python\n\n`print(name)`" not in fixed
    assert "程序从键盘接收输入时" in fixed
    assert (
        "```python\n# 保存用户姓名\nname = \"小明\"\n\nprint(name)\n```"
        in fixed
    )


def test_normalize_drops_empty_code_fence_before_real_fence() -> None:
    raw = """参考答案：

```python

```
```python
print("I am learning Python")
print("This is my first program")
```
"""

    fixed = normalize_markdown_rendering(raw)

    assert "```python\n\n```" not in fixed
    assert fixed.count("```python") == 1
    assert 'print("I am learning Python")' in fixed


def test_presentation_issue_reports_markdown_swallowed_by_code_fence() -> None:
    raw = """```python
## 被吞进代码块的小节

这是一段正文，不应该在代码块里。
```"""

    issues = find_markdown_presentation_issues(raw)
    fixed = normalize_markdown_rendering(raw)

    assert "Markdown 代码块中混入了正文标题或段落。" in issues
    assert "Markdown 代码块中混入了正文标题或段落。" not in find_markdown_presentation_issues(fixed)
    assert "## 被吞进代码块的小节" in fixed


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


def test_normalize_supports_practice_and_question_callout_blocks() -> None:
    raw = (
        "[!PRACTICE]\n1. **任务**：判断条件是否满足。\n2. **答案**：满足。\n\n"
        "[!QUESTION]\n**题目**：判断函数是否单调。\n- A. 是\n- B. 否"
    )

    fixed = normalize_markdown_rendering(raw)
    normalized = normalize_educational_callouts(fixed)
    summary = summarize_markdown_presentation(fixed)

    assert fixed.startswith("> [!PRACTICE]\n>\n> 1. **任务**")
    assert normalized.startswith("**练习**\n\n1. **任务**")
    assert "> [!QUESTION]\n>\n> **题目**：判断函数是否单调。" in normalized
    assert "> - A. 是" in normalized
    assert "GitHub callout 未使用 blockquote 语法。" not in find_markdown_rendering_issues(normalized)
    assert summary["callout_count"] == 2


def test_normalize_splits_callout_learning_fields_into_paragraphs() -> None:
    raw = (
        "> [!EXAMPLE]\n"
        "> **例题**：设 $f(x)$ 连续。 **解析**：构造辅助函数并使用定理。 "
        "**答案/结论**：命题成立。 **易错点**：不要漏掉适用条件。"
    )

    fixed = normalize_markdown_rendering(raw)

    assert "> **例题**：设 $f(x)$ 连续。\n>\n> **解析**：构造辅助函数并使用定理。" in fixed
    assert "> **答案/结论**：命题成立。\n>\n> **易错点**：不要漏掉适用条件。" in fixed
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


def test_normalize_mermaid_repairs_labels_plain_lines_and_class_lists() -> None:
    raw = "\n".join(
        [
            "```mermaid",
            "flowchart LR PC: 0xFFFF0 → 0x00000",
            "A[导数应用] --> B1[一阶导数正负]",
            "B1 --> B2[递增: f'(x) > 0]",
            "B1 -->|f'(x) < 0| B3[递减]",
            "G[练习]",
            "classDef core fill:#f9f,stroke:#333,stroke-width:1px;",
            "class A, B1, G core",
            "```",
        ]
    )

    fixed = normalize_mermaid_blocks(raw)

    assert 'A["导数应用"] --> B1["一阶导数正负"]' in fixed
    assert 'B1 --> B2["递增: f\'(x) 大于 0"]' in fixed
    assert "B1 -->|f'(x) 小于 0| B3[\"递减\"]" in fixed
    assert '["PC: 0xFFFF0 → 0x00000"]' in fixed
    assert "class A,B1,G core" in fixed
    assert "classDef core fill:#f9f,stroke:#333,stroke-width:1px;" in fixed


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
            "观察提示：组合即得标准提示符。",
        ]
    )

    fixed = normalize_markdown_rendering(raw)

    assert "  - `$$`：显示 `$` 符号。" in fixed
    assert "- **示例**：\n```dos\nPROMPT $P$G\n```" in fixed
    assert "> [!TIP]\n>\n> 观察提示：组合即得标准提示符。" in fixed
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
            "",
            "<!-- [MERMAID: DOS 命令的整体知识脉络图] -->",
        ]
    )

    fixed = sanitize_public_markdown(normalize_markdown_rendering(raw))

    assert "读完《" not in fixed
    assert "LLM 预选" not in fixed
    assert "来源切片" not in fixed
    assert "参考资料与延伸阅读" not in fixed
    assert "计算机基础.pdf" not in fixed
    assert "MERMAID:" not in fixed
    assert "<!--" not in fixed
    assert "## 典型例题" in fixed
    assert "`PROMPT $P$G`" in fixed


def test_normalize_separates_github_callout_markers_and_adjacent_blocks() -> None:
    raw = "\n".join(
        [
            "> [!IMPORTANT]",
            "> 从方程到函数的转化，本质是从点态求解转向整体建模。",
            "",
            "> [!WARNING] 不要把无实数根误判为无解。",
            "> 例如，十位数字不能为 0。",
            "> [!NOTE]",
            ">",
            "> 🔗 本章定位：这是代数思维的起点。",
        ]
    )

    fixed = normalize_markdown_rendering(raw)

    assert "> [!IMPORTANT]\n>\n> 从方程到函数的转化" in fixed
    assert "> [!WARNING]\n>\n> 不要把无实数根误判为无解。" in fixed
    assert "> 例如，十位数字不能为 0。\n\n> [!NOTE]" in fixed
    assert "> [!NOTE]\n>\n> 🔗 本章定位：这是代数思维的起点。" in fixed


def test_textbook_style_promotes_educational_emoji_quotes_to_callouts() -> None:
    raw = "\n".join(
        [
            "> 💡 **观察提示**：看到平方差就先想共轭或因式分解。",
            "",
            "> ✅ **高频考点**：先抓题目条件，再选公式。",
            "",
            "> ⭐ **关键结论**：先抓题目条件，再选公式。",
            "",
            "> ⚠️ **边界提醒**：不要把定义域限制漏掉。",
            "",
            "> ✅ **答案**：5",
            "",
            "> ✅ **答案/结论**：命题成立。",
            "",
            "> 这是一段普通引用，后面会提醒注意事项。",
            "",
            "> 普通引用不应变化。",
        ]
    )

    fixed = normalize_educational_callouts(raw)

    assert "> [!TIP]\n>\n> **观察提示**：看到平方差就先想共轭或因式分解。" in fixed
    assert "> [!IMPORTANT]\n>\n> **高频考点**：先抓题目条件，再选公式。" in fixed
    assert "> [!IMPORTANT]\n>\n> **关键结论**：先抓题目条件，再选公式。" in fixed
    assert "> [!WARNING]\n>\n> **边界提醒**：不要把定义域限制漏掉。" in fixed
    assert "> ✅ **答案**：5" in fixed
    assert "> [!IMPORTANT]\n>\n> ✅ **答案**：5" not in fixed
    assert "> ✅ **答案/结论**：命题成立。" in fixed
    assert "> [!IMPORTANT]\n>\n> ✅ **答案/结论**：命题成立。" not in fixed
    assert "> 这是一段普通引用，后面会提醒注意事项。" in fixed
    assert "> [!WARNING]\n>\n> 这是一段普通引用" not in fixed
    assert "> 普通引用不应变化。" in fixed


def test_textbook_style_flattens_large_example_and_practice_callouts() -> None:
    raw = "\n".join(
        [
            "> [!EXAMPLE]",
            ">",
            "> **题目/任务**：计算一元一次方程，并说明每一步为什么可以等价变形。",
            ">",
            "> **解析/判定依据**：先移项，再合并同类项，最后把系数化为 1。",
            ">",
            "> **答案/结论**：得到唯一解。",
            "",
            "> [!PRACTICE]",
            ">",
            "> **任务**：判断下一步变形是否等价。",
            ">",
            "> **答案**：等价。",
            "",
            "> [!TIP]",
            ">",
            "> 先看条件。",
        ]
    )

    fixed = normalize_educational_callouts(raw)

    assert "> [!EXAMPLE]" not in fixed
    assert "> [!PRACTICE]" not in fixed
    assert "**例题**" in fixed
    assert "**练习**" in fixed
    assert "**题目/任务**：计算一元一次方程" in fixed
    assert "**任务**：判断下一步变形是否等价" in fixed
    assert "> [!TIP]\n>\n> 先看条件。" in fixed


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

    assert "## 典型例题解析" in fixed
    assert "未命名章节的典型例题解析" not in fixed


def test_textbook_headings_do_not_skip_from_h1_to_h3() -> None:
    raw = "\n".join(
        [
            "# 数与式运算、化简与因式分解",
            "",
            "### 学习目标与核心概念",
            "正文。",
            "",
            "#### 分式约分",
            "正文。",
        ]
    )

    fixed = normalize_textbook_headings(
        raw,
        digest_mode="sprint",
        fallback_title="数与式运算、化简与因式分解",
        focus_items=[],
    )

    assert "\n**本章目标与知识点**" in fixed
    assert "\n## 分式约分" in fixed
    assert "## 学习目标与核心概念" not in fixed
    assert "\n#### 学习目标与核心概念" not in fixed


def test_textbook_heading_focus_drops_action_clauses_but_preserves_math() -> None:
    assert (
        clean_heading_focus(
            "建立极限的基本语言与常见题型入口，先会识别题目属于哪类极限问题。",
            max_chars=32,
        )
        == "建立极限的基本语言与常见题型入口"
    )
    assert clean_heading_focus("理解多元函数、偏导数、全微分、方向导数等基础概念") == "理解多元函数、偏导数、全微分"
    assert clean_heading_focus("$dy=f'(x)dx$ 的使用条件", max_chars=80) == "$dy=f'(x)dx$ 的使用条件"


def test_textbook_heading_normalization_preserves_inline_math_comparisons() -> None:
    fixed = normalize_textbook_headings(
        "# 中值定理\n\n### 证明当 $x>0$ 时，$e^x>1+x$\n\n正文。",
        digest_mode="sprint",
    )

    assert "## 证明当 $x>0$ 时，$e^x>1+x$" in fixed
    assert "$x 0$" not in fixed
    assert "$e^x 1+x$" not in fixed


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
    assert "## 区分不定积分、定积分及其几何意义的边界说明" in fixed
    assert "### 解题步骤" in fixed
    assert "### 题目条件" in fixed
    assert "### 易错诊断" in fixed
    assert "方向导的判定规则" not in fixed
    assert "## 理解多元函数、偏导数、全微分、方向导数的判定规则" in fixed


def test_textbook_heading_normalization_demotes_ai_scaffold_titles() -> None:
    raw = "\n".join(
        [
            "# 连续与间断",
            "",
            "## 学习目标与核心概念",
            "理解连续定义。",
            "",
            "## 核心概念",
            "左极限、右极限和函数值。",
            "",
            "## 易错点",
            "忽略定义域。",
            "",
            "## 典型例题回顾",
            "题1. 判断连续性。",
            "",
            "## 本章高频规则清单",
            "分界点优先看左右极限。",
            "",
            "## 章末练习",
            "题1. 判断左右极限。",
            "",
            "## 学习大纲",
            "连续、间断、极限。",
            "",
            "## 典型方法与例题",
            "分段函数先看分界点。",
            "",
            "## 章末小结",
            "左右极限相等才可能连续。",
            "",
            "## 真实知识点",
            "这里保留为知识点。",
            "",
            "## 单元测试",
            "1. 判断间断点类型。答案：可去间断点。",
        ]
    )

    fixed = normalize_textbook_headings(
        raw,
        digest_mode="sprint",
        fallback_title="连续与间断",
        focus_items=[],
    )

    assert "\n**本章目标与知识点**" in fixed
    assert "\n**知识点速览**" in fixed
    assert "\n**易错点**" in fixed
    assert "\n**例题回顾**" in fixed
    assert "\n**高频规则**" in fixed
    assert "\n**练习**" in fixed
    assert "\n**学习大纲**" in fixed
    assert "\n**方法与例题**" in fixed
    assert "\n**小结**" in fixed
    assert "\n## 真实知识点" in fixed
    assert "\n## 单元测试" in fixed
    assert "## 典型例题回顾" not in fixed
    assert "## 本章高频规则清单" not in fixed
    assert "## 章末练习" not in fixed
    assert "## 学习大纲" not in fixed
    assert "## 典型方法与例题" not in fixed
    assert "## 章末小结" not in fixed
    assert "## 核心概念" not in fixed
    assert "## 易错点" not in fixed


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


def test_presentation_validator_catches_readability_and_learning_block_issues() -> None:
    long_paragraph = "这是一段连续铺开的解释文字，用来模拟没有分组、没有停顿、学生很难扫读的长段落。" * 24
    raw = "\n".join(
        [
            "# 标题",
            "",
            long_paragraph,
            "",
            "> [!EXAMPLE]",
            ">",
            "> **题目**：计算 1 + 1，并说明为什么这样计算。",
        ]
    )

    issues = find_markdown_presentation_issues(raw)
    summary = summarize_markdown_presentation(raw)

    assert "Markdown 存在超长正文段落，影响学生扫读。" in issues
    assert "例题/练习 callout 缺少题目、解析或答案字段。" in issues
    assert summary["long_paragraph_count"] == 1
    assert summary["example_callout_count"] == 1
    assert summary["reading_block_count"] >= 1


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
        "<body><script src=\"https://example.com/x.js\"></script><script>localStorage.getItem('x')</script>"
        "<iframe src=\"https://example.com/embed\"></iframe>"
        "<object data=\"//cdn.example.com/diagram.svg\"></object>"
        "<img srcset=\"local.png 1x, https://example.com/remote.png 2x\" alt=\"\" /></body></html>"
    )

    issues = validate_single_file_html(html)

    assert "HTML sidecar 缺少 <!doctype html>。" in issues
    assert "HTML sidecar 包含外部脚本引用。" in issues
    assert "HTML sidecar 包含外部样式 import。" in issues
    assert "HTML sidecar 包含远程样式资源。" in issues
    assert "HTML sidecar 包含不允许的联网或持久化 API。" in issues
    assert "HTML sidecar 包含远程资源 URL。" in issues


def test_single_file_html_validator_ignores_markup_inside_literals_and_header_tags() -> None:
    html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>demo</title>
  <style>.note::before{content:"<head> text";}</style>
</head>
<body>
  <script>
    const sample = '<iframe src="https://example.com/embed"></iframe>';
    const link = '<object data="//cdn.example.com/diagram.svg"></object>';
    const shell = "<head><body></body></head>";
  </script>
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
    assert 'http-equiv="Content-Security-Policy"' in cleaned
    assert "connect-src 'none'" in cleaned
    assert "form-action 'none'" in cleaned


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


def test_normalize_single_file_html_csp_limits_external_resources_to_allowlist() -> None:
    raw = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <script src="https://unpkg.com/example/widget.js"></script>
</head>
<body><main>交互演示</main></body>
</html>"""

    cleaned = normalize_single_file_html(
        raw,
        title="交互演示",
        allow_scripts=True,
        allow_external_resources=True,
        allowed_resource_hosts={"unpkg.com"},
    )

    assert "script-src 'unsafe-inline' https://unpkg.com" in cleaned
    assert "connect-src 'none'" in cleaned
    assert validate_single_file_html(
        cleaned,
        allow_external_resources=True,
        allowed_resource_hosts={"unpkg.com"},
    ) == []
