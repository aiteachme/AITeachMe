"""DocGen LLM task scheduling contracts."""

from __future__ import annotations

import pytest

from app.shared.infra.execution import TracedExecutionContext
from app.workflows.digest.docgen.lib import (
    chapter_execution_brief,
    chapter_revision,
    chapter_review,
    intent,
    query_planning,
    title_lock,
    writer,
)
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterGenerationTask,
    ChapterQualitySignals,
    DocGenIntentProfile,
    EnhancedChapterDraft,
    LLMChapterReviewResult,
    LockedChapterTitle,
)
from app.workflows.digest.docgen.lib.query_planning import ResearchSubQueryPlan
from app.workflows.digest.docgen.lib.writer import DocGenWriterRuntime


@pytest.mark.anyio
async def test_core_docgen_single_llm_calls_use_run_llm_tasks(monkeypatch) -> None:
    scheduler_calls: list[dict[str, object]] = []

    async def fake_run_llm_tasks(items, worker, *, max_concurrent=None, on_result=None):
        queued = list(items)
        scheduler_calls.append({"items": queued, "max_concurrent": max_concurrent})
        results = []
        for index, item in enumerate(queued):
            result = await worker(item)
            if on_result is not None:
                await on_result(index, item, result)
            results.append(result)
        return results

    async def fake_completion(*args, **kwargs):
        response_model = kwargs.get("response_model")
        if response_model is DocGenIntentProfile:
            return DocGenIntentProfile(learning_goal_text="掌握函数图像")
        if response_model is LockedChapterTitle:
            return LockedChapterTitle(chapter_index=1, enhanced_title="函数变化与图像")
        if response_model is ChapterExecutionBrief:
            return ChapterExecutionBrief(
                chapter_index=1,
                teaching_outline=["先讲变量关系，再讲图像变化"],
                content_role_targets={"concept": ["函数图像"]},
                example_coverage_plan=[{"target": "函数图像", "purpose": "连接概念和题型"}],
                concept_targets=["函数图像"],
                retrieval_queries=["函数图像变化"],
            )
        raise AssertionError(f"unexpected response model: {response_model}")

    for module in (intent, title_lock, chapter_execution_brief):
        monkeypatch.setattr(module, "run_llm_tasks", fake_run_llm_tasks)
        monkeypatch.setattr(module, "acompletion_with_fallback", fake_completion)

    intent_result = await intent.infer_intent_core(
        course_name="数学",
        digest_mode="systematic",
        user_prompt="复习函数",
        plan="按函数图像复习",
        material_profile={},
        chapters=[{"chapter_index": 1, "title": "函数基础"}],
    )
    title_result = await title_lock.lock_title_for_chapter(
        course_name="数学",
        digest_mode="systematic",
        user_prompt="复习函数",
        plan="按函数图像复习",
        chapter={"chapter_index": 1, "title": "函数基础"},
    )
    brief_result = await chapter_execution_brief.build_chapter_execution_brief(
        course_name="数学",
        digest_mode="systematic",
        chapter={"chapter_index": 1, "title": "函数基础"},
        locked_title="函数变化与图像",
        intent_core={"learning_goal_text": "掌握函数图像"},
        glossary_terms=[],
        claim_targets=[],
        confusion_targets=[],
    )

    assert intent_result.learning_goal_text == "掌握函数图像"
    assert title_result.enhanced_title == "函数变化与图像"
    assert brief_result.retrieval_queries == ["函数图像变化"]
    assert scheduler_calls == [
        {"items": [None], "max_concurrent": 1},
        {"items": [None], "max_concurrent": 1},
        {"items": [None], "max_concurrent": 1},
    ]


@pytest.mark.anyio
async def test_docgen_query_planning_uses_run_llm_tasks(monkeypatch) -> None:
    scheduler_calls: list[dict[str, object]] = []

    async def fake_run_llm_tasks(items, worker, *, max_concurrent=None, on_result=None):
        queued = list(items)
        scheduler_calls.append({"items": queued, "max_concurrent": max_concurrent})
        results = []
        for index, item in enumerate(queued):
            result = await worker(item)
            if on_result is not None:
                await on_result(index, item, result)
            results.append(result)
        return results

    async def fake_completion(*args, **kwargs):
        query_tool = kwargs.get("extra_metadata", {}).get("query_tool")
        if query_tool == "generate_sub_queries":
            return ResearchSubQueryPlan(queries=["函数图像 单调性", "函数图像 最值"])
        if query_tool == "generate_gap_queries":
            return ResearchSubQueryPlan(queries=["函数图像 易错点"])
        raise AssertionError(f"unexpected query tool: {query_tool}")

    monkeypatch.setattr(query_planning, "run_llm_tasks", fake_run_llm_tasks)
    monkeypatch.setattr(query_planning, "acompletion_with_fallback", fake_completion)

    sub_queries = await query_planning.generate_sub_queries("函数图像", max_queries=3)
    gap_queries = await query_planning.generate_gap_queries("已有：定义。", required_elements=["单调性"])

    assert sub_queries == ["函数图像 单调性", "函数图像 最值"]
    assert gap_queries == ["函数图像 易错点"]
    assert scheduler_calls == [
        {"items": [None], "max_concurrent": 1},
        {"items": [None], "max_concurrent": 1},
    ]


