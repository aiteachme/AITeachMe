"""Regression cases from the production short-course build trace."""

from __future__ import annotations

import pytest
from markdown_it import MarkdownIt

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.graph import route_after_step
from app.workflows.digest.docgen.lib import chapter_execution_brief, chapter_planning, quality, repair
from app.workflows.digest.docgen.lib.chapter_context import DocGenChapterContextRuntime
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    DocGenContext,
    DocGenIntentProfile,
    DocumentBackbone,
    LLMDocumentConsistencyReviewResult,
    LockedChapterTitle,
    ReviewAction,
    ReviewedChapterDraft,
)
from app.workflows.digest.docgen.lib.quantity_contracts import explicit_chapter_structure_issues
from app.workflows.digest.docgen.lib.unit_test_generation import generate_chapter_unit_test_markdown
from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestItem, ChapterUnitTestSet, append_unit_test_markdown, render_unit_test_markdown,
)
from app.workflows.digest.docgen.lib.writer import (
    DocGenWriterNoContentError,
    DocGenWriterRuntime,
    _explicit_writer_contract_issues,
)
from app.workflows.digest.docgen.nodes.generate_chapters import _chapter_plan_for_writer
from app.workflows.digest.docgen.nodes import assemble_chapter_tasks, merge_review
from app.workflows.digest.docgen.prompts.chapter_review import build_chapter_review_messages
from app.workflows.digest.docgen.prompts.document_review import build_document_review_messages
from app.workflows.digest.docgen.prompts.generation import build_docgen_writer_messages


TITLE = "Python列表索引与切片"


def _compile_brief(brief: ChapterExecutionBrief, *, build_constraints: dict | None = None) -> ChapterGenerationTask:
    return chapter_planning.assemble_chapter_generation_plan(
        docgen_context=DocGenContext(course_name=TITLE, digest_mode="sprint", build_constraints=build_constraints or {}),
        confirmed_chapters=[{"chapter_index": 1, "title": TITLE}],
        locked_titles=[LockedChapterTitle(chapter_index=1, confirmed_title=TITLE, enhanced_title=TITLE)],
        # A high default density must not inflate an explicit user quantity.
        intent_profile=DocGenIntentProfile(example_ratio=0.9, practice_ratio=0.9),
        file_summaries=[],
        task_seeds=[ChapterGenerationTaskSeed(
            chapter_index=1, confirmed_title=TITLE,
            required_elements=["正索引", "负索引", "取值", "越界", "切片", "起点", "终点"],
            retrieval_queries=[TITLE],
        )],
        chapter_execution_briefs=[brief],
    ).chapters[0]


