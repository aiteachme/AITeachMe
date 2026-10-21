"""Keep explicit question-type allocations through document repair and publication."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from app.shared.infra.storage import build_course_storage_scope
from app.workflows.digest.docgen.lib import publish, repair
from app.workflows.digest.docgen.lib.models import (
    ChapterGenerationTask,
    EnhancedChapterDraft,
    ReviewAction,
    ReviewedChapterDraft,
)
from app.workflows.digest.docgen.lib.quantity_contracts import ChapterQuantityContractError
from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestItem,
    ChapterUnitTestSet,
    append_unit_test_markdown,
    markdown_unit_test_type_quota_issues,
    render_unit_test_markdown,
)
from app.workflows.digest.docgen.nodes.merge_review import _chapter_metadata


TITLE = "整数加法"
EXPECTED_TYPES = ["应用迁移"] * 4 + ["填空题"] * 5
DRIFTED_TYPES = ["应用迁移"] * 3 + ["错因辨析"] + ["填空题"] * 5


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _plan():
    return [
        {"target": "整数加法情境应用", "question_count": 4, "question_type": "应用迁移"},
        {"target": "整数加法短测", "question_count": 5, "question_type": "填空题"},
    ]


def _quiz(types, *, corrected=False):
    return render_unit_test_markdown(
        ChapterUnitTestSet(items=[
            ChapterUnitTestItem(
                type=kind, target=f"整数加法考点{i}", stem=f"账户原有{i}元，收入1元，现有多少元？",
                answer=str(i + 1), basis=f"{i}+1={i + 1}。" + ("收入记为正数。" if corrected else ""),
            ) for i, kind in enumerate(types, start=1)
        ]), title=TITLE, min_items=9, max_items=9, fallback_targets=[],
    )


def _chapter(types=None):
    return ReviewedChapterDraft(
        chapter_index=1, title=TITLE,
        markdown=append_unit_test_markdown(
            f"# {TITLE}\n\n## 加一\n\n整数加一。",
            _quiz(EXPECTED_TYPES if types is None else types),
        ),
    )


def _task(plan=None):
    return {
        "chapter_index": 1,
        "quantity_constraints": {"chapter_end_question_count": 9},
        "chapter_end_practice_plan": _plan() if plan is None else plan,
    }


def _action():
    return ReviewAction(
        action_id="A1", action_type="section_patch", chapter_index=1, severity="error",
        target_anchor="## 单元测试", reason="章末解析需要纠正。",
        instruction="修正章末解析，保留4道应用迁移与5道填空题。",
    )


@pytest.mark.anyio
@pytest.mark.parametrize("recover", [True, False])
async def test_document_quiz_patch_retries_type_drift_then_recovers_or_stays_unresolved(monkeypatch, recover):
    prompts = []

    async def completion(messages, **kwargs):
        prompts.append(messages[-1]["content"])
        types = EXPECTED_TYPES if recover and len(prompts) > 1 else DRIFTED_TYPES
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 单元测试",
            patch_markdown=_quiz(types, corrected=True), covered_action_ids=["A1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    original = _chapter()
    chapters, actions, unresolved, trace = await repair.repair_or_route_review_actions(
        reviewed_chapters=[original], review_actions=[_action()], chapter_tasks=[_task()],
    )

    assert len(prompts) == (2 if recover else 3)
    assert "应用迁移" in prompts[1] and "4" in prompts[1] and "3" in prompts[1]
    assert actions[0].status == ("applied" if recover else "downgraded")
    assert bool(unresolved) is (not recover)
    assert trace[0].changed is recover
    if recover:
        assert chapters[0].markdown.count("｜应用迁移｜") == 4
        assert chapters[0].markdown.count("｜填空题｜") == 5
        assert "收入记为正数" in chapters[0].markdown
    else:
        assert chapters[0].markdown == original.markdown


@pytest.mark.anyio
@pytest.mark.parametrize("untyped_plan", [[], [{"target": "练习", "question_count": 9}],
                                         [{"target": "练习", "question_count": 9, "question_type": None}]])
async def test_untyped_legacy_plan_keeps_legitimate_document_review_relabeling(monkeypatch, untyped_plan):
    calls = []

    async def completion(_messages, **kwargs):
        calls.append(kwargs["response_model"])
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 单元测试",
            patch_markdown=_quiz(DRIFTED_TYPES, corrected=True), covered_action_ids=["A1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    chapters, actions, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[_chapter()], review_actions=[_action()], chapter_tasks=[_task(untyped_plan)],
    )
    assert calls == [repair._LocalMarkdownPatch]
    assert actions[0].status == "applied" and not unresolved
    assert chapters[0].markdown.count("｜应用迁移｜") == 3
    assert chapters[0].markdown.count("｜错因辨析｜") == 1


@pytest.mark.anyio
async def test_body_fix_may_precede_separate_correction_of_existing_wrong_type_quota(monkeypatch):
    async def completion(_messages, **kwargs):
        return repair._LocalMarkdownPatch(
            operation="replace_section", target_anchor="## 加一",
            patch_markdown="## 加一\n\n整数加一得到下一个整数。", covered_action_ids=["A1"],
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", completion)
    original = _chapter(DRIFTED_TYPES)
    action = _action().model_copy(update={
        "target_anchor": "## 加一", "reason": "正文概念需要纠正。", "instruction": "纠正加一的解释。",
    })
    chapters, actions, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[original], review_actions=[action], chapter_tasks=[_task()],
    )
    assert actions[0].status == "applied" and not unresolved
    assert "整数加一得到下一个整数。" in chapters[0].markdown
    assert chapters[0].markdown.count("｜应用迁移｜") == 3
    assert chapters[0].markdown.count("｜错因辨析｜") == 1


@pytest.mark.parametrize("explicit_quota", [True, False])
def test_final_markdown_gate_rejects_type_drift_only_when_requested(explicit_quota):
    kwargs = {
        "title": TITLE, "quantity_constraints": {"chapter_end_question_count": 9},
        "chapter_end_practice_plan": _plan() if explicit_quota else [],
    }
    markdown = _chapter(DRIFTED_TYPES).markdown
    if explicit_quota:
        with pytest.raises(ChapterQuantityContractError, match="应用迁移"):
            publish._prepare_chapter_markdown(markdown, **kwargs)
    else:
        prepared = publish._prepare_chapter_markdown(markdown, **kwargs)
        assert prepared.count("｜应用迁移｜") == 3
        assert prepared.count("｜错因辨析｜") == 1


@pytest.mark.parametrize("multiline_header", [True, False])
def test_type_quota_reads_only_real_final_question_headers_and_ignores_body_and_code(multiline_header):
    markdown = _chapter().markdown
    if multiline_header:
        markdown = markdown.replace("> [!QUESTION] **Q", "> [!QUESTION]\n>\n> **Q")
    prepared = publish._prepare_chapter_markdown(
        markdown, title=TITLE, chapter_end_practice_plan=_plan(),
        quantity_constraints={"chapter_end_question_count": 9},
    )
    assert markdown_unit_test_type_quota_issues(prepared, _plan()) == []
    example = (
        "> [!QUESTION] **Q99｜错因辨析｜基础｜考点：展示示例**\n>\n> 演示题干。\n\n"
        "> [!ANSWER]\n>\n> 演示答案。\n"
    )
    markdown = markdown.replace("\n## 单元测试", "\n\n" + example + "\n## 单元测试", 1)
    quoted_code = "> ```markdown\n" + "\n".join("> " + line for line in example.splitlines()) + "\n> ```"
    markdown += "\n\n" + quoted_code
    markdown += "\n\n```markdown\n" + example + "```\n"
    assert markdown_unit_test_type_quota_issues(markdown, _plan()) == []


@pytest.mark.parametrize("enough", [True, False])
def test_final_gate_honors_minimum_type_quota_when_other_groups_are_untyped(enough):
    plan = [_plan()[0], {"target": "自选题型短测", "question_count": 5}]
    types = ["应用迁移"] * 5 + ["错因辨析"] * 4 if enough else DRIFTED_TYPES
    kwargs = {"title": TITLE, "chapter_end_practice_plan": plan,
              "quantity_constraints": {"chapter_end_question_count": 9}}
    if enough:
        prepared = publish._prepare_chapter_markdown(_chapter(types).markdown, **kwargs)
        assert prepared.count("｜应用迁移｜") == 5
    else:
        with pytest.raises(ChapterQuantityContractError, match="至少4题"):
            publish._prepare_chapter_markdown(_chapter(types).markdown, **kwargs)


@pytest.mark.anyio
@pytest.mark.parametrize("entrypoint", ["merge", "stage", "publish"])
async def test_each_publication_entrypoint_validates_task_type_plan_before_writes(monkeypatch, entrypoint):
    scope = build_course_storage_scope(user_id="user-quota-test", course_id="course_quotatest001")

    class NoWrites:
        async def write_text(self, *_args, **_kwargs):
            pytest.fail("A bad explicit type allocation reached a storage write")

    @contextmanager
    def read_session():
        yield object()

    monkeypatch.setattr(publish, "get_content_store", NoWrites)
    monkeypatch.setattr(publish, "managed_session", read_session)
    monkeypatch.setattr(publish.docgen_repo, "get_latest_version_no", lambda *_args: 0)
    metadata = dict(_task(), title=TITLE, markdown=_chapter(DRIFTED_TYPES).markdown)
    with pytest.raises(ChapterQuantityContractError, match="应用迁移"):
        if entrypoint == "merge":
            publish.build_merged_markdown([metadata])
        elif entrypoint == "stage":
            await publish.stage_knowledge_docs(
                course_id=scope.course_id, chapter_metadatas=[metadata], course_scope=scope,
            )
        else:
            publish.publish_staged_knowledge_docs(
                course_id=scope.course_id, build_group_id="group-quota-test", publish_token="quota-test",
                chapter_metadatas=[metadata], chapter_assignments=[], document_context={},
                cover_markdown=None, user_prompt="test", requested_at=datetime.now(timezone.utc), course_scope=scope,
            )


def test_task_type_plan_survives_source_metadata_to_real_publication_gate():
    chapter = EnhancedChapterDraft.model_validate(_chapter(DRIFTED_TYPES).model_dump())
    task = ChapterGenerationTask.model_validate(_task())
    metadata = _chapter_metadata(chapter, digest_mode="sprint", task=task)
    assert metadata["chapter_end_practice_plan"] == task.chapter_end_practice_plan
    with pytest.raises(ChapterQuantityContractError, match="应用迁移"):
        publish.build_merged_markdown([metadata])


def test_metadata_without_task_preserves_legacy_untyped_publication():
    chapter = EnhancedChapterDraft.model_validate(_chapter(DRIFTED_TYPES).model_dump())
    metadata = _chapter_metadata(chapter, digest_mode="sprint")
    prepared = publish.build_merged_markdown([metadata])
    assert prepared.count("｜应用迁移｜") == 3
    assert prepared.count("｜错因辨析｜") == 1
