"""Repair a unique source fragment without leaving the original error behind."""

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
    split_final_unit_test_section,
    unit_test_structure_issues,
)


TITLE = "整数减法"
ANCHOR = "## 整数减法"
TABLE_HEADER = "| 考点 | 重要程度 | 题型或任务场景 | 抓手 |"
OLD_ROW = "| 相反数、绝对值与符号 | 核心 | 判断相反数、确定结果符号 | 减数不变，先取相反数 |"
NEW_ROW = "| 相反数、绝对值与符号 | 核心 | 判断相反数、确定结果符号 | **被减数保持不变，减数取相反数后改为加法** |"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _chapter(*, duplicate_source: bool = False, extra_body: str = "") -> ReviewedChapterDraft:
    body = (
        f"# {TITLE}\n\n{TABLE_HEADER}\n|---|---|---|---|\n{OLD_ROW}\n\n"
        f"{ANCHOR}\n\n减去一个数，等于加上这个数的相反数。\n\n"
        "### 计算检查\n\n被减数不变，只对减数取相反数。\n"
    )
    if duplicate_source:
        body += f"\n{TABLE_HEADER}\n|---|---|---|---|\n{OLD_ROW}\n"
    if extra_body:
        body += f"\n{extra_body}\n"
    quiz = render_unit_test_markdown(
        ChapterUnitTestSet(items=[
            ChapterUnitTestItem(
                type="填空题", target=f"减法检查{i}", stem=f"计算 {i}－1。",
                answer=str(i - 1), basis=f"{i}－1＝{i - 1}。",
            ) for i in range(1, 10)
        ]),
        title=TITLE, min_items=9, max_items=9, fallback_targets=[],
    )
    return ReviewedChapterDraft(
        chapter_index=2, title=TITLE,
        markdown=append_unit_test_markdown(body, quiz),
    )


def _action() -> ReviewAction:
    return ReviewAction(
        action_id="A3", action_type="section_patch", chapter_index=2, severity="error",
        target_anchor=ANCHOR,
        reason="章首考点表错误指定了减法转化时保持不变的对象。",
        instruction="仅修正章首考点表中的对象对应关系，使其与减法转加法公式及后文步骤一致。",
        constraints=["保持原有章节边界、教学小节数量及9道章末题。"],
    )