@pytest.mark.anyio
async def test_no_retrieval_brief_preserves_user_contract_through_writer_and_quiz(monkeypatch) -> None:
    async def fake_brief(*_args, **kwargs):
        return kwargs["response_model"](
            teaching_outline=["索引取值", "基本切片"],
            writing_instructions=["仅2小节、2示例、2练习，1200–1600字，不联网。"],
            quantity_constraints={
                "body_section_count": 2, "worked_example_count": 2,
                "inline_practice_count": 0, "chapter_end_question_count": 2,
                "min_word_count": 1200, "max_word_count": 1600,
            },
            content_role_targets={"concept": ["列表索引", "列表切片"]},
            example_coverage_plan=[{"target": "索引取值"}, {"target": "切片边界"}],
            chapter_end_practice_plan=[{"target": "负索引", "question_count": 1}, {"target": "切片终点", "question_count": 1}],
            retrieval_queries=[],
        )

    monkeypatch.setattr(chapter_execution_brief, "acompletion_with_fallback", fake_brief)
    brief = await chapter_execution_brief.build_chapter_execution_brief(
        course_name=TITLE, digest_mode="sprint", chapter={"chapter_index": 1}, locked_title=TITLE,
        intent_core={}, glossary_terms=[], claim_targets=[], confusion_targets=[],
        user_prompt="只要2小节、2代码示例、2道练习，正文1200–1600字，不联网。",
    )
    assert brief.fallback_used is False
    task = _compile_brief(brief)
    # Exercise the persisted task round trip as well as plan compilation.
    task = ChapterGenerationTask.model_validate(task.model_dump(mode="json"))
    assert task.retrieval_queries == []
    assert task.teaching_outline == ["索引取值", "基本切片"]
    assert (task.min_word_count, task.target_word_count, task.max_word_count) == (1200, 1400, 1600)
    writer_plan = _chapter_plan_for_writer(task, total_chapters=1)
    contract = writer_plan["execution_contract"]
    assert contract["practice_quota"]["worked_examples"] == 2
    assert contract["practice_quota"]["practice_tasks"] == 0
    assert contract["practice_quota"]["chapter_end_min_tasks"] == 2
    assert contract["practice_quota"]["chapter_end_max_tasks"] == 2
    writer_prompt = build_docgen_writer_messages(
        title=TITLE, objective="", digest_mode="sprint", required_elements=task.required_elements,
        writing_instructions=writer_plan["writing_instructions"], source_count=0, dense_context="",
        execution_contract=contract,
    )[-1]["content"]
    assert "正文恰好 2 个二级小节" in writer_prompt
    assert "正文恰好 2 个例题/代码示例" in writer_prompt
    assert "不要用代码长度凑最低字数" in writer_prompt
    assert "训练型约" not in writer_prompt
    assert "短练习/自测/变式约 0 个" in writer_prompt
    quiz_prompts = []

    async def fake_quiz(messages, **_kwargs):
        quiz_prompts.append(messages[-1]["content"])
        return ChapterUnitTestSet(items=[
            ChapterUnitTestItem(
                type="填空题", target=f"列表索引{n}", stem=f"四个元素的列表下标 {n} 对应第几项？",
                answer=str(n + 1), basis=f"索引从零开始；所以是第{n + 1}项。",
            ) for n in range(2)
        ])

    markdown = await generate_chapter_unit_test_markdown(
        chapter_index=1, chapter_title=TITLE, digest_mode="sprint", required_elements=task.required_elements,
        chapter_end_practice_plan=contract["chapter_end_practice_plan"],
        body_markdown=f"# {TITLE}\n\n## 索引\n正文\n\n## 切片\n正文\n",
        min_items=contract["practice_quota"]["chapter_end_min_tasks"],
        max_items=contract["practice_quota"]["chapter_end_max_tasks"], llm_caller=fake_quiz,
    )
    assert len(quiz_prompts) == 2  # Independent answer review remains enabled.
    assert all("题量范围：2-2" in prompt and "切片终点" in prompt for prompt in quiz_prompts)
    assert markdown.count("> [!QUESTION]") == markdown.count("> [!ANSWER]") == 2
    review_prompt = build_document_review_messages(
        digest_mode="sprint", reviewed_chapters=[{"markdown": markdown}], rule_report={},
        chapter_tasks=[task.model_dump(mode="json")],
    )[-1]["content"]
    assert "'worked_example_count': 2" in review_prompt
    assert "'chapter_end_question_count': 2" in review_prompt
    chapter_review_prompt = build_chapter_review_messages(
        chapter_title=TITLE, digest_mode="sprint", chapter_task=task.model_dump(mode="json"),
        markdown=markdown, claim_ledger={}, claim_evidence_map={}, conflict_report={}, rule_review={},
    )[-1]["content"]
    assert "'inline_practice_count': 0" in chapter_review_prompt
    assert "'chapter_end_question_count': 2" in chapter_review_prompt
    assert "仅2小节、2示例、2练习，1200–1600字，不联网。" in chapter_review_prompt


def test_unspecified_quantities_keep_mode_defaults() -> None:
    task = _compile_brief(ChapterExecutionBrief(chapter_index=1))
    contract = _chapter_plan_for_writer(task, total_chapters=1)["execution_contract"]
    assert contract["quantity_constraints"] == {}
    assert contract["practice_quota"]["chapter_end_min_tasks"] == 3
    assert contract["practice_quota"]["chapter_end_max_tasks"] == 4
    assert contract["practice_quota"]["worked_examples"] >= 4


