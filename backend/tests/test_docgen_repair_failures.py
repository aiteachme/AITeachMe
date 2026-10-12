from __future__ import annotations

import ast

import pytest

from app.workflows.digest.docgen.lib import repair, unit_tests
from app.workflows.digest.docgen.lib.models import EnhancedChapterDraft, ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.lib.quality import build_merge_review_report


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


@pytest.mark.parametrize("answer", ["A. $-2$", "E", "$5$", "A\n> B", "A或B"])
def test_raw_choice_answer_normalization_preserves_invalid_or_ambiguous_answer(answer):
    markdown = _choice_test(answer)
    assert unit_tests.normalize_unit_test_choice_answers(markdown) == markdown


def test_choice_normalization_preserves_fenced_examples_and_non_choice_answers():
    fenced = "```markdown\n" + _choice_test("A") + "```\n\n"
    non_choice = _choice_test("A").replace("选择题", "短答题")
    markdown = fenced + non_choice
    assert unit_tests.normalize_unit_test_choice_answers(markdown) == markdown


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
        if kwargs["response_model"] is repair._LocalPatchVerification:
            payloads = ast.literal_eval(user.split("待复核动作：\n", 1)[1].split("\n\n用户确认", 1)[0])
            return repair._LocalPatchVerification(
                passed=True, verified_action_ids=[item["repair_action_key"] for item in payloads],
                verification_notes=["逐项核对候选替换内容与本章计算规则一致。"],
            )
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
        if kwargs["response_model"] is repair._LocalPatchVerification:
            return repair._LocalPatchVerification(
                passed=True, verified_action_ids=["a1"], verification_notes=["加法得到和，与上下文一致。"],
            )
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


def _ambiguous_choice_test() -> str:
    return _choice_test("$-6 < -2$").replace("计算 $1+1$。", "下列不等式中，正确的是哪一项？").replace(
        "> - A. $2$\n> - B. $-2$\n> - C. $3$\n> - D. $4$",
        "> - A. $-6 < -2$\n> - B. $-6 > 0$\n> - C. $-2 < 0$\n> - D. $0 < -6$",
    )


@pytest.mark.anyio
async def test_independent_review_rejects_ambiguous_patch_and_guides_next_attempt(monkeypatch):
    calls = []

    async def completion(messages, **kwargs):
        if kwargs["response_model"] is repair._LocalPatchVerification:
            calls.append("verify")
            if "$-2 < 0$" in messages[1]["content"]:
                return repair._LocalPatchVerification(
                    passed=False, verified_action_ids=[], issues=["Q01 的 A、C 都正确，不满足单选。"],
                    verification_notes=["-6 在 -2 左侧，-2 在 0 左侧，所以两项都成立。"],
                )
            return repair._LocalPatchVerification(
                passed=True, verified_action_ids=["a1"], verification_notes=["1+1=2，其余三个选项均不等于2。"],
            )
        calls.append("patch")
        if calls.count("patch") == 1:
            markdown = _ambiguous_choice_test()
        else:
            assert "Q01 的 A、C 都正确" in messages[1]["content"]
            markdown = _choice_test()
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 单元测试",
            patch_markdown=markdown, covered_action_ids=["a1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapter = ReviewedChapterDraft(chapter_index=1, title="算术", markdown="# 算术\n\n## 加法\n\n$1+1=2$。\n\n" + _choice_test("$3$"))
    action = ReviewAction(action_id="a1", action_type="section_patch", chapter_index=1, severity="error", target_anchor="## 单元测试")
    chapters, updated, unresolved, _ = await repair.repair_or_route_review_actions(reviewed_chapters=[chapter], review_actions=[action])
    assert calls == ["patch", "verify", "patch", "verify"]
    assert updated[0].status == "applied"
    assert not unresolved
    assert "$-2 < 0$" not in chapters[0].markdown
    assert unit_tests.unit_test_structure_issues(chapters[0].markdown) == []


@pytest.mark.anyio
@pytest.mark.parametrize("review_result", [
    TimeoutError("独立审核超时"),
    {"passed": False, "verified_action_ids": [], "issues": ["A 和 C 都正确，单选不成立。"]},
    {"passed": True, "verified_action_ids": [], "verification_notes": ["没有完整核对修补动作。"]},
    {"passed": True, "verified_action_ids": ["a1"], "issues": ["答案仍有矛盾。"], "verification_notes": ["发现未解决问题。"]},
    {"passed": True, "verified_action_ids": ["a1"], "verification_notes": []},
])
async def test_unverified_error_patch_cannot_replace_chapter_or_pass_publication(monkeypatch, review_result):
    monkeypatch.setattr(repair, "_MAX_LLM_PATCH_ATTEMPTS_PER_TARGET", 1)

    async def completion(_messages, **kwargs):
        if kwargs["response_model"] is repair._LocalPatchVerification:
            if isinstance(review_result, Exception):
                raise review_result
            return review_result
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 单元测试",
            patch_markdown=_ambiguous_choice_test(), covered_action_ids=["a1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapter = ReviewedChapterDraft(chapter_index=1, title="算术", markdown="# 算术\n\n## 加法\n\n正文。\n\n" + _choice_test("$3$"))
    action = ReviewAction(action_id="a1", action_type="section_patch", chapter_index=1, severity="error", target_anchor="## 单元测试")
    chapters, updated, unresolved, traces = await repair.repair_or_route_review_actions(reviewed_chapters=[chapter], review_actions=[action])
    assert chapters[0].markdown == chapter.markdown
    assert updated[0].status != "applied"
    assert unresolved and all(not trace.changed for trace in traces)
    report = build_merge_review_report(
        enhanced_chapters=[EnhancedChapterDraft(chapter_index=1, title=chapter.title, markdown=chapters[0].markdown)],
        expected_chapter_count=1, plan="", review_actions=updated,
    )
    assert not report.passed
    assert report.decision == "fail"
    assert any(issue.issue_type == "unresolved_review_error" for issue in report.issues)


@pytest.mark.anyio
async def test_warning_patch_does_not_require_extra_error_verification(monkeypatch):
    calls = []

    async def completion(_messages, **kwargs):
        calls.append(kwargs["response_model"])
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 加法", patch_markdown="## 加法\n\n相加得到和。",
            covered_action_ids=["a1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapter = ReviewedChapterDraft(chapter_index=1, title="算术", markdown="# 算术\n\n## 加法\n\n旧内容。")
    action = ReviewAction(action_id="a1", action_type="section_patch", chapter_index=1, severity="warning", target_anchor="## 加法")
    _, updated, unresolved, _ = await repair.repair_or_route_review_actions(reviewed_chapters=[chapter], review_actions=[action])
    assert calls == [repair._LocalMarkdownPatch]
    assert updated[0].status == "applied" and not unresolved
