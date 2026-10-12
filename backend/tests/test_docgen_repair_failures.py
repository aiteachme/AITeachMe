from __future__ import annotations

import ast
import re

import pytest

from app.workflows.digest.docgen.lib import repair, unit_tests
from app.workflows.digest.docgen.lib.models import EnhancedChapterDraft, ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.lib.quality import build_merge_review_report
from app.workflows.digest.docgen.lib.presentation_policy import normalize_docgen_presentation
from app.workflows.digest.docgen.prompts.repair import build_patch_verification_messages


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


def test_patch_review_contract_accepts_option_content_without_display_label():
    candidate = unit_tests.normalize_unit_test_choice_answers(_choice_test("A. $2$"))
    messages = build_patch_verification_messages(
        chapter_title="算术", actions=[], patch_markdown=candidate,
        related_markdown_context="", quantity_contract={},
    )
    assert "不含 A-D 选项编号" in messages[0]["content"]
    assert "缺少编号不构成答案错误" in messages[0]["content"]
    assert "> **答案**\n>\n> $2$" in messages[1]["content"]
    assert unit_tests.unit_test_structure_issues(candidate) == []


@pytest.mark.anyio
@pytest.mark.parametrize("explicit_length", [{}, {"min_word_count": 1200, "max_word_count": 1600}])
async def test_patch_review_receives_explicit_length_without_mode_budget(monkeypatch, explicit_length):
    monkeypatch.setattr(repair, "_MAX_LLM_PATCH_ATTEMPTS_PER_TARGET", 1)
    quantities = {"body_section_count": 1, "min_word_count": None, "max_word_count": None, **explicit_length}
    reviews = []

    async def completion(messages, **kwargs):
        if kwargs["response_model"] is repair._LocalPatchVerification:
            contract_text = messages[1]["content"].split("用户确认的数量与写作边界：\n", 1)[1].split("\n\n候选补丁", 1)[0]
            contract = ast.literal_eval(contract_text)
            assert "min_word_count" not in contract and "max_word_count" not in contract
            assert contract["quantity_constraints"] == quantities
            reviews.append(contract)
            return repair._LocalPatchVerification(
                passed=True, verified_action_ids=["a1"],
                verification_notes=["例题结果正确，数量及显式篇幅按整章正文核验；模式参考篇幅不阻断局部修补。"],
            )
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
    assert len(reviews) == 1
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
    patch_models = []

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
        patch_models.append(kwargs["model"])
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
    assert patch_models == ["primary", "reason"]
    assert updated[0].status == "applied"
    assert not unresolved
    assert "$-2 < 0$" not in chapters[0].markdown
    assert unit_tests.unit_test_structure_issues(chapters[0].markdown) == []


@pytest.mark.anyio
async def test_retry_retains_semantic_feedback_after_structural_rejection(monkeypatch):
    patch_models = []
    verifications = 0
    patch_feedback = []

    async def completion(messages, **kwargs):
        nonlocal verifications
        if kwargs["response_model"] is repair._LocalPatchVerification:
            verifications += 1
            if verifications == 1:
                return repair._LocalPatchVerification(
                    passed=False, verified_action_ids=[], issues=["Q01 的 A、C 都正确，不满足单选。"],
                    verification_notes=["必须排除两个正确选项。"],
                )
            return repair._LocalPatchVerification(
                passed=True, verified_action_ids=["a1"],
                verification_notes=["1+1=2，四个选项只有一个正确答案。"],
            )
        patch_models.append(kwargs["model"])
        patch_feedback.append(messages[1]["content"])
        if len(patch_models) == 1:
            markdown = _ambiguous_choice_test()
        elif len(patch_models) == 2:
            markdown = _choice_test("A。实际结果为 $2$")
        else:
            markdown = _choice_test()
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 单元测试",
            patch_markdown=markdown, covered_action_ids=["a1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapter = ReviewedChapterDraft(
        chapter_index=1, title="算术", markdown="# 算术\n\n## 加法\n\n正文保持。\n\n" + _choice_test("$3$"),
    )
    action = ReviewAction(
        action_id="a1", action_type="section_patch", chapter_index=1,
        severity="error", target_anchor="## 单元测试",
    )
    chapters, updated, unresolved, traces = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter], review_actions=[action],
    )
    assert patch_models == ["primary", "reason", "reason"]
    assert "Q01 的 A、C 都正确" in patch_feedback[-1], patch_feedback[-1]
    assert "题答合同" in patch_feedback[-1], patch_feedback[-1]
    assert verifications == 2, [trace.detail for trace in traces]
    assert updated[0].status == "applied"
    assert not unresolved
    assert "正文保持。" in chapters[0].markdown
    assert unit_tests.unit_test_structure_issues(chapters[0].markdown) == []