def test_explicit_question_count_above_default_keeps_entire_practice_plan() -> None:
    task = _compile_brief(ChapterExecutionBrief(
        quantity_constraints={"chapter_end_question_count": 6},
        chapter_end_practice_plan=[{"target": f"索引边界{i}"} for i in range(6)],
    ))
    assert len(task.chapter_end_practice_plan) == 6
    contract = _chapter_plan_for_writer(task, total_chapters=1)["execution_contract"]
    assert contract["practice_quota"]["chapter_end_min_tasks"] == 6
    assert contract["practice_quota"]["chapter_end_max_tasks"] == 6


def test_explicit_zero_examples_and_small_word_cap_override_density_and_budget() -> None:
    task = _compile_brief(ChapterExecutionBrief(quantity_constraints={
        "worked_example_count": 0, "max_word_count": 400,
    }))
    assert task.min_word_count <= task.target_word_count <= task.max_word_count == 400
    contract = _chapter_plan_for_writer(task, total_chapters=1)["execution_contract"]
    assert contract["practice_quota"]["worked_examples"] == 0
    prompt = build_docgen_writer_messages(
        title=TITLE, objective="", digest_mode="sprint", required_elements=[], writing_instructions="",
        source_count=0, dense_context="", execution_contract=contract,
    )[-1]["content"]
    assert "正文恰好 0 个例题/代码示例" in prompt
    assert "训练型约" not in prompt


def test_explicit_minimum_is_not_lowered_by_default_maximum() -> None:
    task = _compile_brief(
        ChapterExecutionBrief(quantity_constraints={"min_word_count": 4000}),
        build_constraints={"chapter_min_words": 480, "chapter_target_words": 600, "chapter_max_words": 720},
    )
    assert task.min_word_count == 4000
    assert task.target_word_count >= 4000
    assert task.max_word_count >= 4000


def test_impossible_document_budget_reports_conflict_instead_of_lowering_user_minimum() -> None:
    with pytest.raises(chapter_planning.ChapterWordBudgetError, match="超出整本 600 字预算"):
        _compile_brief(
            ChapterExecutionBrief(quantity_constraints={"min_word_count": 1200, "max_word_count": 1600}),
            build_constraints={"target_total_words": 600},
        )


@pytest.mark.anyio
async def test_task_assembly_stops_before_generation_for_impossible_word_budget() -> None:
    node = assemble_chapter_tasks.build_assemble_chapter_tasks_node(context=WorkflowContext(
        workflow_name="digest.docgen", course_id="course_word_conflict",
    ))
    result = await node({
        "docgen_context": {"course_name": TITLE, "build_constraints": {"target_total_words": 600}},
        "chapter_assignments": [{"chapter_index": 1, "title": TITLE}],
        "locked_titles": [LockedChapterTitle(chapter_index=1, confirmed_title=TITLE, enhanced_title=TITLE).model_dump()],
        "chapter_task_seeds": [ChapterGenerationTaskSeed(chapter_index=1, confirmed_title=TITLE).model_dump()],
        "chapter_execution_brief_items": [ChapterExecutionBrief(
            quantity_constraints={"min_word_count": 1200, "max_word_count": 1600},
        ).model_dump()],
    })
    assert "超出整本 600 字预算" in result["error"]
    assert "chapter_tasks" not in result
    assert route_after_step(result) == "fail"


