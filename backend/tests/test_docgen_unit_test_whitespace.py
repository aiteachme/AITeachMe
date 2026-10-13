import pytest

from app.workflows.digest.docgen.lib.unit_test_generation import generate_chapter_unit_test_markdown
from app.workflows.digest.docgen.lib.publish import build_merged_markdown
from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestGenerationError,
    ChapterUnitTestItem,
    ChapterUnitTestSet,
    render_unit_test_markdown,
    unit_test_structure_issues,
)


@pytest.mark.parametrize(
    "options",
    [
        ["```text\ncat\ndog\nfox\n```", "```text\ncat dog fox\n```", "```text\nfox\ndog\ncat\n```", "```text\n0\n1\n2\n```"],
        ["`x`", "`x `", "`x  `", "`x   `"],
    ],
)
def test_distinct_whitespace_options_survive_validation_and_rendering(options):
    item = ChapterUnitTestItem(
        type="选择题", target="输出字符", stem="选择程序的完整输出。",
        options=options, answer=options[2], basis="逐字符核对空格、换行和输出顺序。",
    )
    assert item.options == options
    markdown = render_unit_test_markdown(
        ChapterUnitTestSet(items=[item]), title="输出字符", min_items=1, fallback_targets=[],
    )
    markdown = build_merged_markdown([
        {"chapter_index": 1, "title": "输出字符", "markdown": "# 输出字符\n\n" + markdown},
    ])
    assert unit_test_structure_issues(markdown, expected_question_count=1) == []
    for option in options:
        if "\n" not in option:
            assert option in markdown


def test_choice_answer_must_match_whitespace_inside_code():
    item = ChapterUnitTestItem(
        type="选择题", target="输出字符", stem="选择输出字符串。",
        options=["`x`", "`y`", "`z`", "`w`"], answer="`x  `", basis="末尾有两个空格。",
    )
    with pytest.raises(ChapterUnitTestGenerationError):
        render_unit_test_markdown(
            ChapterUnitTestSet(items=[item]), title="输出字符", min_items=1, fallback_targets=[],
        )


def test_published_choice_contract_rejects_answer_with_different_code_whitespace():
    item = ChapterUnitTestItem(
        type="选择题", target="输出字符", stem="选择输出字符串。",
        options=["`x`", "`y`", "`z`", "`w`"], answer="`x`", basis="输出一个字符。",
    )
    markdown = render_unit_test_markdown(
        ChapterUnitTestSet(items=[item]), title="输出字符", min_items=1, fallback_targets=[],
    ).replace("> **答案**\n>\n> `x`", "> **答案**\n>\n> `x  `")
    assert any("答案必须与 A-D 中某个完整选项一致" in issue for issue in unit_test_structure_issues(markdown))


def test_exact_duplicate_options_remain_unusable():
    item = ChapterUnitTestItem(
        type="选择题", target="输出字符", stem="选择输出字符串。",
        options=["`x `", "`x `", "`y`", "`z`"], answer="`x `", basis="输出一个空格。",
    )
    with pytest.raises(ChapterUnitTestGenerationError):
        render_unit_test_markdown(
            ChapterUnitTestSet(items=[item]), title="输出字符", min_items=1, fallback_targets=[],
        )


@pytest.mark.parametrize("options", [
    ["cat\ndog\nfox", "cat dog fox", "fox\ndog\ncat", "0\n1\n2"],
    ['"a b"', '"a  b"', '"a   b"', '"a    b"'],
])
def test_plain_markdown_whitespace_does_not_create_visually_duplicate_options(options):
    item = ChapterUnitTestItem(
        type="选择题", target="文本输出", stem="选择输出结果。",
        options=options, answer=options[0], basis="核对输出结果。",
    )
    with pytest.raises(ChapterUnitTestGenerationError):
        render_unit_test_markdown(
            ChapterUnitTestSet(items=[item]), title="输出字符", min_items=1, fallback_targets=[],
        )


def test_published_choice_contract_preserves_whitespace_only_code_lines():
    options = ["```text\nx\n  \ny\n```", "```text\nx\n\ny\n```", "```text\nx y\n```", "```text\ny x\n```"]
    item = ChapterUnitTestItem(
        type="选择题", target="空白行输出", stem="选择逐字符匹配的程序输出。",
        options=options, answer=options[0], basis="中间一行包含两个空格。",
    )
    markdown = render_unit_test_markdown(
        ChapterUnitTestSet(items=[item]), title="输出字符", min_items=1, fallback_targets=[],
    )
    assert unit_test_structure_issues(markdown) == []
    question, answer = markdown.split("> **答案**", 1)
    # A response with a different number of spaces is absent from the options.
    changed = question + "> **答案**" + answer.replace(">   \n", ">    \n", 1)
    assert any("答案必须与 A-D 中某个完整选项一致" in issue for issue in unit_test_structure_issues(changed))


@pytest.mark.anyio
async def test_complete_output_question_is_not_dropped_or_retried():
    stages = []

    async def fake_llm(_messages, **kwargs):
        stages.append(kwargs["extra_metadata"]["docgen_stage"])
        return {"chapter_index": 1, "items": [
            {"type": "选择题", "target": "列表索引", "stem": "['cat', 'dog'][1] 的值是？",
             "options": ["cat", "dog", "fox", "0"], "answer": "dog", "basis": "索引1读取第二个元素。"},
            {"type": "选择题", "target": "逐行输出", "stem": "for循环逐项print三个元素的输出是什么？",
             "options": ["```text\ncat\ndog\nfox\n```", "```text\n0\n1\n2\n```", "```text\nfox\ndog\ncat\n```", "```text\ncat dog fox\n```"],
             "answer": "```text\ncat\ndog\nfox\n```", "basis": "print每次换行，循环共输出三行。"},
        ]}

    markdown = await generate_chapter_unit_test_markdown(
        chapter_index=1, chapter_title="列表循环", digest_mode="sprint",
        required_elements=["列表索引", "逐行输出"], chapter_end_practice_plan=[],
        body_markdown="# 列表循环\n\n## 索引\n索引从0开始。\n\n## 循环\nprint每次换行。",
        min_items=2, max_items=2, llm_caller=fake_llm,
    )
    assert stages == ["generate_chapter_unit_test", "review_chapter_unit_test"]
    assert unit_test_structure_issues(markdown, expected_question_count=2) == []