@pytest.mark.anyio
async def test_docgen_writer_completion_uses_run_llm_tasks(monkeypatch) -> None:
    scheduler_calls: list[dict[str, object]] = []

    async def fake_run_llm_tasks(items, worker, *, max_concurrent=None, on_result=None):
        queued = list(items)
        scheduler_calls.append({"items": queued, "max_concurrent": max_concurrent})
        results = []
        for index, item in enumerate(queued):
            result = await worker(item)
            if on_result is not None:
                await on_result(index, item, result)
            results.append(result)
        return results

    async def fake_llm(*args, **kwargs):
        return (
            "# Function Graphs\n\n"
            "## Function Graph Definition\n\n"
            "A function graph shows the relation between input and output.\n\n"
            "## Worked Example\n\n"
            "Use points to sketch the trend and compare intervals.\n\n"
            "## Common Mistakes\n\n"
            "Do not confuse intercepts with extrema.\n\n"
            "## 单元测试\n\n"
            "1. State one feature of a linear graph.\n"
        )

    monkeypatch.setattr(writer, "run_llm_tasks", fake_run_llm_tasks)

    runtime = DocGenWriterRuntime(
        TracedExecutionContext(
            course_id="course_docgen0000",
            build_session_id="build-1",
            digest_mode="systematic",
            llm_caller=fake_llm,
        )
    )
    result = await runtime.execute(
        chapter_plan={
            "chapter_index": 1,
            "total_chapters": 1,
            "title": "Function Graphs",
            "objective": "Understand function graph basics.",
            "required_elements": ["function graph"],
            "execution_contract": {"min_word_count": 1},
        },
        dense_context="local context",
        digest_mode="systematic",
    )

    assert "Function Graphs" in result.content
    assert scheduler_calls
    assert all(call == {"items": [None], "max_concurrent": 1} for call in scheduler_calls)


@pytest.mark.anyio
async def test_chapter_rewrite_uses_run_llm_tasks(monkeypatch) -> None:
    scheduler_calls: list[dict[str, object]] = []

    async def fake_run_llm_tasks(items, worker, *, max_concurrent=None, on_result=None):
        queued = list(items)
        scheduler_calls.append({"items": queued, "max_concurrent": max_concurrent})
        return [await worker(item) for item in queued]

    async def fake_llm(*args, **kwargs):
        return (
            "# Function Graphs\n\n"
            "## Function Graph Definition\n\n"
            "A function graph connects inputs and outputs.\n\n"
            "## Worked Example\n\n"
            "Plot points and identify the trend.\n\n"
            "## Common Mistakes\n\n"
            "Do not confuse slope and intercept.\n\n"
            "## 单元测试\n\n"
            "1. Explain the graph trend.\n"
        )

    monkeypatch.setattr(chapter_revision, "run_llm_tasks", fake_run_llm_tasks)

    rewritten, quality = await chapter_revision.maybe_rewrite_chapter(
        llm=fake_llm,
        markdown="# Function Graphs\n\nToo short.",
        title="Function Graphs",
        digest_mode="systematic",
        required_points=["function graph"],
        dense_context="local context",
        quality=ChapterQualitySignals(
            coverage_score=0.0,
            quality_score=0.1,
            warnings=["missing required point"],
            critic_summary="missing required point",
        ),
        min_word_count=1,
        max_retries=1,
        extra_metadata={"course_id": "course_docgen0000"},
    )

    assert "Function Graphs" in rewritten
    assert quality.rewrite_used is True
    assert scheduler_calls == [{"items": [None], "max_concurrent": 1}]


@pytest.mark.anyio
async def test_chapter_review_uses_run_llm_tasks(monkeypatch) -> None:
    scheduler_calls: list[dict[str, object]] = []

    async def fake_run_llm_tasks(items, worker, *, max_concurrent=None, on_result=None):
        queued = list(items)
        scheduler_calls.append({"items": queued, "max_concurrent": max_concurrent})
        return [await worker(item) for item in queued]

    async def fake_completion(*args, **kwargs):
        return LLMChapterReviewResult(
            passed=True,
            coverage_score=1.0,
            evidence_support_score=1.0,
            quality_score=1.0,
        )

    monkeypatch.setattr(chapter_review, "run_llm_tasks", fake_run_llm_tasks)
    monkeypatch.setattr(chapter_review, "acompletion_with_fallback", fake_completion)

    reviewed, report, _actions = await chapter_review.review_chapter(
        draft=EnhancedChapterDraft(
            chapter_index=1,
            title="Function Graphs",
            markdown=(
                "# Function Graphs\n\n"
                "## Function Graph Definition\n\n"
                "A function graph connects inputs and outputs.\n\n"
                "## Worked Example\n\n"
                "Plot points and read the trend.\n\n"
                "## Common Mistakes\n\n"
                "Do not confuse slope and intercept.\n\n"
                "## 单元测试\n\n"
                "1. Explain the graph trend.\n"
            ),
            source_details=[{"title": "local source"}],
        ),
        task=ChapterGenerationTask(
            chapter_index=1,
            confirmed_title="Function Graphs",
            required_elements=["function graph"],
        ),
        claim_ledger=None,
        claim_evidence_map=None,
        conflict_report=None,
        digest_mode="systematic",
    )

    assert reviewed.chapter_index == 1
    assert report.quality_score >= 1.0
    assert scheduler_calls == [{"items": [None], "max_concurrent": 1}]