@pytest.mark.parametrize("chapter_ranges", [
    [{"min_word_count": 800, "max_word_count": 800}, {"min_word_count": 1200, "max_word_count": 1200}],
    [{"min_word_count": 1500, "max_word_count": 1800}, {}],
    [{"max_word_count": 400}, {"min_word_count": 1400}],
    [{"min_word_count": 400, "max_word_count": 400}, {"min_word_count": 400, "max_word_count": 400}],
])
def test_document_budget_supports_different_explicit_chapter_lengths(chapter_ranges) -> None:
    plan = chapter_planning.assemble_chapter_generation_plan(
        docgen_context=DocGenContext(course_name=TITLE, digest_mode="sprint", build_constraints={"target_total_words": 2000}),
        confirmed_chapters=[{"chapter_index": n, "title": f"列表索引{n}"} for n in (1, 2)],
        locked_titles=[LockedChapterTitle(chapter_index=n, confirmed_title=f"列表索引{n}", enhanced_title=f"列表索引{n}") for n in (1, 2)],
        intent_profile=DocGenIntentProfile(), file_summaries=[],
        task_seeds=[ChapterGenerationTaskSeed(chapter_index=n, confirmed_title=f"列表索引{n}") for n in (1, 2)],
        chapter_execution_briefs=[ChapterExecutionBrief(chapter_index=n, quantity_constraints=quantities)
                                  for n, quantities in enumerate(chapter_ranges, start=1)],
    )
    assert sum(task.max_word_count for task in plan.chapters) <= 2000
    for task, requested in zip(plan.chapters, chapter_ranges, strict=True):
        assert task.min_word_count <= task.target_word_count <= task.max_word_count
        if requested.get("min_word_count") is not None:
            assert task.min_word_count == requested["min_word_count"]
        if requested.get("max_word_count") is not None:
            assert task.max_word_count <= requested["max_word_count"]


def test_separate_inline_and_chapter_end_practice_quotas_remain_separate() -> None:
    task = _compile_brief(ChapterExecutionBrief(quantity_constraints={
        "inline_practice_count": 3, "chapter_end_question_count": 2,
    }))
    contract = _chapter_plan_for_writer(task, total_chapters=1)["execution_contract"]
    assert contract["practice_quota"]["practice_tasks"] == 3
    assert contract["practice_quota"]["chapter_end_min_tasks"] == 2
    assert contract["practice_quota"]["chapter_end_max_tasks"] == 2
    prompt = build_docgen_writer_messages(
        title=TITLE, objective="", digest_mode="sprint", required_elements=[], writing_instructions="",
        source_count=0, dense_context="", execution_contract=contract,
    )[-1]["content"]
    assert "正文练习、自测或变式题合计恰好 3 道" in prompt
    assert "章末测试恰好 2 道题" in prompt


def test_only_chapter_end_count_does_not_disable_unspecified_inline_practice() -> None:
    task = _compile_brief(ChapterExecutionBrief(quantity_constraints={"chapter_end_question_count": 2}))
    contract = _chapter_plan_for_writer(task, total_chapters=1)["execution_contract"]
    assert contract["practice_quota"]["chapter_end_min_tasks"] == 2
    assert contract["practice_quota"]["practice_tasks"] > 0
    prompt = build_docgen_writer_messages(
        title=TITLE, objective="", digest_mode="sprint", required_elements=[], writing_instructions="",
        source_count=0, dense_context="", execution_contract=contract,
    )[-1]["content"]
    assert "正文练习、自测或变式题合计恰好" not in prompt
    assert "章末测试恰好 2 道题" in prompt


@pytest.mark.anyio
async def test_explicit_empty_retrieval_queries_do_not_trigger_title_search() -> None:
    runtime = DocGenChapterContextRuntime(TracedExecutionContext(course_id="course_no_retrieval"))
    result = await runtime.execute(queries=[], chapter_title=TITLE, objective="讲清切片")
    assert result.content == ""
    assert result.metadata["query_count"] == 0


@pytest.mark.anyio
async def test_writer_preserves_repeated_code_and_output_lines() -> None:
    async def fake_llm(*_args, **_kwargs):
        return (
            f"# {TITLE}\n\n## 取值\n\n"
            '```python\ncolors = ["红", "黄", "蓝", "绿"]\n'
            "print(colors[-1])\nprint(colors[-1])\nprint(colors[-2])\n```\n\n"
            "输出：\n\n```text\n绿\n绿\n蓝\n```\n"
        )

    runtime = DocGenWriterRuntime(TracedExecutionContext(course_id="course_repeated_output", llm_caller=fake_llm))
    result = await runtime.execute(chapter_plan={"title": TITLE}, dense_context="", digest_mode="sprint")
    assert "print(colors[-1])\nprint(colors[-1])" in result.content
    assert "绿\n绿\n蓝" in result.content