async def _apply(monkeypatch, chapter, *, operation="replace_text", original_text=OLD_ROW, replacement=NEW_ROW):
    verification_messages = []

    async def completion(messages, **kwargs):
        if kwargs["response_model"] is repair._LocalPatchVerification:
            verification_messages.append(messages)
            return repair._LocalPatchVerification(
                passed=True, verified_action_ids=["A3"],
                verification_notes=["减法转化保持被减数不变，减数取相反数。"],
            )
        return repair._LocalMarkdownPatch(
            operation=operation, original_text=original_text,
            target_anchor=ANCHOR, patch_markdown=replacement, covered_action_ids=["A3"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    updated, results, remaining = await repair._apply_llm_patch_actions(
        chapter=chapter, indexed_actions=[(1, _action())], repair_round=1,
        quantity_contract={"quantity_constraints": {"chapter_end_question_count": 9}},
    )
    return updated, results, remaining, verification_messages


@pytest.mark.anyio
async def test_error_append_cannot_hide_unchanged_intro_error_even_if_verifier_always_passes(monkeypatch):
    original = _chapter()
    updated, results, remaining, verification_messages = await _apply(
        monkeypatch, original, operation="append",
    )

    assert updated.markdown == original.markdown
    assert results[0][1].status == "downgraded"
    assert remaining
    assert verification_messages == []
    assert OLD_ROW in updated.markdown and NEW_ROW not in updated.markdown


@pytest.mark.anyio
async def test_unique_intro_table_row_is_replaced_in_place_despite_body_heading_anchor(monkeypatch):
    original = _chapter()
    updated, results, remaining, verification_messages = await _apply(monkeypatch, original)

    assert results[0][1].status == "applied"
    assert not remaining and len(verification_messages) == 1
    assert OLD_ROW not in updated.markdown
    assert updated.markdown.count(NEW_ROW) == 1
    assert updated.markdown.index(NEW_ROW) < updated.markdown.index(ANCHOR)
    assert updated.markdown == original.markdown.replace(OLD_ROW, NEW_ROW, 1)
    assert re.findall(r"(?m)^#{1,6}\s+.+$", updated.markdown) == re.findall(
        r"(?m)^#{1,6}\s+.+$", original.markdown,
    )
    assert split_final_unit_test_section(updated.markdown)[1] == split_final_unit_test_section(original.markdown)[1]
    assert unit_test_structure_issues(updated.markdown, expected_question_count=9) == []


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["missing", "whitespace_mismatch", "duplicate", "empty", "blank", "oversize", "h1", "h2", "unit_test"])
async def test_unsafe_or_ambiguous_original_fragment_is_rejected_without_verification(monkeypatch, case):
    oversized = "只用于检验局部替换上限。" * (repair._MAX_LOCAL_PATCH_CHARS // 10 + 1)
    original = _chapter(duplicate_source=case == "duplicate", extra_body=oversized if case == "oversize" else "")
    sources = {
        "missing": "不存在的旧错误",
        "whitespace_mismatch": OLD_ROW + " ",
        "duplicate": OLD_ROW,
        "empty": "",
        "blank": "\n\n",
        "oversize": oversized,
        "h1": f"# {TITLE}\n\n{TABLE_HEADER}",
        "h2": f"{ANCHOR}\n\n减去一个数，等于加上这个数的相反数。",
        "unit_test": "计算 1－1。",
    }
    updated, results, remaining, verification_messages = await _apply(
        monkeypatch, original, original_text=sources[case],
    )

    assert updated.markdown == original.markdown
    assert results[0][1].status == "downgraded"
    assert remaining
    assert verification_messages == []


@pytest.mark.anyio
async def test_verification_receives_operation_before_and_actual_after_at_original_location(monkeypatch):
    original = _chapter()
    captured = []
    build_messages = repair.build_patch_verification_messages

    def capture_messages(**kwargs):
        captured.append(kwargs)
        return build_messages(**kwargs)

    monkeypatch.setattr(repair, "build_patch_verification_messages", capture_messages)
    updated, results, remaining, _ = await _apply(monkeypatch, original)

    assert results[0][1].status == "applied" and not remaining
    assert len(captured) == 1
    payload = captured[0]
    assert payload["operation"] == "replace_text"
    assert OLD_ROW in payload["original_markdown"]
    after = payload["patched_markdown_context"]
    assert TABLE_HEADER in after and NEW_ROW in after
    assert OLD_ROW not in after
    assert OLD_ROW not in payload["related_markdown_context"]
    assert OLD_ROW not in updated.markdown


@pytest.mark.anyio
@pytest.mark.parametrize("recover", [False, True])
async def test_rejected_error_append_retries_with_feedback_and_cannot_be_marked_applied_on_exhaustion(monkeypatch, recover):
    patch_messages = []
    verification_calls = []

    async def completion(messages, **kwargs):
        if kwargs["response_model"] is repair._LocalPatchVerification:
            verification_calls.append(messages)
            return repair._LocalPatchVerification(
                passed=True, verified_action_ids=["A3"],
                verification_notes=["原位修正了保持不变的对象。"],
            )
        patch_messages.append(messages)
        return repair._LocalMarkdownPatch(
            operation="replace_text" if recover and len(patch_messages) > 1 else "append",
            original_text=OLD_ROW, patch_markdown=NEW_ROW, target_anchor=ANCHOR,
            covered_action_ids=["A3"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    monkeypatch.setattr(repair, "_MAX_LLM_PATCH_ATTEMPTS_PER_TARGET", 2)
    original = _chapter()
    chapters, actions, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[original], review_actions=[_action()],
        chapter_tasks=[{"chapter_index": 2, "quantity_constraints": {"chapter_end_question_count": 9}}],
    )

    assert len(patch_messages) == 2
    assert "append" in patch_messages[1][-1]["content"]
    assert len(verification_calls) == int(recover)
    if recover:
        assert actions[0].status == "applied" and not unresolved
        assert OLD_ROW not in chapters[0].markdown
        assert chapters[0].markdown.index(NEW_ROW) < chapters[0].markdown.index(ANCHOR)
    else:
        assert actions[0].status == "downgraded" and unresolved
        assert chapters[0].markdown == original.markdown
