from __future__ import annotations

import ast
import re

import pytest

from app.workflows.digest.docgen.lib import repair, unit_tests
from app.workflows.digest.docgen.lib.models import EnhancedChapterDraft, ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.lib.quality import build_merge_review_report
from app.workflows.digest.docgen.lib.presentation_policy import normalize_docgen_presentation


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _choice_test(answer: str = "$2$") -> str:
    return (
        "## 单元测试\n\n"
        "> [!QUESTION] **Q01｜选择题｜基础｜考点：算术**\n>\n> 计算 $1+1$。\n>\n"
        "> - A. $2$\n> - B. $-2$\n> - C. $3$\n> - D. $4$\n\n"
        "> [!ANSWER]\n>\n> **答案**\n>\n> " + answer + "\n>\n"
        "> **解析步骤**\n>\n> 相加得到 $2$。\n"
    )


@pytest.mark.parametrize("answer", ["A", "a", "选项 A", "A. $2$", "A、$2$"])
def test_raw_choice_answer_normalization_uses_explicit_option_label(answer):
    markdown = _choice_test(answer)
    normalized = unit_tests.normalize_unit_test_choice_answers(markdown)
    assert normalized == _choice_test()
    assert unit_tests.unit_test_structure_issues(normalized) == []


@pytest.mark.anyio
@pytest.mark.parametrize("explicit_length", [{}, {"min_word_count": 1200, "max_word_count": 1600}])
async def test_repair_receives_explicit_length_without_mode_budget(monkeypatch, explicit_length):
    monkeypatch.setattr(repair, "_MAX_LLM_PATCH_ATTEMPTS_PER_TARGET", 1)
    quantities = {"body_section_count": 1, "min_word_count": None, "max_word_count": None, **explicit_length}
    contracts = []

    async def completion(messages, **kwargs):
        contract_text = messages[1]["content"].split("用户确认的当前章数量与写作边界（优先于模式默认）：\n", 1)[1].split("\n\n当前修补轮次", 1)[0]
        contract = ast.literal_eval(contract_text)
        assert "min_word_count" not in contract and "max_word_count" not in contract
        assert contract["quantity_constraints"] == quantities
        contracts.append(contract)
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 加法", patch_markdown="## 加法\n\n例题：$1+1=2$，两个1相加得到2。",
            covered_action_ids=["a1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapter = ReviewedChapterDraft(
        chapter_index=1, title="算术", markdown="# 算术\n\n## 加法\n\n例题：$1+1=3$。\n\n" + _choice_test(),
    )
    action = ReviewAction(
        action_id="a1", action_type="section_patch", chapter_index=1, severity="error", target_anchor="## 加法",
        instruction="纠正例题的计算结果。",
    )
    chapters, updated, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter], review_actions=[action], chapter_tasks=[{
            "chapter_index": 1, "quantity_constraints": quantities, "writing_rules": ["仅一个教学小节。"],
            "min_word_count": explicit_length.get("min_word_count", 2500),
            "max_word_count": explicit_length.get("max_word_count", 3600),
        }],
    )
    assert updated[0].status == "applied" and not unresolved
    assert len(contracts) == 1
    assert "$1+1=3$" not in chapters[0].markdown


@pytest.mark.parametrize("answer", ["A. $-2$", "E", "$5$", "A\n> B", "A或B"])
def test_raw_choice_answer_normalization_preserves_invalid_or_ambiguous_answer(answer):
    markdown = _choice_test(answer)
    assert unit_tests.normalize_unit_test_choice_answers(markdown) == markdown


def test_choice_normalization_preserves_fenced_examples_and_non_choice_answers():
    fenced = "```markdown\n" + _choice_test("A") + "```\n\n"
    non_choice = _choice_test("A").replace("选择题", "短答题")
    markdown = fenced + non_choice
    assert unit_tests.normalize_unit_test_choice_answers(markdown) == markdown


def test_patch_cleaning_preserves_python_blocks_and_keeps_intro_outside_code():
    code = 'values = ["猫", "狗"]\nfor value in values:\n    print(value)'
    raw = f'## 循环\n\n下面的程序使用四个空格缩进，让 `print(value)` 成为循环体：\n```python\n{code}\n```\n'
    cleaned = repair._clean_patch_snippet(raw, chapter_title="列表")
    published = normalize_docgen_presentation("# 列表\n\n" + cleaned, title="列表")
    blocks = re.findall(r"```python\n(.*?)\n```", published, re.DOTALL)
    assert blocks == [code]
    compile(blocks[0], "<self-authored-example>", "exec")
    assert "下面的程序" in published.split("```python", 1)[0]