@pytest.mark.anyio
@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_writer_retries_section_contract_once_and_rejects_remaining_violation(repair_succeeds) -> None:
    calls = []

    async def fake_llm(messages, **_kwargs):
        calls.append(messages)
        body = f"# {TITLE}\n\n## 索引\n正文\n\n## 切片\n正文\n"
        if len(calls) == 1 or not repair_succeeds:
            body += "\n## 额外总结\n重复正文\n"
        return body

    runtime = DocGenWriterRuntime(TracedExecutionContext(course_id="course_explicit_sections", llm_caller=fake_llm))
    kwargs = dict(
        chapter_plan={"title": TITLE, "execution_contract": {"quantity_constraints": {"body_section_count": 2}}},
        dense_context="", digest_mode="sprint",
    )
    if repair_succeeds:
        result = await runtime.execute(**kwargs)
        headings = [t for t in MarkdownIt().parse(result.content) if t.type == "heading_open" and t.tag == "h2"]
        assert len(headings) == 2
        assert result.metadata["writer_contract_repair_attempted"] is True
    else:
        with pytest.raises(DocGenWriterNoContentError, match="still violates explicit contract"):
            await runtime.execute(**kwargs)
    assert len(calls) == 2
    assert "当前为 3 个" in calls[-1][-1]["content"]


def test_section_count_ignores_headings_inside_code_fences() -> None:
    body = "# Python\n\n## 索引\n正文\n\n## 切片\n正文\n\n```text\n## literal heading\n```\n"
    assert _explicit_writer_contract_issues(body, {"quantity_constraints": {"body_section_count": 2}}) == []


def test_word_budget_does_not_mistake_code_and_markup_for_prose_length() -> None:
    body = "# Python\n\n## 索引\n" + "讲解" * 30 + "\n\n```python\n" + "print(1)\n" * 20 + "```\n"
    assert _explicit_writer_contract_issues(body, {
        "quantity_constraints": {"body_section_count": 1, "min_word_count": 40, "max_word_count": 90},
    }) == []


def _published_chapter(*, extra_section: bool = False, question_count: int = 2) -> ReviewedChapterDraft:
    body = f"# {TITLE}\n\n## 索引\n索引从零开始。\n\n## 切片\n切片不包括终点。\n"
    if extra_section:
        body += "\n## 额外说明\n额外内容。\n"
    test = render_unit_test_markdown(
        ChapterUnitTestSet(items=[ChapterUnitTestItem(
            type="填空题", target=f"列表取值{n}", stem=f"列表下标 {n} 对应第几项？",
            answer=str(n + 1), basis=f"下标加一，是第 {n + 1} 项。",
        ) for n in range(question_count)]),
        title=TITLE, min_items=question_count, max_items=question_count, fallback_targets=["列表取值"],
    )
    return ReviewedChapterDraft(chapter_index=1, title=TITLE, markdown=append_unit_test_markdown(body, test))


@pytest.mark.parametrize(("extra_section", "question_count", "late_heading", "expected"), [
    (False, 2, False, True), (True, 2, False, False), (False, 4, False, False), (False, 2, True, False),
])
@pytest.mark.anyio
async def test_merge_gate_checks_final_draft_after_enhancement_and_repairs(
    monkeypatch, extra_section, question_count, late_heading, expected,
) -> None:
    task = _compile_brief(ChapterExecutionBrief(quantity_constraints={
        "body_section_count": 2, "chapter_end_question_count": 2,
    }))
    chapter = _published_chapter(extra_section=extra_section, question_count=question_count)
    if late_heading:
        # Publication demotes extra H1 headings to H2; check the formatted result too.
        chapter.markdown = chapter.markdown.replace("## 切片", "# 额外一级标题\n额外内容。\n\n## 切片")
    for name in (
        "update_knowledge_build_status", "update_knowledge_build_merge_preview", "append_knowledge_build_recent_event",
    ):
        monkeypatch.setattr(merge_review, name, lambda *args, **kwargs: None)

    async def fake_publish(*args, **kwargs):
        pass

    monkeypatch.setattr(merge_review, "publish_docgen_progress", fake_publish)
    node = merge_review.build_merge_review_node(context=WorkflowContext(
        workflow_name="digest.docgen", course_id="course_final_quantities",
    ))
    result = await node({
        "course_id": "course_final_quantities", "requested_at": "2026-10-11T00:00:00Z", "digest_mode": "sprint",
        "reviewed_chapter_drafts": [chapter.model_dump(mode="json")],
        "chapter_tasks": [task.model_dump(mode="json")],
        # Even a repair marked as applied must not bypass the final structural gate.
        "review_actions": [ReviewAction(action_type="section_patch", severity="error", status="applied").model_dump()],
    })
    assert result["merge_review_report"]["passed"] is expected
    assert route_after_step(result) == ("continue" if expected else "fail")
    if not expected:
        assert "chapter_metadatas" not in result
        assert "merged_markdown" not in result
        assert "发布前检查未通过" in result["error"]
    else:
        assert result["chapter_metadatas"][0]["quantity_constraints"]["body_section_count"] == 2


