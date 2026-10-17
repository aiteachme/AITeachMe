"""Reject contradictory chapter-end allocations before generating course bodies."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langgraph.graph import END, StateGraph
from langgraph.types import Send
from pydantic import ValidationError

from app.shared.infra.exceptions import LLMCallError
from app.shared.infra.llm_support import structured_calls
from app.shared.infra.settings import set_system_settings_override
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.graph import build_generation_sends
from app.workflows.digest.docgen.lib import chapter_execution_brief, chapter_planning
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterExecutionBriefForGeneration,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    DocGenContext,
    DocGenIntentProfile,
    LockedChapterTitle,
)
from app.workflows.digest.docgen.nodes import assemble_chapter_tasks, build_chapter_execution_briefs
from app.workflows.digest.docgen.state import DocGenState


def _brief_payload(*, total: int | None = 9, counts: tuple[int, ...] = (4, 5)) -> dict:
    return {
        "chapter_index": 1,
        "teaching_outline": ["讲解整数加法并检查应用"],
        "content_role_targets": {"concept": ["整数加法"]},
        "example_coverage_plan": [{"target": "整数加法", "question_count": 3}],
        "quantity_constraints": {"chapter_end_question_count": total},
        "chapter_end_practice_plan": [
            {"target": f"题组{i}", "question_count": count, "min_examples": count}
            for i, count in enumerate(counts, start=1)
        ],
    }


@pytest.mark.parametrize("model", [ChapterExecutionBrief, ChapterGenerationTask])
def test_persisted_group_count_contradictions_are_rejected(model) -> None:
    with pytest.raises(ValidationError, match="question group total 9 must equal chapter_end_question_count 5"):
        model.model_validate(_brief_payload(total=5))


@pytest.mark.parametrize("model", [ChapterExecutionBrief, ChapterGenerationTask])
@pytest.mark.parametrize("invalid_count", [0, 13, None, True, 1.5, "2"])
def test_invalid_group_counts_cannot_be_clamped_into_a_valid_contract(model, invalid_count) -> None:
    payload = _brief_payload(total=4, counts=(4,))
    payload["chapter_end_practice_plan"][0]["question_count"] = invalid_count
    with pytest.raises(ValidationError, match="integer from 1 to 12"):
        model.model_validate(payload)


@pytest.mark.parametrize("model", [ChapterExecutionBrief, ChapterGenerationTask])
def test_counted_plan_cannot_hide_groups_through_partial_or_empty_entries(model) -> None:
    payload = _brief_payload()
    del payload["chapter_end_practice_plan"][1]["question_count"]
    with pytest.raises(ValidationError, match="every chapter-end question group"):
        model.model_validate(payload)
    payload = _brief_payload()
    payload["chapter_end_practice_plan"][1]["target"] = ""
    with pytest.raises(ValidationError, match="must have a target"):
        model.model_validate(payload)


def test_counted_groups_cannot_be_silently_truncated_to_match_a_smaller_total() -> None:
    with pytest.raises(ValidationError, match="exceed the supported plan size"):
        ChapterExecutionBrief.model_validate(_brief_payload(total=12, counts=(1,) * 13))


def test_legacy_plans_remain_readable_but_new_explicit_plans_require_counts() -> None:
    payload = _brief_payload(total=5, counts=(4,))
    del payload["chapter_end_practice_plan"][0]["question_count"]
    assert ChapterExecutionBrief.model_validate(payload).quantity_constraints.chapter_end_question_count == 5
    assert ChapterGenerationTask.model_validate(payload).quantity_constraints.chapter_end_question_count == 5
    with pytest.raises(ValidationError, match="declare its exact question_count"):
        ChapterExecutionBriefForGeneration.model_validate(payload)
    payload["quantity_constraints"]["chapter_end_question_count"] = None
    assert ChapterExecutionBriefForGeneration.model_validate(payload).quantity_constraints.chapter_end_question_count is None
    with pytest.raises(ValidationError, match="require an explicit"):
        ChapterExecutionBrief.model_validate(_brief_payload(total=None))


@pytest.mark.parametrize(("total", "counts"), [(9, (4, 5)), (5, (2, 3)), (5, (5,))])
def test_exact_group_counts_survive_compilation_and_json_restore(total, counts) -> None:
    brief = ChapterExecutionBriefForGeneration.model_validate(_brief_payload(total=total, counts=counts))
    assert "question_count" not in brief.example_coverage_plan[0]
    if 5 in counts:
        item = brief.chapter_end_practice_plan[counts.index(5)]
        assert item["question_count"] == 5 and item["min_examples"] == 4
    task = chapter_planning.assemble_chapter_generation_plan(
        docgen_context=DocGenContext(course_name="整数加法", digest_mode="sprint"),
        confirmed_chapters=[{"chapter_index": 1, "title": "整数加法"}],
        locked_titles=[LockedChapterTitle(chapter_index=1, confirmed_title="整数加法", enhanced_title="整数加法")],
        intent_profile=DocGenIntentProfile(), file_summaries=[],
        task_seeds=[ChapterGenerationTaskSeed(chapter_index=1, confirmed_title="整数加法")],
        chapter_execution_briefs=[brief],
    ).chapters[0]
    restored = ChapterGenerationTask.model_validate_json(task.model_dump_json())
    assert [item["question_count"] for item in restored.chapter_end_practice_plan] == list(counts)
    assert restored.practice_seed_policy["chapter_end_practice_plan"] == restored.chapter_end_practice_plan
    assert restored.quantity_constraints.chapter_end_question_count == total


@pytest.mark.anyio
@pytest.mark.parametrize("scenario", ["valid", "repair", "exhausted"])
async def test_existing_structured_feedback_repairs_the_total_without_dropping_user_groups(monkeypatch, scenario) -> None:
    calls: list[dict] = []

    class Provider:
        async def aresponses(self, **kwargs):
            calls.append(kwargs)
            payload = _brief_payload(total=9 if scenario == "valid" or scenario == "repair" and len(calls) > 1 else 5)
            return SimpleNamespace(
                output_text=json.dumps(payload, ensure_ascii=False),
                usage=SimpleNamespace(input_tokens=2, output_tokens=3, total_tokens=5),
            )

        async def acompletion(self, **kwargs):
            raise AssertionError("the test must remain on its primary Responses endpoint")

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.example.com")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(structured_calls, "load_litellm", lambda: Provider())
    monkeypatch.setattr(structured_calls, "_load_instructor", lambda: None)
    set_system_settings_override({
        "models": {"primary": "gpt-5.5"},
        "llm": {"api_mode": "responses", "text_endpoint_fallback_enabled": False},
    })
    try:
        if scenario == "exhausted":
            with pytest.raises(LLMCallError, match="question group total 9 must equal chapter_end_question_count 5"):
                await structured_calls.acompletion_structured(
                    ChapterExecutionBriefForGeneration,
                    [{"role": "user", "content": "章末4道练习和5道短测，各组都必须保留。"}],
                    model="primary", max_retries=1,
                )
            assert len(calls) == 2
            return
        result = await structured_calls.acompletion_structured(
            ChapterExecutionBriefForGeneration,
            [{"role": "user", "content": "章末4道练习和5道短测，各组都必须保留。"}],
            model="primary", max_retries=1,
        )
    finally:
        set_system_settings_override({})
    assert result.quantity_constraints.chapter_end_question_count == 9
    assert [item["question_count"] for item in result.chapter_end_practice_plan] == [4, 5]
    assert len(calls) == (1 if scenario == "valid" else 2)
    if scenario == "repair":
        feedback = json.dumps(calls[1]["input"], ensure_ascii=False)
        assert "question group total 9 must equal chapter_end_question_count 5" in feedback
        assert "do not treat this generated total as user-confirmed" in feedback


@pytest.mark.anyio
async def test_invalid_raw_brief_return_cannot_bypass_the_generation_boundary(monkeypatch) -> None:
    calls = 0

    async def invalid_completion(*args, **kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["response_model"] is ChapterExecutionBriefForGeneration
        return _brief_payload(total=5)

    monkeypatch.setattr(chapter_execution_brief, "acompletion_with_fallback", invalid_completion)
    with pytest.raises(chapter_execution_brief.ChapterExecutionBriefError, match="invalid chapter brief schema"):
        await chapter_execution_brief.build_chapter_execution_brief(
            course_name="整数加法", digest_mode="sprint", chapter={"chapter_index": 1}, locked_title="整数加法",
            intent_core={}, glossary_terms=[], claim_targets=[], confusion_targets=[],
        )
    assert calls == 1


@pytest.mark.anyio
async def test_exhausted_brief_failure_stops_assembly_and_body_generation(monkeypatch) -> None:
    progress: list[str] = []

    async def fail_brief(**kwargs):
        raise chapter_execution_brief.ChapterExecutionBriefError("sensitive-invalid-output")

    async def publish(*args, **kwargs):
        progress.append(kwargs["stage"])

    def forbid_assembly(**kwargs):
        raise AssertionError("failed planning must not assemble default tasks")

    monkeypatch.setattr(build_chapter_execution_briefs, "build_chapter_execution_brief", fail_brief)
    monkeypatch.setattr(build_chapter_execution_briefs, "publish_docgen_progress", publish)
    monkeypatch.setattr(assemble_chapter_tasks, "assemble_chapter_generation_plan", forbid_assembly)
    context = WorkflowContext(workflow_name="digest.docgen", course_id="quantity-failure")
    state = {"chapter_task_seed": ChapterGenerationTaskSeed(chapter_index=3).model_dump(mode="json")}
    result = await build_chapter_execution_briefs.build_chapter_execution_briefs_node(context=context)(state)
    assert result["chapter_execution_brief_errors"][0]["chapter_index"] == 3
    assert "请重试构建" in result["chapter_execution_brief_errors"][0]["reason"]
    assert "sensitive-invalid-output" not in json.dumps(result)
    assert "chapter_execution_brief_items" not in result
    assert progress == ["chapter_execution_brief_started"]
    failed_state = {**state, **result}
    error = await assemble_chapter_tasks.build_assemble_chapter_tasks_node(context=context)(failed_state)
    assert "第 3 章" in error["error"]
    failed_state.update(error)
    assert await assemble_chapter_tasks.build_assemble_chapter_tasks_node(context=context)(failed_state) == {}
    assert build_generation_sends(failed_state) == "fail"


@pytest.mark.anyio
async def test_parallel_brief_errors_aggregate_alongside_success_without_generating_bodies(monkeypatch) -> None:
    async def build_brief(**kwargs):
        index = kwargs["chapter"]["chapter_index"]
        if index in (1, 3):
            raise chapter_execution_brief.ChapterExecutionBriefError("invalid-sensitive-model-output")
        return ChapterExecutionBrief(chapter_index=index)

    async def publish(*args, **kwargs):
        return None

    async def forbidden_writer(state):
        raise AssertionError("no chapter body may be generated after brief allocation failures")

    monkeypatch.setattr(build_chapter_execution_briefs, "build_chapter_execution_brief", build_brief)
    monkeypatch.setattr(build_chapter_execution_briefs, "publish_docgen_progress", publish)
    monkeypatch.setattr(build_chapter_execution_briefs, "append_knowledge_build_recent_event", lambda *a, **k: None)
    context = WorkflowContext(workflow_name="digest.docgen", course_id="quantity-fanout")
    workflow = StateGraph(DocGenState)
    workflow.add_node("start", lambda state: {})
    workflow.add_conditional_edges("start", lambda state: [
        Send("brief", {
            "chapter_task_seed": ChapterGenerationTaskSeed(chapter_index=index).model_dump(mode="json"),
            "course_id": "quantity-fanout", "requested_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
        }) for index in (1, 2, 3)
    ])
    workflow.add_node("brief", build_chapter_execution_briefs.build_chapter_execution_briefs_node(context=context))
    workflow.add_node("assemble", assemble_chapter_tasks.build_assemble_chapter_tasks_node(context=context))
    workflow.add_node("generate_chapters", forbidden_writer)
    workflow.add_edge("brief", "assemble")
    workflow.add_conditional_edges("assemble", build_generation_sends, {"fail": END})
    workflow.set_entry_point("start")
    result = await workflow.compile().ainvoke({})
    assert [item["chapter_index"] for item in result["chapter_execution_brief_errors"]] == [1, 3]
    assert [item["chapter_index"] for item in result["chapter_execution_brief_items"]] == [2]
    assert "第 1 章" in result["error"] and "第 3 章" in result["error"]
    assert "sensitive" not in result["error"]
    assert not result.get("chapter_tasks")
