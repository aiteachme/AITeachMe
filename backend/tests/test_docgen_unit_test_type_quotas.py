"""Keep explicit question-type allocations through compilation and review."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.workflows.digest.docgen.lib import chapter_planning, unit_test_generation
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterExecutionBriefForGeneration,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    DocGenContext,
    DocGenIntentProfile,
    LockedChapterTitle,
)
from app.workflows.digest.docgen.lib.unit_tests import (
    ChapterUnitTestGenerationError,
    ChapterUnitTestItem,
    ChapterUnitTestSet,
    unit_test_structure_issues,
)


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


def _payload(plan=None):
    return {
        "chapter_index": 1,
        "teaching_outline": ["讲清整数加法并核验结果"],
        "content_role_targets": {"concept": ["整数加法"]},
        "example_coverage_plan": [{"target": "整数加法"}],
        "quantity_constraints": {"chapter_end_question_count": 9},
        "chapter_end_practice_plan": _plan() if plan is None else plan,
    }


def _items(types):
    return ChapterUnitTestSet(items=[
        ChapterUnitTestItem(
            type=kind, target=f"整数加法考点{i}", stem=f"计算 {i}+1。",
            answer=str(i + 1), basis=f"{i}+1={i + 1}。",
        ) for i, kind in enumerate(types, start=1)
    ])


async def _generate(plan, caller):
    return await unit_test_generation.generate_chapter_unit_test_markdown(
        chapter_index=1, chapter_title=TITLE, digest_mode="sprint", required_elements=["整数加法"],
        chapter_end_practice_plan=plan, body_markdown=f"# {TITLE}\n\n## 加一\n\n整数加一得到下一个整数。",
        min_items=9, max_items=9,
        writing_contract={"quantity_constraints": {"chapter_end_question_count": 9}},
        llm_caller=caller,
    )


def test_generation_schema_exposes_optional_canonical_question_type():
    schema = ChapterExecutionBriefForGeneration.model_json_schema()
    items = schema["properties"]["chapter_end_practice_plan"]["items"]
    group = schema["$defs"][items["$ref"].rsplit("/", 1)[-1]]
    alternatives = group["properties"]["question_type"]["anyOf"]

    assert next(item["enum"] for item in alternatives if "enum" in item) == [
        "概念判断", "选择题", "填空题", "步骤排序", "错因辨析", "短答题", "应用迁移", "图表读取", "推导证明",
    ]
    assert {"type": "null"} in alternatives
    assert "question_type" not in group.get("required", [])


def test_type_allocations_survive_cleaning_task_compilation_and_persisted_json():
    brief = ChapterExecutionBriefForGeneration.model_validate(_payload())
    restored_brief = ChapterExecutionBrief.model_validate_json(brief.model_dump_json())
    task = chapter_planning.assemble_chapter_generation_plan(
        docgen_context=DocGenContext(course_name=TITLE, digest_mode="sprint"),
        confirmed_chapters=[{"chapter_index": 1, "title": TITLE}],
        locked_titles=[LockedChapterTitle(chapter_index=1, confirmed_title=TITLE, enhanced_title=TITLE)],
        intent_profile=DocGenIntentProfile(), file_summaries=[],
        task_seeds=[ChapterGenerationTaskSeed(chapter_index=1, confirmed_title=TITLE)],
        chapter_execution_briefs=[restored_brief],
    ).chapters[0]
    restored_task = ChapterGenerationTask.model_validate_json(task.model_dump_json())

    for actual in (
        brief.chapter_end_practice_plan, restored_brief.chapter_end_practice_plan,
        restored_task.chapter_end_practice_plan, restored_task.practice_seed_policy["chapter_end_practice_plan"],
    ):
        assert [(item["question_type"], item["question_count"]) for item in actual] == [
            ("应用迁移", 4), ("填空题", 5),
        ]


@pytest.mark.parametrize("model", [ChapterExecutionBrief, ChapterExecutionBriefForGeneration, ChapterGenerationTask])
@pytest.mark.parametrize("invalid_type", ["", "自由题", "应用题", True])
def test_invalid_explicit_type_cannot_be_silently_dropped(model, invalid_type):
    payload = _payload()
    payload["chapter_end_practice_plan"][0]["question_type"] = invalid_type
    with pytest.raises(ValidationError):
        model.model_validate(payload)


@pytest.mark.parametrize("model", [ChapterExecutionBrief, ChapterExecutionBriefForGeneration, ChapterGenerationTask])
def test_explicit_type_without_its_count_cannot_become_an_unenforceable_legacy_plan(model):
    plan = _plan()
    for group in plan:
        del group["question_count"]
    with pytest.raises(ValidationError):
        model.model_validate(_payload(plan))


@pytest.mark.anyio
@pytest.mark.parametrize("recover", [True, False])
async def test_review_relabeling_retries_with_counts_then_recovers_or_stops(monkeypatch, recover):
    stages = []
    feedback = []
    review_builder = unit_test_generation.build_chapter_unit_test_review_messages

    def capture_review(**kwargs):
        feedback.append(kwargs["generation_issue"])
        return review_builder(**kwargs)

    async def caller(messages, **kwargs):
        stage = kwargs["extra_metadata"]["docgen_stage"]
        stages.append(stage)
        if stage == "generate_chapter_unit_test":
            return _items(EXPECTED_TYPES)
        if recover and stages.count("review_chapter_unit_test") == 2:
            return _items(EXPECTED_TYPES)
        # Same stems, answers and nine questions; only Q04's display type drifts.
        return _items(DRIFTED_TYPES)

    monkeypatch.setattr(unit_test_generation, "build_chapter_unit_test_review_messages", capture_review)
    if recover:
        markdown = await _generate(_plan(), caller)
        assert markdown.count("｜应用迁移｜") == 4
        assert markdown.count("｜填空题｜") == 5
        assert "｜错因辨析｜" not in markdown
        assert unit_test_structure_issues(markdown, expected_question_count=9) == []
    else:
        with pytest.raises(ChapterUnitTestGenerationError):
            await _generate(_plan(), caller)
    assert stages == ["generate_chapter_unit_test", "review_chapter_unit_test", "review_chapter_unit_test"]
    assert len(feedback) == 2 and feedback[0] == ""
    assert "应用迁移" in feedback[1] and "4" in feedback[1] and "3" in feedback[1]


@pytest.mark.anyio
@pytest.mark.parametrize("satisfy_combined_quota", [True, False])
async def test_separate_groups_of_the_same_type_add_their_quotas(satisfy_combined_quota):
    plan = [
        {"target": "温度场景", "question_count": 2, "question_type": "应用迁移"},
        {"target": "收支场景", "question_count": 2, "question_type": "应用迁移"},
        {"target": "知识短测", "question_count": 5, "question_type": "填空题"},
    ]
    types = EXPECTED_TYPES if satisfy_combined_quota else ["应用迁移"] * 2 + ["错因辨析"] * 2 + ["填空题"] * 5

    async def caller(messages, **kwargs):
        return _items(types)

    if satisfy_combined_quota:
        markdown = await _generate(plan, caller)
        assert markdown.count("｜应用迁移｜") == 4
        assert markdown.count("｜填空题｜") == 5
    else:
        with pytest.raises(ChapterUnitTestGenerationError):
            await _generate(plan, caller)


@pytest.mark.anyio
@pytest.mark.parametrize("explicit_null", [False, True])
async def test_historical_plan_without_explicit_types_allows_review_to_relabel_questions(explicit_null):
    plan = _plan()
    for group in plan:
        if explicit_null:
            group["question_type"] = None
        else:
            del group["question_type"]
    stages = []

    async def caller(messages, **kwargs):
        stage = kwargs["extra_metadata"]["docgen_stage"]
        stages.append(stage)
        return _items(EXPECTED_TYPES if stage == "generate_chapter_unit_test" else DRIFTED_TYPES)

    markdown = await _generate(plan, caller)
    assert stages == ["generate_chapter_unit_test", "review_chapter_unit_test"]
    assert markdown.count("｜应用迁移｜") == 3
    assert markdown.count("｜错因辨析｜") == 1
    assert markdown.count("｜填空题｜") == 5


@pytest.mark.anyio
@pytest.mark.parametrize("meet_minimum", [True, False])
async def test_partial_type_plan_reserves_explicit_quota_and_leaves_other_groups_free(meet_minimum):
    plan = _plan()
    del plan[1]["question_type"]
    # Unspecified groups may use the specified type too, so five applications is valid.
    types = ["应用迁移"] * 5 + ["错因辨析"] * 4 if meet_minimum else DRIFTED_TYPES

    async def caller(messages, **kwargs):
        return _items(types)

    if meet_minimum:
        markdown = await _generate(plan, caller)
        assert markdown.count("｜应用迁移｜") == 5
        assert markdown.count("｜错因辨析｜") == 4
        assert unit_test_structure_issues(markdown, expected_question_count=9) == []
    else:
        with pytest.raises(ChapterUnitTestGenerationError):
            await _generate(plan, caller)


@pytest.mark.anyio
@pytest.mark.parametrize("invalid_plan", [
    [{"target": "情境练习", "question_count": 9, "question_type": "自由题"}],
    [{"target": "情境练习", "question_type": "应用迁移"}],
])
async def test_raw_generation_boundary_cannot_silently_ignore_an_invalid_explicit_quota(invalid_plan):
    calls = []

    async def caller(messages, **kwargs):
        calls.append(kwargs["extra_metadata"]["docgen_stage"])
        return _items(EXPECTED_TYPES)

    with pytest.raises(ChapterUnitTestGenerationError):
        await _generate(deepcopy(invalid_plan), caller)
    assert calls == []