@pytest.mark.anyio
@pytest.mark.parametrize("llm_fails", [False, True])
async def test_quantity_rule_errors_survive_semantic_reviewer_success_or_failure(monkeypatch, llm_fails) -> None:
    async def fake_review(*args, **kwargs):
        if llm_fails:
            raise RuntimeError("reviewer unavailable")
        return LLMDocumentConsistencyReviewResult(passed=True, issues=[], actions=[])

    monkeypatch.setattr(quality, "acompletion_with_fallback", fake_review)
    task = _compile_brief(ChapterExecutionBrief(quantity_constraints={"chapter_end_question_count": 2}))
    report, _, calls = await quality.review_document_consistency_with_llm(
        reviewed_chapters=[_published_chapter(question_count=4)],
        document_backbone=DocumentBackbone(), expected_chapter_count=1,
        chapter_tasks=[task.model_dump(mode="json")],
    )
    assert calls == (2 if llm_fails else 1)
    assert report.passed is False
    assert any(item["severity"] == "error" and "当前为 4 道" in item["detail"] for item in report.issues)


@pytest.mark.anyio
@pytest.mark.parametrize("has_semantic_quantity", [True, False])
async def test_semantic_quantity_contract_requires_successful_semantic_review(monkeypatch, has_semantic_quantity) -> None:
    async def failed_review(*args, **kwargs):
        raise RuntimeError("reviewer unavailable")

    monkeypatch.setattr(quality, "acompletion_with_fallback", failed_review)
    task = _compile_brief(ChapterExecutionBrief(
        quantity_constraints={"worked_example_count": 2} if has_semantic_quantity else {},
    ))
    report, actions, _ = await quality.review_document_consistency_with_llm(
        reviewed_chapters=[_published_chapter()], document_backbone=DocumentBackbone(), expected_chapter_count=1,
        chapter_tasks=[task.model_dump(mode="json")],
    )
    assert report.fallback_used is True
    assert report.passed is (not has_semantic_quantity)
    if has_semantic_quantity:
        assert report.issues[0]["issue_type"] == "quantity_review_unavailable"
        assert actions[0].severity == "error"
        merged = quality.build_merge_review_report(
            enhanced_chapters=[_published_chapter()], expected_chapter_count=1, plan="", review_actions=actions,
        )
        assert merged.decision == "fail"
    else:
        assert actions == []


