"""DocGen LLM task scheduling contracts."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.shared.infra.execution import TracedExecutionContext
from app.workflows.digest.docgen.lib import (
    chapter_execution_brief,
    chapter_revision,
    chapter_review,
    intent,
    query_planning,
    static_html_figure,
    title_lock,
    writer,
)
from app.workflows.digest.docgen.lib.figure_spec import FigureSpec
from app.workflows.digest.docgen.lib.models import (
    ChapterDraft,
    ChapterExecutionBrief,
    ChapterGenerationTask,
    ChapterQualitySignals,
    DocGenIntentProfile,
    EnhancedChapterDraft,
    LockedChapterTitle,
)
from app.workflows.digest.docgen.lib.query_planning import ResearchSubQueryPlan
from app.workflows.digest.docgen.lib.writer import DocGenWriterRuntime


@pytest.mark.anyio
async def test_core_docgen_single_llm_calls_call_provider_directly(monkeypatch) -> None:
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


@pytest.mark.anyio
async def test_chapter_brief_passes_configured_overall_timeout(monkeypatch) -> None:
    captured_overall_timeout: float | None = None

    async def fake_completion(*args, **kwargs):
        nonlocal captured_overall_timeout
        captured_overall_timeout = float(kwargs["overall_timeout_s"])
        return ChapterExecutionBrief(
            chapter_index=1,
            teaching_outline=["先讲变量关系，再讲图像变化"],
            content_role_targets={"concept": ["函数图像"]},
            example_coverage_plan=[{"target": "函数图像", "purpose": "连接概念和题型"}],
            concept_targets=["函数图像"],
            retrieval_queries=["函数图像变化"],
        )

    monkeypatch.setattr(chapter_execution_brief, "_chapter_brief_timeout_seconds", lambda: 0.01)
    monkeypatch.setattr(chapter_execution_brief, "acompletion_with_fallback", fake_completion)

    result = await chapter_execution_brief.build_chapter_execution_brief(
        course_name="数学",
        digest_mode="systematic",
        chapter={"chapter_index": 1, "title": "函数基础"},
        locked_title="函数变化与图像",
        intent_core={"learning_goal_text": "掌握函数图像"},
        glossary_terms=[],
        claim_targets=[],
        confusion_targets=[],
    )

    assert result.retrieval_queries == ["函数图像变化"]
    assert captured_overall_timeout == 0.01


@pytest.mark.anyio
async def test_docgen_query_planning_calls_single_llm_directly(monkeypatch) -> None:
    async def fake_completion(*args, **kwargs):
        query_tool = kwargs.get("extra_metadata", {}).get("query_tool")
        if query_tool == "generate_sub_queries":
            return ResearchSubQueryPlan(queries=["函数图像 单调性", "函数图像 最值"])
        if query_tool == "generate_gap_queries":
            return ResearchSubQueryPlan(queries=["函数图像 易错点"])
        raise AssertionError(f"unexpected query tool: {query_tool}")

    monkeypatch.setattr(query_planning, "acompletion_with_fallback", fake_completion)

    sub_queries = await query_planning.generate_sub_queries("函数图像", max_queries=3)
    gap_queries = await query_planning.generate_gap_queries("已有：定义。", required_elements=["单调性"])

    assert sub_queries == ["函数图像 单调性", "函数图像 最值"]
    assert gap_queries == ["函数图像 易错点"]


@pytest.mark.anyio
async def test_docgen_writer_calls_single_completion_directly(monkeypatch) -> None:
    captured_completion_kwargs: dict[str, object] = {}

    async def fake_llm(*args, **kwargs):
        captured_completion_kwargs.update(kwargs)
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
            "execution_contract": {"min_word_count": 1, "target_word_count": 1200},
        },
        dense_context="local context",
        digest_mode="systematic",
    )

    assert "Function Graphs" in result.content
    assert captured_completion_kwargs["max_tokens"] <= 4080


def test_docgen_writer_caps_unreasonable_target_word_budget(monkeypatch) -> None:
    monkeypatch.setattr(writer, "WRITER_MAX_EFFECTIVE_TARGET_WORDS", 2400)

    contract = {"target_word_count": 100000}

    assert writer._writer_target_word_count(contract) == 2400
    assert writer._writer_max_tokens_for_contract(contract) <= 5600
    assert writer._writer_stream_char_limit(contract) <= 14000


@pytest.mark.anyio
async def test_docgen_writer_raises_when_primary_completion_fails(monkeypatch) -> None:
    async def failing_llm(*args, **kwargs):
        raise RuntimeError("primary concurrency exhausted")

    runtime = DocGenWriterRuntime(
        TracedExecutionContext(
            course_id="course_docgen0000",
            build_session_id="build-1",
            digest_mode="systematic",
            llm_caller=failing_llm,
        )
    )
    with pytest.raises(writer.DocGenWriterNoContentError, match="RuntimeError"):
        await runtime.execute(
            chapter_plan={
                "chapter_index": 1,
                "total_chapters": 1,
                "title": "Function Graphs",
                "objective": "Understand function graph basics.",
                "required_elements": ["function graph", "worked example"],
                "writing_instructions": "Compare graph shape with algebraic expression.",
                "execution_contract": {"min_word_count": 1},
            },
            dense_context="Function graphs connect input and output values.\nWorked examples should compare intervals.",
            digest_mode="systematic",
        )



@pytest.mark.anyio
async def test_docgen_writer_raises_when_completion_times_out(monkeypatch) -> None:
    async def slow_llm(*args, **kwargs):
        await asyncio.sleep(0.05)
        return "# Should not arrive\n\nThis completion is too slow."

    monkeypatch.setattr(writer, "WRITER_TASK_TIMEOUT_S", 0.01)

    runtime = DocGenWriterRuntime(
        TracedExecutionContext(
            course_id="course_docgen0000",
            build_session_id="build-1",
            digest_mode="systematic",
            llm_caller=slow_llm,
        )
    )
    with pytest.raises(writer.DocGenWriterNoContentError, match="TimeoutError"):
        await runtime.execute(
            chapter_plan={
                "chapter_index": 1,
                "total_chapters": 1,
                "title": "Function Graphs",
                "objective": "Understand function graph basics.",
                "required_elements": ["function graph"],
                "execution_contract": {"min_word_count": 1},
            },
            dense_context="Function graphs connect input and output values.",
            digest_mode="systematic",
        )

@pytest.mark.anyio
async def test_docgen_writer_stream_timeout_retries_with_primary_completion(monkeypatch) -> None:
    completion_calls: list[dict[str, object]] = []

    async def slow_stream(*args, **kwargs):
        await asyncio.sleep(0.05)
        yield "# Incomplete stream"

    async def fallback_llm(*args, **kwargs):
        completion_calls.append(dict(kwargs))
        return (
            "# Function Graphs\n\n"
            "## Function Graph Definition\n\n"
            "A function graph shows the relation between input and output.\n\n"
            "## Worked Example\n\n"
            "Use points to sketch the trend and compare intervals.\n\n"
            "## Common Mistakes\n\n"
            "Do not confuse intercepts with extrema.\n"
        )

    async def ignore_stream_update(_: str) -> None:
        return None

    monkeypatch.setattr(writer, "WRITER_TASK_TIMEOUT_S", 0.01)
    monkeypatch.setattr(writer, "acompletion_stream", slow_stream)
    monkeypatch.setattr(TracedExecutionContext, "resolve_llm_caller", lambda self: fallback_llm)

    runtime = DocGenWriterRuntime(
        TracedExecutionContext(
            course_id="course_docgen0000",
            build_session_id="build-1",
            digest_mode="systematic",
        )
    )
    result = await runtime.execute(
        chapter_plan={
            "chapter_index": 1,
            "total_chapters": 1,
            "title": "Function Graphs",
            "objective": "Understand function graph basics.",
            "required_elements": ["function graph", "worked example"],
            "execution_contract": {"min_word_count": 1, "target_word_count": 1200},
        },
        dense_context="Function graphs connect input and output values.",
        digest_mode="systematic",
        on_stream_update=ignore_stream_update,
    )

    assert "Function Graphs" in result.content
    assert result.metadata["fallback_used"] is True
    assert "TimeoutError" in str(result.metadata["writer_stream_failure_reason"])
    assert result.metadata["writer_fallback_model_slot"] == "primary"
    assert completion_calls[0]["model"] == "primary"
    fallback_metadata = completion_calls[0]["extra_metadata"]
    assert isinstance(fallback_metadata, dict)
    assert fallback_metadata["docgen_writer_stream_timed_out"] is True


@pytest.mark.anyio
async def test_chapter_rewrite_calls_single_llm_directly(monkeypatch) -> None:
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


@pytest.mark.anyio
async def test_chapter_review_does_not_schedule_a_second_llm_pass() -> None:
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
    assert report.review_mode == "rule_guardrail"
    assert report.llm_action_count == 0


@pytest.mark.anyio
async def test_static_html_figure_assets_batch_candidates_through_scheduler(monkeypatch) -> None:
    scheduler_calls: list[dict[str, object]] = []
    written_assets: dict[str, str] = {}
    completion_calls = {"count": 0}

    async def fake_run_llm_tasks(items, worker, *, max_concurrent=None, on_result=None):
        queued = list(items)
        scheduler_calls.append({"items": [item.title for item in queued], "max_concurrent": max_concurrent})
        results = []
        for index, item in enumerate(queued):
            result = await worker(item)
            if on_result is not None:
                await on_result(index, item, result)
            results.append(result)
        return results

    async def fake_completion(*args, **kwargs):
        completion_calls["count"] += 1
        if kwargs.get("response_model") is static_html_figure._StaticFigureSelection:
            return static_html_figure._StaticFigureSelection(
                selected=[
                    static_html_figure._StaticFigureSelectionItem(index=1, figure_goal="比较类型字节数"),
                    static_html_figure._StaticFigureSelectionItem(index=2, figure_goal="展示逻辑表达式树"),
                ]
            )
        if completion_calls["count"] == 2:
            return FigureSpec(
                type="problem_diagram",
                title="占位图示",
                elements=[
                    {"kind": "shape", "id": "shape-a", "label": "!a", "shape_type": "rectangle"},
                    {"kind": "shape", "id": "shape-b", "label": "!b", "shape_type": "rectangle"},
                    {"kind": "shape", "id": "shape-c", "label": "||", "shape_type": "rectangle"},
                    {"kind": "vector", "id": "edge-a-c", "label": "&&", "from_id": "shape-a", "to_id": "shape-c"},
                    {"kind": "vector", "id": "edge-b-c", "label": "!c", "from_id": "shape-b", "to_id": "shape-c"},
                ],
            )
        return FigureSpec(
            type="problem_diagram",
            title="占位图示",
            elements=[
                {"kind": "shape", "id": "shape-a", "label": "A", "shape_type": "rectangle", "x": 24, "y": 42, "rx": 8, "ry": 7},
                {"kind": "shape", "id": "shape-b", "label": "B", "shape_type": "rectangle", "x": 64, "y": 42, "rx": 8, "ry": 7},
                {"kind": "vector", "id": "edge-a-b", "label": "关系", "x": 34, "y": 42, "x2": 54, "y2": 42},
            ],
        )

    class FakeContentStore:
        async def write_text(self, key: str, text: str) -> None:
            written_assets[key] = text

    monkeypatch.setattr(static_html_figure, "run_llm_tasks", fake_run_llm_tasks)
    monkeypatch.setattr(static_html_figure, "acompletion_with_fallback", fake_completion)
    monkeypatch.setattr(static_html_figure, "get_content_store", lambda: FakeContentStore())
    monkeypatch.setattr(
        static_html_figure,
        "resolve_course_storage_scope",
        lambda course_id: SimpleNamespace(namespace=f"courses/{course_id}"),
    )
    monkeypatch.setattr(static_html_figure, "validate_single_file_html", lambda html: [])

    markdown = (
        "# C 语言基础\n\n"
        "## 基本数据类型\n\n"
        "C 语言中 char 占 1B，int 和 float 通常占 4B，double 占 8B，需要按字节数理解变量存储空间。"
        "教材会把这些类型放到一条字节尺度上比较：char 最小，int 与 float 常用于普通整数和小数，"
        "double 用更长的存储长度换取更高精度。理解这条尺度后，再看变量、数组和结构体占用内存时，"
        "就能把“类型名称”和“实际字节数”对应起来，而不是只背零散结论。\n\n"
        "## 逻辑运算符优先级\n\n"
        "表达式 !a && !b || !c 的求值顺序要按 !、&&、|| 的优先级形成表达式树，图示可展示执行顺序。"
        "先对 a、b、c 分别取反，再把左侧两个结果用 && 合并，最后把该结果与 !c 用 || 合并。"
        "如果 a=1、b=1、c=0，叶子节点会得到 0、0、1，内部节点再依次给出 && 的 0 和 || 的 1。"
        "这个过程适合画成树状图，因为学生能看到优先级不是从左到右机械扫描，而是由运算符层级决定。\n"
    )

    assets = await static_html_figure.generate_static_html_figure_assets(
        draft=ChapterDraft(chapter_index=1, title="C 语言基础", markdown=markdown),
        traced_context=TracedExecutionContext(
            course_id="course_docgen000000",
            build_session_id="build-1",
            digest_mode="systematic",
        ),
        digest_mode="systematic",
        markdown=markdown,
        max_assets=2,
    )

    assert scheduler_calls == [{"items": ["基本数据类型", "逻辑运算符优先级"], "max_concurrent": None}]
    assert len(assets) == 2
    assert len(written_assets) == 2
    assert {asset["anchor_heading"] for asset in assets} == {"基本数据类型", "逻辑运算符优先级"}
