"""Keep explicit chapter-end quantities during whole-test replacement patches."""

from __future__ import annotations

import re

import pytest

from app.workflows.digest.docgen.lib import repair
from app.workflows.digest.docgen.lib.models import ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestItem,
    ChapterUnitTestSet,
    append_unit_test_markdown,
    render_unit_test_markdown,
    unit_test_structure_issues,
)


def _quiz(question_count: int, *, start: int = 0) -> str:
    rendered = render_unit_test_markdown(
        ChapterUnitTestSet(items=[
            ChapterUnitTestItem(
                type="填空题", target=f"整数加法{i}", stem=f"整数 {i} 加一是多少？",
                answer=str(i + 1), basis=f"{i}+1={i + 1}。",
            ) for i in range(start, start + question_count)
        ]),
        title="整数加法", min_items=question_count, max_items=question_count,
        fallback_targets=[],
    )
    return re.sub(r"Q(\d+)｜", lambda match: f"Q{int(match.group(1)) + start:02d}｜", rendered)


def _chapter(question_count: int) -> ReviewedChapterDraft:
    return ReviewedChapterDraft(
        chapter_index=1, title="整数加法",
        markdown=append_unit_test_markdown("# 整数加法\n\n## 加一\n整数加一。\n", _quiz(question_count)),
    )


def _action() -> ReviewAction:
    return ReviewAction(
        action_type="section_patch", chapter_index=1, severity="error",
        target_anchor="## 单元测试", reason="需要修正章末题目。",
        instruction="修正题目并保留用户明确要求的题数。",
    )


@pytest.mark.anyio
@pytest.mark.parametrize("original_count,replacement_count,expected_count,accepted", [
    (5, 9, 5, False),
    (9, 5, 5, True),
    (5, 9, None, True),
])
async def test_unit_test_patch_respects_explicit_quantity(
    monkeypatch, original_count, replacement_count, expected_count, accepted,
) -> None:

    async def fake_patch(_messages, **kwargs):
        return repair._LocalMarkdownPatch(
            status="patch", operation="replace_section", target_anchor="## 单元测试",
            patch_markdown=_quiz(replacement_count),
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_patch)
    original = _chapter(original_count)
    quantities = {} if expected_count is None else {"chapter_end_question_count": expected_count}
    updated, results, remaining = await repair._apply_llm_patch_actions(
        chapter=original, indexed_actions=[(1, _action())], repair_round=1,
        quantity_contract={"quantity_constraints": quantities},
    )
    assert results[0][1].status == ("applied" if accepted else "downgraded")
    assert bool(remaining) is (not accepted)
    if accepted:
        assert updated.markdown.count("> [!QUESTION]") == replacement_count
        assert unit_test_structure_issues(updated.markdown, expected_question_count=expected_count) == []
    else:
        assert updated.markdown == original.markdown
        assert "必须恰好有 5 道题，当前为 9 道" in results[0][2].detail


@pytest.mark.anyio
async def test_quantity_rejection_retries_before_marking_action_applied(monkeypatch) -> None:
    patch_prompts = []

    async def fake_patch(messages, **kwargs):
        patch_prompts.append(messages[-1]["content"])
        return repair._LocalMarkdownPatch(
            status="patch", operation="replace_section", target_anchor="## 单元测试",
            patch_markdown=_quiz(9 if len(patch_prompts) == 1 else 5),
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_patch)
    repaired, actions, unresolved, trace = await repair.repair_or_route_review_actions(
        reviewed_chapters=[_chapter(5)], review_actions=[_action()],
        chapter_tasks=[{"chapter_index": 1, "quantity_constraints": {"chapter_end_question_count": 5}}],
    )
    assert len(patch_prompts) == 2
    assert "必须恰好有 5 道题，当前为 9 道" in patch_prompts[1]
    assert actions[0].status == "applied"
    assert unresolved == []
    assert trace[0].changed is True
    assert unit_test_structure_issues(repaired[0].markdown, expected_question_count=5) == []


@pytest.mark.anyio
async def test_body_append_cannot_change_valid_explicit_chapter_end_quantity(monkeypatch) -> None:

    async def fake_patch(_messages, **kwargs):
        return repair._LocalMarkdownPatch(
            operation="append", target_anchor="## 单元测试",
            patch_markdown="> [!QUESTION]" + _quiz(4, start=5).split("> [!QUESTION]", 1)[1],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_patch)
    original = _chapter(5)
    action = ReviewAction(
        action_type="section_patch", chapter_index=1, severity="warning",
        target_anchor="## 加一", reason="需要新增练习题目。",
        instruction="补充练习并给出正确答案。",
    )
    updated, results, remaining = await repair._apply_llm_patch_actions(
        chapter=original, indexed_actions=[(1, action)], repair_round=1,
        quantity_contract={"quantity_constraints": {"chapter_end_question_count": 5}},
    )
    assert updated.markdown == original.markdown
    assert results[0][1].status == "downgraded"
    assert "必须恰好有 5 道题，当前为 9 道" in results[0][2].detail
    assert remaining


@pytest.mark.anyio
async def test_body_fix_can_precede_correction_of_existing_wrong_chapter_end_count(monkeypatch) -> None:
    async def fake_patch(_messages, **kwargs):
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 加一",
            patch_markdown="## 加一\n\n整数加一得到下一个整数。",
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_patch)
    action = ReviewAction(
        action_type="section_patch", chapter_index=1, severity="error",
        target_anchor="## 加一", reason="纠正正文概念。", instruction="纠正加一的解释。",
    )
    updated, results, remaining = await repair._apply_llm_patch_actions(
        chapter=_chapter(9), indexed_actions=[(1, action)], repair_round=1,
        quantity_contract={"quantity_constraints": {"chapter_end_question_count": 5}},
    )
    assert results[0][1].status == "applied"
    assert not remaining
    assert "得到下一个整数" in updated.markdown
    assert updated.markdown.count("> [!QUESTION]") == 9


@pytest.mark.anyio
async def test_body_question_cleanup_and_chapter_end_count_fix_can_run_in_order(monkeypatch) -> None:
    patch_calls = []

    async def fake_patch(_messages, **kwargs):
        key = "body" if not patch_calls else "quiz"
        patch_calls.append(key)
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 加一" if key == "body" else "## 单元测试",
            patch_markdown="## 加一\n\n整数加一。" if key == "body" else _quiz(5),
            covered_action_ids=[key],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_patch)
    original = _chapter(9)
    original = original.model_copy(update={"markdown": original.markdown.replace(
        "整数加一。", "整数加一。\n\n> [!QUESTION]\n> 计算100+1。\n\n> [!ANSWER]\n> 答案：101。", 1,
    )})
    body_action = ReviewAction(
        action_id="body", action_type="section_patch", chapter_index=1, severity="error",
        target_anchor="## 加一", reason="用户明确要求正文不安排练习。", instruction="移除正文练习。",
    )
    quiz_action = _action().model_copy(update={"action_id": "quiz"})
    repaired, actions, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[original], review_actions=[body_action, quiz_action],
        chapter_tasks=[{
            "chapter_index": 1,
            "quantity_constraints": {"inline_practice_count": 0, "chapter_end_question_count": 5},
        }],
    )
    assert patch_calls == ["body", "quiz"]
    assert [action.status for action in actions] == ["applied", "applied"]
    assert unresolved == []
    assert repaired[0].markdown.count("> [!QUESTION]") == 5
    assert unit_test_structure_issues(repaired[0].markdown, expected_question_count=5) == []