def test_patch_cleaning_preserves_question_code_and_multiline_labeled_answer():
    options = [f"```text\n{first}\n{second}\n```" for first, second in ((1, 2), (2, 1), (-1, 2), (1, -2))]
    quiz = unit_tests.render_unit_test_markdown(
        unit_tests.ChapterUnitTestSet(items=[unit_tests.ChapterUnitTestItem(
            type="选择题", target="逐行输出", stem='输出是什么？\n\n```python\nprint(2)\nprint(1)\n```',
            options=options, answer="B", basis="两次print分别输出2和1。",
        )]), title="输出", min_items=1, fallback_targets=[],
    )
    original_answer = "\n".join(f"> {line}" for line in options[1].splitlines())
    labeled = quiz.replace("> **答案**\n>\n" + original_answer, "> **答案**\n>\n> B.\n>\n" + original_answer)
    cleaned = repair._clean_patch_snippet(labeled, chapter_title="输出")
    normalized = unit_tests.normalize_unit_test_choice_answers(cleaned)
    assert normalized.count("```text") == 5
    assert "> **答案**\n>\n" + original_answer in normalized
    assert unit_tests.unit_test_structure_issues(normalized, expected_question_count=1) == []
    quoted_python = "> ```python\n> print(2)\n> print(1)\n> ```"
    assert quoted_python in normalized


def test_structured_choice_answer_does_not_hide_sign_mismatch():
    item = unit_tests.ChapterUnitTestItem(
        type="选择题", options=["$2$", "$-2$", "$3$", "$4$"], answer="A. $-2$",
    )
    assert item.answer == "A. $-2$"


@pytest.mark.parametrize("options", [
    ["$2$", "$-2$", "$3$", "$4$"],
    ["$a/b$", "$ab$", "$a_b$", "$AB$"],
])
def test_unit_test_keeps_mathematically_distinct_options(options):
    item = unit_tests.ChapterUnitTestItem(
        type="选择题", target="符号", stem="选择正确结果。", options=options,
        answer=options[0], basis="逐项代入计算。",
    )
    assert len(item.options) == 4
    assert unit_tests._is_usable_unit_test_item(item)


def test_choice_contract_rejects_answer_with_wrong_sign():
    markdown = _choice_test("$-2$").replace("> - B. $-2$", "> - B. $1$")
    assert any("完整选项一致" in issue for issue in unit_tests.unit_test_structure_issues(markdown))


def test_unit_test_deduplication_keeps_questions_with_different_math_signs():
    items = [unit_tests.ChapterUnitTestItem(
        type="短答题", target="加法", stem=stem, answer=answer, basis="按符号相加。",
    ) for stem, answer in [("计算 $1+2$。", "$3$"), ("计算 $1+-2$。", "$-1$")]]
    assert len(unit_tests._dedupe_unit_test_items([*items, items[0]])) == 2


@pytest.mark.anyio
async def test_repair_attempts_each_section_and_tests_with_independent_limits(monkeypatch):
    monkeypatch.setattr(repair, "_MAX_LLM_PATCH_ATTEMPTS_PER_TARGET", 1)
    chapter = ReviewedChapterDraft(
        chapter_index=1, title="算术",
        markdown="# 算术\n\n## 加法\n\n先相加。\n\n## 减法\n\n先相减。\n\n" + _choice_test(),
    )
    actions = [
        ReviewAction(action_id=key, chapter_index=1, action_type="section_patch", severity="error", target_anchor=anchor)
        for key, anchor in [("a1", "## 加法"), ("a2", "## 减法"), ("a3", "## 单元测试")]
    ]
    calls = []

    async def completion(messages, **kwargs):
        user = messages[1]["content"]
        payloads = ast.literal_eval(user.split("复核动作列表：\n", 1)[1].split("\n\n用户确认", 1)[0])
        assert len(payloads) == 1
        key = payloads[0]["action_id"]
        calls.append(key)
        if key == "a3":
            assert "相加得到 $2$" in user
            markdown = _choice_test("A")
        else:
            assert "Q01" in user
            markdown = payloads[0]["target_anchor"] + "\n\n相加得到 $2$。" if key == "a1" else "## 减法\n\n相减得到差。"
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor=payloads[0]["target_anchor"],
            patch_markdown=markdown, covered_action_ids=[key],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapters, updated, unresolved, traces = await repair.repair_or_route_review_actions(reviewed_chapters=[chapter], review_actions=actions)
    assert calls == ["a1", "a2", "a3"]
    assert [action.status for action in updated] == ["applied"] * 3
    assert unresolved == []
    assert len({trace.llm_call_group for trace in traces}) == 3
    assert "相减得到差" in chapters[0].markdown
    assert unit_tests.unit_test_structure_issues(chapters[0].markdown) == []