@pytest.mark.anyio
async def test_retry_can_fix_verified_error_elsewhere_in_the_same_test_block(monkeypatch):
    second = (
        _choice_test("$4$").replace("## 单元测试\n\n", "").replace("Q01", "Q02")
        .replace("计算 $1+1$。", "计算 $2+2$。")
        .replace("> - A. $2$", "> - A. $4$").replace("> - B. $-2$", "> - B. $-4$")
        .replace("> - C. $3$", "> - C. $5$").replace("> - D. $4$", "> - D. $6$")
        .replace("相加得到 $2$。", "相加得到 $4$。")
    )
    incorrect = _choice_test() + "\n" + second.replace("相加得到 $4$。", "相加得到 $5$。")
    corrected = _choice_test() + "\n" + second
    patch_calls = []

    async def completion(messages, **kwargs):
        if kwargs["response_model"] is repair._LocalPatchVerification:
            candidate = messages[1]["content"].split("候选补丁（必须完整核验）：\n", 1)[1].split("\n\n同章其它正文", 1)[0]
            if "相加得到 $5$。" in candidate:
                return repair._LocalPatchVerification(
                    passed=False, verified_action_ids=["a1"],
                    issues=["Q02解析错误：2+2等于4，不是5；这处错误也在当前完整替换块内。"],
                    verification_notes=["Q01已正确，Q02的答案为4但解析仍写5。"],
                )
            return repair._LocalPatchVerification(
                passed=True, verified_action_ids=["a1"],
                verification_notes=["两题均有四个不同选项，1+1=2、2+2=4，唯一答案与各步解析一致。"],
            )
        patch_calls.append(kwargs["model"])
        if len(patch_calls) > 1:
            assert "Q02解析错误" in messages[1]["content"]
            assert "同一完整替换块" in messages[0]["content"]
            assert "不得修改同章只读参考小节" in messages[0]["content"]
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 单元测试",
            patch_markdown=incorrect if len(patch_calls) == 1 else corrected,
            covered_action_ids=["a1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapter = ReviewedChapterDraft(
        chapter_index=1, title="算术", markdown="# 算术\n\n## 加法\n\n正文保持。\n\n" + incorrect,
    )
    action = ReviewAction(
        action_id="a1", chapter_index=1, action_type="section_patch", severity="error",
        target_anchor="## 单元测试", instruction="仅修改Q01的解析。",
    )
    # Make the first candidate differ from the existing block so it reaches verification.
    chapter = chapter.model_copy(update={"markdown": chapter.markdown.replace("相加得到 $2$。", "相加得到 $4$。", 1)})
    chapters, updated, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter], review_actions=[action],
    )
    assert patch_calls == ["primary", "reason"]
    assert updated[0].status == "applied"
    assert not unresolved
    assert "正文保持。" in chapters[0].markdown
    assert "相加得到 $5$。" not in chapters[0].markdown
    assert unit_tests.unit_test_structure_issues(chapters[0].markdown, expected_question_count=2) == []


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


@pytest.mark.anyio
@pytest.mark.parametrize("inline_count,severity,review_passed,applied", [
    (0, "error", True, True),
    (0, "error", False, False),
    (None, "error", True, False),
    (1, "error", True, False),
    (0, "warning", True, False),
])
async def test_remove_extra_body_question_only_with_zero_contract_and_independent_review(
    monkeypatch, inline_count, severity, review_passed, applied,
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
    reviews = []

    async def completion(messages, **kwargs):
        if kwargs["response_model"] is repair._LocalPatchVerification:
            reviews.append(messages)
            assert "例题：$1+1=2$" in messages[1]["content"]
            assert "Q01" in messages[1]["content"]
            return repair._LocalPatchVerification(
                passed=review_passed, verified_action_ids=["a1"] if review_passed else [],
                issues=[] if review_passed else ["补丁丢失了要求的例题讲解。"],
                verification_notes=["正文保留例题并删除额外题答块，正式单元测试保持一题。"],
            )
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
    assert bool(reviews) == (inline_count == 0 and severity == "error")
    assert (updated[0].status == "applied") == applied
    assert bool(unresolved) != applied
    if applied:
        final_body, final_test = unit_tests.split_final_unit_test_section(chapters[0].markdown)
        assert "例题：$1+1=2$" in final_body
        assert "[!QUESTION]" not in final_body
        assert final_test == _choice_test().strip()
    else:
        assert chapters[0].markdown == chapter.markdown
