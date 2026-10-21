"""Large-test repairs cannot rewrite untouched questions or start another review loop."""

from __future__ import annotations

import pytest

from app.workflows.digest.docgen.lib import repair
from app.workflows.digest.docgen.lib.models import ReviewAction, ReviewedChapterDraft
from app.workflows.digest.docgen.lib.unit_test_repair import (
    UnitTestQuestionPatch, UnitTestQuestionPatches, unit_test_question_blocks,
)
from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestItem, ChapterUnitTestSet, append_unit_test_markdown,
    render_unit_test_markdown, split_final_unit_test_section, unit_test_structure_issues,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _item(number: int, *, answer: str | None = None, kind: str = "填空题") -> ChapterUnitTestItem:
    return ChapterUnitTestItem(
        type=kind, target=f"整数{number}加一", stem=f"整数{number}加1等于____。",
        answer=answer or str(number + 1),
        basis=f"从整数{number}起增加1，得到{number + 1}。" * 5,
    )


def _case(count: int, *, compact: bool = False):
    items = [_item(i) for i in range(1, count + 1)]
    items[count - 2].answer = "999"
    # Markers inside a code example must not become replacement locations.
    items[1].stem = "阅读代码后填写输出：\n```python\nprint('> [!QUESTION]')\n```"
    items[1].answer = "`> [!QUESTION]`"
    items[1].basis = "print 输出字符串本身。"
    quiz = render_unit_test_markdown(
        ChapterUnitTestSet(items=items), title="整数加法", min_items=count,
        max_items=count, fallback_targets=[],
    )
    if compact:
        quiz = "\n".join(line for line in quiz.splitlines() if line.strip())
    chapter = ReviewedChapterDraft(
        chapter_index=1, title="整数加法",
        markdown=append_unit_test_markdown("# 整数加法\n\n## 加一\n\n整数加一。", quiz),
    )
    action = ReviewAction(
        action_id="fix-answer", action_type="section_patch", chapter_index=1,
        severity="error", target_anchor="## 单元测试",
        instruction=f"核对并修正 Q{count - 1:02d} 的答案和解析，保留其它题目。",
    )
    contract = {
        "quantity_constraints": {"chapter_end_question_count": count},
        "chapter_end_practice_plan": [
            {"target": "整数加法", "question_type": "填空题", "question_count": count},
        ],
    }
    return chapter, action, contract


@pytest.mark.anyio
@pytest.mark.parametrize("count", [13, 20, 40])
@pytest.mark.parametrize("compact", [False, True])
async def test_selective_repair_retries_bad_numbers_and_type_drift_without_rewriting_other_questions(monkeypatch, count, compact):
    chapter, action, contract = _case(count, compact=compact)
    assert len(repair._question_callout_records(chapter.markdown)) == count
    target = count - 1
    prompts = []

    async def completion(messages, **kwargs):
        assert kwargs["response_model"] is UnitTestQuestionPatches
        assert kwargs["max_tokens"] >= 10000
        prompts.append(messages[-1]["content"])
        assert f"Q{count:02d}" in prompts[-1] and "中间内容已截断" not in prompts[-1]
        return UnitTestQuestionPatches(
            patches=[UnitTestQuestionPatch(
                question_number=count + 1 if len(prompts) == 1 else target,
                item=_item(target, kind="短答题" if len(prompts) == 2 else "填空题"),
            )], covered_action_ids=[action.action_id],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    updated, results, remaining = await repair._apply_llm_patch_actions(
        chapter=chapter, indexed_actions=[(1, action)], repair_round=1, quantity_contract=contract,
    )
    assert updated.markdown == chapter.markdown and remaining
    assert "Invalid" in results[0][2].detail
    chapters, actions, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter], review_actions=[action], chapter_tasks=[{"chapter_index": 1, **contract}],
    )
    assert len(prompts) == 3
    assert "题型配额" in prompts[-1]
    assert actions[0].status == "applied" and not unresolved
    original_body, original_test = split_final_unit_test_section(chapter.markdown)
    body, quiz = split_final_unit_test_section(chapters[0].markdown)
    assert body == original_body
    _, original_blocks = unit_test_question_blocks(original_test)
    _, blocks = unit_test_question_blocks(quiz)
    assert list(blocks) == list(original_blocks)
    assert {number: (blocks[number], original_blocks[number]) for number in blocks
            if number != target and blocks[number] != original_blocks[number]} == {}
    assert unit_test_structure_issues(quiz, expected_question_count=count) == []


@pytest.mark.anyio
async def test_selective_repair_delivers_final_answer_with_one_model_call(monkeypatch):
    chapter, action, contract = _case(20)
    calls = []

    async def completion(_messages, **kwargs):
        calls.append(kwargs["response_model"])
        return UnitTestQuestionPatches(
            patches=[UnitTestQuestionPatch(question_number=19, item=_item(19))],
            covered_action_ids=[action.action_id],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapters, actions, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[chapter], review_actions=[action], chapter_tasks=[{"chapter_index": 1, **contract}],
    )
    assert calls == [UnitTestQuestionPatches]
    assert actions[0].status == "applied" and not unresolved
    original_body, original_test = split_final_unit_test_section(chapter.markdown)
    body, quiz = split_final_unit_test_section(chapters[0].markdown)
    _, original = unit_test_question_blocks(original_test)
    _, updated = unit_test_question_blocks(quiz)
    assert body == original_body
    assert [number for number in original if original[number] != updated[number]] == [19]
    assert "999" not in updated[19] and "20" in updated[19]