@pytest.mark.anyio
async def test_regular_patch_retries_with_actual_rejection_feedback(monkeypatch):
    calls = 0

    async def completion(messages, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            markdown = "## 加法\n\n" + "过长内容" * 600
        else:
            assert "局部补丁过长" in messages[1]["content"]
            markdown = "## 加法\n\n相加得到和。"
        return repair._LocalMarkdownPatch(operation="replace_section", target_anchor="## 加法", patch_markdown=markdown, covered_action_ids=["a1"])

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapter = ReviewedChapterDraft(chapter_index=1, title="算术", markdown="# 算术\n\n## 加法\n\n旧内容。\n\n" + _choice_test())
    action = ReviewAction(action_id="a1", chapter_index=1, action_type="section_patch", target_anchor="## 加法", severity="error")
    chapters, updated, unresolved, _ = await repair.repair_or_route_review_actions(reviewed_chapters=[chapter], review_actions=[action])
    assert calls == 2
    assert updated[0].status == "applied"
    assert not unresolved
    assert "旧内容" not in chapters[0].markdown


@pytest.mark.anyio
@pytest.mark.parametrize("covered,unresolved", [(["a1"], ["a1"]), (["foreign-action"], [])])
async def test_patch_with_invalid_coverage_never_marks_error_resolved(monkeypatch, covered, unresolved):
    monkeypatch.setattr(repair, "_MAX_LLM_PATCH_ATTEMPTS_PER_TARGET", 1)

    async def completion(*args, **kwargs):
        return repair._LocalMarkdownPatch(operation="replace_section", target_anchor="## 加法", patch_markdown="## 加法\n\n声称已修好。", covered_action_ids=covered, unresolved_action_ids=unresolved)

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapter = ReviewedChapterDraft(chapter_index=1, title="算术", markdown="# 算术\n\n## 加法\n\n旧内容。\n")
    action = ReviewAction(action_id="a1", chapter_index=1, action_type="section_patch", target_anchor="## 加法", severity="error")
    chapters, updated, warnings, _ = await repair.repair_or_route_review_actions(reviewed_chapters=[chapter], review_actions=[action])
    assert chapters[0].markdown == chapter.markdown
    assert updated[0].status == "downgraded"
    assert warnings


@pytest.mark.anyio
@pytest.mark.parametrize("test_repair_valid", [True, False])
async def test_body_patch_does_not_retry_known_pending_test_error(monkeypatch, test_repair_valid):
    monkeypatch.setattr(repair, "_MAX_LLM_PATCH_ATTEMPTS_PER_TARGET", 1)
    incorrect_test = _choice_test().replace("相加得到 $2$。", "相加得到 $3$。")
    chapter = ReviewedChapterDraft(
        chapter_index=1, title="算术",
        markdown="# 算术\n\n## 加法\n\n例题：$1+1=3$。\n\n" + incorrect_test,
    )
    actions = [
        ReviewAction(
            action_id="body", action_type="section_patch", chapter_index=1, severity="error",
            target_anchor="## 加法", instruction="纠正正文例题，不能修改只读的章末题。",
        ),
        ReviewAction(
            action_id="test", action_type="section_patch", chapter_index=1, severity="error",
            target_anchor="## 单元测试", instruction="纠正章末题的错误解析。",
        ),
    ]
    patch_targets = []

    async def completion(messages, **kwargs):
        target = "## 加法" if not patch_targets else "## 单元测试"
        patch_targets.append(target)
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor=target,
            patch_markdown="## 加法\n\n例题：$1+1=2$，两个1相加得到2。" if target == "## 加法" else (_choice_test() if test_repair_valid else _choice_test().split("> [!ANSWER]", 1)[0]),
            covered_action_ids=["body" if target == "## 加法" else "test"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapters, updated, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter], review_actions=actions,
    )
    assert updated[0].status == "applied", "已修好的正文不应因另一待修块的旧错误被丢弃。"
    assert patch_targets == ["## 加法", "## 单元测试"]
    assert (updated[1].status == "applied") == test_repair_valid
    assert bool(unresolved) != test_repair_valid
    report = build_merge_review_report(
        enhanced_chapters=[EnhancedChapterDraft.model_validate(chapters[0].model_dump())],
        expected_chapter_count=1, plan="", review_actions=updated,
    )
    assert any(issue.issue_type == "unresolved_review_error" for issue in report.issues) != test_repair_valid


