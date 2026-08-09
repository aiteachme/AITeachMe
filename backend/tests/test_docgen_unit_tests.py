import re

from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestItem,
    ChapterUnitTestSet,
    append_unit_test_markdown,
    normalize_published_unit_test_sections,
    render_unit_test_markdown,
    strip_existing_unit_test_sections,
)


def test_unit_test_renderer_replaces_existing_unit_test_section_once() -> None:
    body = (
        "# 统计量\n\n"
        "## 平均数\n\n"
        "平均数反映整体水平。\n\n"
        "## 6.7 章末单元测试\n\n"
        "旧测试。\n\n"
        "## 中位数\n\n"
        "中位数反映中间位置。\n"
    )
    unit_test = render_unit_test_markdown(
        ChapterUnitTestSet(
            chapter_index=1,
            items=[
                ChapterUnitTestItem(
                    target="平均数",
                    stem="给出平均数的计算方法。",
                    answer="总和除以个数。",
                    basis="先求和，再除以样本数。",
                )
            ],
        ),
        title="统计量",
        min_items=1,
        fallback_targets=["中位数"],
    )

    markdown = append_unit_test_markdown(body, unit_test)

    assert "旧测试" not in strip_existing_unit_test_sections(body)
    assert markdown.count("## 单元测试") == 1
    assert '<div class="atm-unit-tests"' not in markdown
    assert "> [!QUESTION]" in markdown
    assert "> [!ANSWER]" in markdown
    assert "**1 题覆盖**" in markdown
    assert "短答题" in markdown
    assert "**答案**" in markdown
    assert "**解析步骤**" in markdown
    assert "总和除以个数。" in markdown
    assert "###" not in unit_test
    assert "> **答案与依据**" not in unit_test
    assert "**判定依据**" not in unit_test


def test_unit_test_renderer_strips_body_writer_test_and_recap_sections() -> None:
    body = (
        "# 三角形全等\n\n"
        "## 全等判定条件\n\n"
        "SSS、SAS、ASA 都可以作为判定条件。\n\n"
        "## 单元小测\n\n"
        "旧的小测题。\n\n"
        "## 小结式检查清单与单元测试\n\n"
        "旧的小结清单和测试。\n"
    )

    stripped = strip_existing_unit_test_sections(body)
    markdown = append_unit_test_markdown(
        body,
        render_unit_test_markdown(
            ChapterUnitTestSet(
                chapter_index=1,
                items=[
                    ChapterUnitTestItem(
                        target="全等判定条件",
                        stem="说明 SSS 判定条件。",
                        answer="三边分别相等。",
                        basis="SSS 要求三组对应边分别相等。",
                    )
                ],
            ),
            title="三角形全等",
            min_items=1,
            fallback_targets=["全等判定条件"],
        ),
    )

    assert "## 全等判定条件" in stripped
    assert "旧的小测题" not in stripped
    assert "旧的小结清单和测试" not in stripped
    assert markdown.count("## 单元测试") == 1
    assert "单元小测" not in markdown
    assert "小结式检查清单" not in markdown


def test_unit_test_renderer_normalizes_raw_and_escaped_latex_options() -> None:
    unit_test = render_unit_test_markdown(
        ChapterUnitTestSet(
            chapter_index=1,
            items=[
                ChapterUnitTestItem(
                    type="single_choice",
                    difficulty="medium",
                    target="复合函数定义域",
                    stem=r"已知函数 f(x) 的定义域为 [0, 2]，则函数 f(x^2) 的定义域为：",
                    options=[r"[0, 4]", r"[0, \sqrt{2}]", r"[-\sqrt{2}, \sqrt{2}]", "[-2, 2]"],
                    answer=r"[-\sqrt{2}, \sqrt{2}]",
                    basis=r"需要满足 0 \leq x^2 \leq 2。",
                ),
                ChapterUnitTestItem(
                    type="single_choice",
                    difficulty="medium",
                    target="连续定义",
                    stem=r"函数 f(x) 在 x_0 处连续的充要条件是哪一项？",
                    options=[
                        r"\|$$\lim_{x \to x_0} f(x)$$ 存在",
                        r"\|$$f(x_0)$$ 有定义",
                        r"\|$$\lim_{x \to x_0} f(x)=f(x_0)$$",
                        r"\|$$\lim_{x \to x_0^-} f(x)=\lim_{x \to x_0^+} f(x)$$",
                    ],
                    answer=r"C. $$\lim_{x \to x_0} f(x)=f(x_0)$$",
                    basis=r"连续要求极限存在、函数值存在，并且二者相等。",
                ),
            ],
        ),
        title="函数",
        min_items=2,
        fallback_targets=[],
    )

    assert r"$[0, \sqrt{2}]$" in unit_test
    assert r"$[-\sqrt{2}, \sqrt{2}]$" in unit_test
    assert r"$0 \leq x^2 \leq 2$" in unit_test
    assert r"\|$$" not in unit_test
    assert r"$$\lim_{x \to x_0} f(x)=f(x_0)$$" in unit_test
    assert r"$$\lim_{x \to x_0^-} f(x)=\lim_{x \to x_0^+} f(x)$$" in unit_test
    assert r"..." not in unit_test
    assert "…" not in re.search(r"> - C\..+", unit_test).group(0)