@pytest.mark.anyio
async def test_quantity_review_recovers_with_primary_after_reason_timeout(monkeypatch) -> None:
    calls = []

    async def review(messages, **kwargs):
        calls.append((messages, kwargs))
        if len(calls) == 1:
            raise TimeoutError("reason model timed out")
        return LLMDocumentConsistencyReviewResult(passed=True, issues=[], actions=[])

    monkeypatch.setattr(quality, "acompletion_with_fallback", review)
    task = _compile_brief(ChapterExecutionBrief(quantity_constraints={"worked_example_count": 2}))
    report, actions, count = await quality.review_document_consistency_with_llm(
        reviewed_chapters=[_published_chapter()], document_backbone=DocumentBackbone(), expected_chapter_count=1,
        chapter_tasks=[task.model_dump(mode="json")],
        user_prompt="逐题答案折叠，不要新增集中答案的约束。",
        plan="两小节、两例题，保留题答配对。",
    )

    assert report.passed is True
    assert report.fallback_used is False
    assert actions == []
    assert count == 2
    assert [kwargs["model"] for _, kwargs in calls] == ["reason", "primary"]
    assert calls[0][0] == calls[1][0]
    assert "逐题答案折叠，不要新增集中答案的约束。" in calls[0][0][-1]["content"]
    assert "两小节、两例题，保留题答配对。" in calls[0][0][-1]["content"]
    assert sum(float(kwargs["overall_timeout_s"]) for _, kwargs in calls) <= 180


@pytest.mark.parametrize("status", ["recorded", "skipped", "downgraded", "applied"])
def test_unresolved_review_errors_cannot_be_downgraded_to_publish_warnings(status) -> None:
    report = quality.build_merge_review_report(
        enhanced_chapters=[_published_chapter()], expected_chapter_count=1, plan="",
        review_actions=[ReviewAction(
            action_type="section_patch", severity="error", status=status, reason="例题数量不符合用户合同。",
        )],
    )
    assert report.passed is (status == "applied")
    if status != "applied":
        assert report.decision == "fail"


def test_final_structure_count_ignores_literal_markers_and_nested_headings() -> None:
    chapter = _published_chapter()
    body = chapter.markdown.replace("## 切片", (
        "```text\n## 额外小节\n> [!QUESTION] literal marker\n```\n\n"
        "> ## 引用中的标题\n\n## 切片"
    ))
    task = _compile_brief(ChapterExecutionBrief(quantity_constraints={
        "body_section_count": 2, "chapter_end_question_count": 2,
    }))
    assert explicit_chapter_structure_issues(body, task.quantity_constraints, include_unit_test=True) == []


@pytest.mark.anyio
async def test_semantic_repair_receives_user_quantity_and_writing_boundaries(monkeypatch) -> None:
    prompts = []
    verification_prompts = []

    async def fake_patch(messages, **kwargs):
        if kwargs["response_model"] is repair._LocalPatchVerification:
            verification_prompts.append(messages[-1]["content"])
            return repair._LocalPatchVerification(
                passed=True, verified_action_ids=["repair_action_001"],
                verification_notes=["负索引从末尾定位，未增加例题或扩大主题。"],
            )
        prompts.append(messages[-1]["content"])
        return kwargs["response_model"](
            status="patch", operation="replace_section", target_anchor="## 索引",
            patch_markdown="## 索引\n\n索引从零开始，负索引从列表末尾向前定位。",
        )

    monkeypatch.setattr(repair, "acompletion_with_fallback", fake_patch)
    task = _compile_brief(ChapterExecutionBrief(
        quantity_constraints={"body_section_count": 2, "worked_example_count": 2, "chapter_end_question_count": 2},
        writing_instructions=["不要扩展到列表排序。"],
    ))
    repaired, actions, unresolved, _ = await repair.repair_or_route_review_actions(
        reviewed_chapters=[_published_chapter()], chapter_tasks=[task.model_dump(mode="json")],
        review_actions=[ReviewAction(
            action_type="section_patch", chapter_index=1, severity="error", target_anchor="## 索引",
            reason="未解释负索引。", instruction="在已有索引小节解释负索引，保持小节边界。",
        )],
    )
    assert len(prompts) == 1
    assert "'worked_example_count': 2" in prompts[0]
    assert "不要扩展到列表排序" in prompts[0]
    assert len(verification_prompts) == 1
    assert "'worked_example_count': 2" in verification_prompts[0]
    assert "不要扩展到列表排序" in verification_prompts[0]
    assert actions[0].status == "applied"
    assert unresolved == []
    assert "负索引从列表末尾向前定位" in repaired[0].markdown
    assert explicit_chapter_structure_issues(repaired[0].markdown, task.quantity_constraints, include_unit_test=True) == []