@pytest.mark.anyio
@pytest.mark.parametrize("severity", ["warning", "error"])
async def test_repair_applies_final_content_with_one_model_call(monkeypatch, severity):
    calls = []

    async def completion(_messages, **kwargs):
        calls.append(kwargs["response_model"])
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 加法", patch_markdown="## 加法\n\n相加得到和。",
            covered_action_ids=["a1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapter = ReviewedChapterDraft(chapter_index=1, title="算术", markdown="# 算术\n\n## 加法\n\n旧内容。")
    action = ReviewAction(action_id="a1", action_type="section_patch", chapter_index=1, severity=severity, target_anchor="## 加法")
    _, updated, unresolved, _ = await repair.repair_or_route_review_actions(reviewed_chapters=[chapter], review_actions=[action])
    assert calls == [repair._LocalMarkdownPatch]
    assert updated[0].status == "applied" and not unresolved


@pytest.mark.anyio
@pytest.mark.parametrize("first_response", ["timeout", "no_change"])
async def test_required_repair_recovers_in_place_from_unusable_response(monkeypatch, first_response):
    calls = []

    async def completion(messages, **kwargs):
        calls.append(kwargs["response_model"])
        if len(calls) == 1:
            if first_response == "timeout":
                raise TimeoutError("temporary repair timeout")
            return repair._LocalMarkdownPatch(status="no_change")
        assert "重试" in messages[1]["content"] or "尚未修改" in messages[1]["content"]
        return repair._LocalMarkdownPatch(
            operation="replace_text", original_text="$1+1=3$", patch_markdown="$1+1=2$",
            covered_action_ids=["a1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapter = ReviewedChapterDraft(chapter_index=1, title="算术", markdown="# 算术\n\n## 加法\n\n$1+1=3$。")
    action = ReviewAction(action_id="a1", action_type="section_patch", chapter_index=1, severity="error", target_anchor="## 加法")
    repaired, actions, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter], review_actions=[action],
    )
    assert calls == [repair._LocalMarkdownPatch] * 2
    assert actions[0].status == "applied" and not unresolved
    assert repaired[0].markdown == chapter.markdown.replace("$1+1=3$", "$1+1=2$")


@pytest.mark.anyio
@pytest.mark.parametrize("action_type", ["evidence_patch", "record_only", "re_dispatch", "rebuild_backbone"])
async def test_chapter_content_errors_are_repaired_instead_of_only_recorded(monkeypatch, action_type):
    calls = []

    async def completion(_messages, **kwargs):
        calls.append(kwargs["response_model"])
        return repair._LocalMarkdownPatch(
            operation="replace_text", original_text="$1+1=3$", patch_markdown="$1+1=2$",
            covered_action_ids=["a1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapter = ReviewedChapterDraft(chapter_index=1, title="算术", markdown="# 算术\n\n## 加法\n\n$1+1=3$。")
    action = ReviewAction(action_id="a1", action_type=action_type, chapter_index=1, severity="error", target_anchor="## 加法")
    repaired, actions, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter], review_actions=[action],
    )
    assert calls == [repair._LocalMarkdownPatch]
    assert actions[0].status == "applied" and not unresolved
    report = build_merge_review_report(
        enhanced_chapters=[EnhancedChapterDraft.model_validate(repaired[0].model_dump())],
        expected_chapter_count=1, plan="", review_actions=actions,
    )
    assert report.passed
    assert "$1+1=3$" not in repaired[0].markdown


@pytest.mark.anyio
@pytest.mark.parametrize("inline_count,severity,applied", [
    (0, "error", True),
    (None, "error", False),
    (1, "error", False),
    (0, "warning", False),
])
async def test_remove_extra_body_question_only_with_zero_contract(
    monkeypatch, inline_count, severity, applied,
):
    monkeypatch.setattr(repair, "_MAX_LLM_PATCH_ATTEMPTS_PER_TARGET", 1)
    body = "## 加法\n\n例题：$1+1=2$，逐项相加即可。"
    extra = "\n\n> [!QUESTION]\n> 计算 $2+2$。\n\n> [!ANSWER]\n> 答案：$4$。"
    chapter = ReviewedChapterDraft(
        chapter_index=1, title="算术", markdown="# 算术\n\n" + body + extra + "\n\n" + _choice_test(),
    )
    action = ReviewAction(
        action_id="a1", action_type="section_patch", chapter_index=1, severity=severity,
        target_anchor="## 加法", instruction="删除正文额外题答块，保留例题和正式单元测试。",
    )

    async def completion(messages, **kwargs):
        assert "零正文练习合同优先" in messages[1]["content"]
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 加法", patch_markdown=body,
            covered_action_ids=["a1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapters, updated, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter], review_actions=[action],
        chapter_tasks=[{"chapter_index": 1, "quantity_constraints": {"inline_practice_count": inline_count}}],
    )
    assert (updated[0].status == "applied") == applied
    assert bool(unresolved) != applied
    if applied:
        final_body, final_test = unit_tests.split_final_unit_test_section(chapters[0].markdown)
        assert "例题：$1+1=2$" in final_body
        assert "[!QUESTION]" not in final_body
        assert final_test == _choice_test().strip()
    else:
        assert chapters[0].markdown == chapter.markdown