def test_unit_test_renderer_keeps_decimal_steps_and_code_options_readable() -> None:
    unit_test = render_unit_test_markdown(
        ChapterUnitTestSet(
            chapter_index=1,
            items=[
                ChapterUnitTestItem(
                    type="错因辨析",
                    difficulty="进阶",
                    target="错误定位：int 转换失败",
                    stem='下面代码在用户输入 "abc" 时会出错。哪一项给出了正确的错误类型和修正关键句？ age = int(input("请输入年龄：")) print(age)',
                    options=[
                        'ValueError；age_text = input("请输入年龄：").strip(); if age_text.isdigit(): age = int(age_text)',
                        'FileNotFoundError；with open("age.txt", "r") as f: age = f.read()',
                        'ZeroDivisionError；if len(age) != 0: print(age)',
                        'TypeError；age = str(input("请输入年龄：")); print(age)',
                    ],
                    answer='ValueError；age_text = input("请输入年龄：").strip(); if age_text.isdigit(): age = int(age_text)',
                    basis="1. input() 得到字符串。 2. int(\"abc\") 不能转换为整数。 3. 平均值示例为 270 / 3 = 90.0。 4. 应先判断再转换。",
                )
            ],
        ),
        title="Python 入门",
        min_items=1,
        fallback_targets=[],
    )

    assert "str…" not in unit_test
    assert "print…" not in unit_test
    assert 'age_text = input("请输入年龄：").strip()' in unit_test
    assert "270 / 3 = 90.0" in unit_test
    assert "> 5. 0" not in unit_test


def test_unit_test_renderer_removes_fill_blank_options_and_resolves_letter_answer() -> None:
    unit_test = render_unit_test_markdown(
        ChapterUnitTestSet(
            chapter_index=1,
            items=[
                ChapterUnitTestItem(
                    type="填空题",
                    difficulty="基础",
                    target="对称轴、顶点与最值",
                    stem=r"函数 $y=x^2-4x+1$ 的对称轴是____，顶点是____，最小值是____。",
                    options=[r"$x=2$，$(2,-3)$，$-3$"],
                    answer="A",
                    basis=r"配方得到 $y=(x-2)^2-3$。",
                )
            ],
        ),
        title="二次函数",
        min_items=1,
        fallback_targets=[],
    )

    assert "**Q01｜填空题｜基础｜考点：对称轴、顶点与最值**" in unit_test
    assert "**选项**" not in unit_test
    assert "> A\n" not in unit_test
    assert r"$x=2$，$(2,-3)$，$-3$" in unit_test


def test_unit_test_renderer_normalizes_metadata_and_keeps_four_options() -> None:
    unit_test = render_unit_test_markdown(
        ChapterUnitTestSet(
            chapter_index=1,
            items=[
                ChapterUnitTestItem(
                    type="single_choice",
                    difficulty="hard",
                    target="函数单调性",
                    stem="下列哪一项最能判断函数单调性？",
                    options=["定义域", "函数值变化方向", "图像颜色", "函数名称"],
                    answer="函数值变化方向",
                    basis="单调性看自变量变化时函数值的变化方向。",
                ),
                ChapterUnitTestItem(
                    type="概念判断",
                    difficulty="基础",
                    target="函数相等判定",
                    stem="关于函数相等，哪一项正确？",
                    options=["定义域相同且对应法则相同", "只看表达式一样", "只看图像相似", "只看函数名一致"],
                    answer="定义域相同且对应法则相同",
                    basis="函数相等需要定义域和对应关系同时一致。",
                ),
                ChapterUnitTestItem(
                    type="错因辨析",
                    difficulty="进阶",
                    target="复合函数定义域",
                    stem="求复合函数定义域时，哪一项最容易导致错误？",
                    options=["忘记内层函数值域限制", "先写外层条件", "列不等式", "检查端点"],
                    answer="忘记内层函数值域限制",
                    basis="复合函数需要同时满足内层表达式和外层定义域。",
                ),
            ],
        ),
        title="函数",
        min_items=3,
        fallback_targets=[],
    )

    assert "**Q01｜选择题｜挑战｜考点：函数单调性**" in unit_test
    assert "**Q02｜概念判断｜基础｜考点：函数相等判定**" in unit_test
    assert "**Q03｜错因辨析｜进阶｜考点：复合函数定义域**" in unit_test
    assert unit_test.count("- A.") == 3
    assert unit_test.count("- B.") == 3
    assert unit_test.count("- C.") == 3
    assert unit_test.count("- D.") == 3


