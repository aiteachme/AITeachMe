from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestItem,
    ChapterUnitTestSet,
    append_unit_test_markdown,
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
        min_items=2,
        fallback_targets=["中位数"],
    )

    markdown = append_unit_test_markdown(body, unit_test)

    assert "旧测试" not in strip_existing_unit_test_sections(body)
    assert markdown.count("## 单元测试") == 1
    assert markdown.rstrip().endswith("| 2 | 中位数 | 用一句话说明“中位数”的核心含义。 | 围绕“中位数”按本章定义、条件和步骤作答。；依据：能说清对象、条件和结论。 |")
    assert "###" not in unit_test