def test_unit_test_renderer_keeps_generated_items_without_filling_type_diversity() -> None:
    unit_test = render_unit_test_markdown(
        ChapterUnitTestSet(
            chapter_index=1,
            items=[
                ChapterUnitTestItem(
                    type="短答题",
                    difficulty="基础",
                    target=f"知识点 {index}",
                    stem=f"解释知识点 {index}。",
                    answer="按正文作答。",
                    basis="说清条件和结论。",
                )
                for index in range(1, 7)
            ],
        ),
        title="函数",
        min_items=4,
        max_items=4,
        fallback_targets=["函数定义", "对应关系", "函数值"],
    )

    assert unit_test.count("**Q") == 4
    assert "**4 题覆盖**" in unit_test
    question_types = set(re.findall(r"Q\d+｜([^｜]+)｜", unit_test))
    assert question_types == {"短答题"}


def test_published_unit_test_normalizer_keeps_html_unit_test_block() -> None:
    markdown = (
        "# 圆与切线\n\n"
        "## 切线判定\n\n"
        "经过圆上一点且垂直半径的直线是切线。\n\n"
        "## 单元测试\n\n"
        '<div class="atm-unit-tests" data-unit-test-count="1">\n'
        '<article class="atm-unit-test-card">\n'
        '<details class="atm-unit-test-answer">\n'
        "<summary>查看答案与判定依据</summary>\n"
        "<p>答案内容</p>\n"
        "</details>\n"
        "</article>\n"
        "</div>\n\n"
        "## 不应保留的后续标题\n\n"
        "这段不应留在单元测试之后。\n"
    )

    normalized = normalize_published_unit_test_sections(markdown)

    assert normalized.count("## 单元测试") == 1
    assert '<div class="atm-unit-tests" data-unit-test-count="1">' in normalized
    assert '<details class="atm-unit-test-answer">' in normalized
    assert "查看答案与判定依据" in normalized
    assert "不应保留的后续标题" not in normalized


def test_published_unit_test_normalizer_restores_missing_standard_heading() -> None:
    markdown = (
        "# 平行线与角\n\n"
        "## 图形识别与小测\n\n"
        "先识别截线和角的位置。\n\n"
        "| 题号 | 训练点 | 题目 / 任务 | 答案与判定依据 |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | 同位角 | 识别同位角。 | 位置相同。 |\n"
    )

    normalized = normalize_published_unit_test_sections(markdown)

    assert "## 图形识别与小测" in normalized
    assert normalized.count("## 单元测试") == 1
    assert normalized.index("## 单元测试") < normalized.index("| 题号 | 训练点 | 题目 / 任务 | 答案与判定依据 |")


def test_published_unit_test_normalizer_removes_recap_sections() -> None:
    cases = [
        ("单元测试与快速自检", "旧自检内容。"),
        ("小结式检查清单", "做题前、做题中、做题后各检查一次。"),
        ("本章收口", "本章已经学完，最后回看一下。"),
        ("本章学习回看", "你应该形成三种直观。"),
    ]

    for recap_title, recap_body in cases:
        markdown = (
            "# 三角形全等\n\n"
            "## 全等证明路径\n\n"
            "先找对应关系，再选择判定条件。\n\n"
            f"## {recap_title}\n\n"
            f"{recap_body}\n\n"
            "## 单元测试\n\n"
            "| 题号 | 训练点 | 题目 / 任务 | 答案与判定依据 |\n"
            "| --- | --- | --- | --- |\n"
            "| 1 | 对应关系 | 写出对应顶点。 | 先看已知相等条件。 |\n"
        )

        normalized = normalize_published_unit_test_sections(markdown)

        assert f"## {recap_title}" not in normalized
        assert recap_body not in normalized
        assert "## 全等证明路径" in normalized
        assert normalized.count("## 单元测试") == 1


def test_published_unit_test_normalizer_promotes_h3_test_table_to_final_h2() -> None:
    markdown = (
        "# 圆与切线\n\n"
        "## 识图对照与错因回看\n\n"
        "先标圆心、切点和切线。\n\n"
        "### 单元测试\n"
        "围绕本章核心概念完成测试。\n\n"
        "### 快速自测\n"
        "1. 过圆上一点的直线一定是切线吗？\n\n"
        "| 题号 | 训练点 | 题目 / 任务 | 答案与判定依据 |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | 切线判定 | 判断 l 是否为切线。 | 经过切点且垂直半径。 |\n"
        "\n### 图示辨析补充\n"
        "这段属于正文补充，不应放在章末测试后。\n"
    )

    normalized = normalize_published_unit_test_sections(markdown)

    assert "### 单元测试" not in normalized
    assert "### 快速自测" not in normalized
    assert "图示辨析补充" not in normalized
    assert normalized.count("## 单元测试") == 1
    assert normalized.rstrip().endswith("| 1 | 切线判定 | 判断 l 是否为切线。 | 经过切点且垂直半径。 |")
