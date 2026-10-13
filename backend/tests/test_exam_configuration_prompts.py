import pytest

from app.models.knowledge_unit import KnowledgeUnit
from app.shared.kernel.question_types import CANONICAL_QUESTION_TYPE_KEYS, UnsupportedQuestionTypeError
from app.workflows.examine.question_build.lib import generator
from app.workflows.examine.question_build.prompts import (
    build_exam_question_blueprint_messages,
    build_exam_question_requirement_messages,
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_exam_blueprint_prompt_enforces_explicit_difficulty_configuration() -> None:
    messages = build_exam_question_blueprint_messages(
        course_name="代数",
        course_description="函数与方程",
        course_user_intent="阶段复习",
        exam_mode="web_practice",
        requested_question_count=10,
        user_prompt="整体难度以挑战为主。",
        units=[{"id": 1, "canonical_name": "函数单调性"}],
        question_prompt_plans=[
            {
                "item_order": 1,
                "question_type": "single_choice",
                "generation_prompt": "整体难度以挑战为主。",
            }
        ],
    )

    prompt = messages[-1]["content"]
    assert "如果 user_prompt 明确指定了整体、题号或题型难度，必须遵守" in prompt
    assert '"user_prompt": "整体难度以挑战为主。"' in prompt


@pytest.mark.anyio
async def test_saved_question_types_build_a_deterministic_hard_constraint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_llm_is_called(*_args, **_kwargs):
        raise AssertionError("structured question types must not depend on another LLM planning call")

    monkeypatch.setattr(generator, "acompletion_with_fallback", fail_if_llm_is_called)

    plans, rationale = await generator.plan_exam_question_requirements(
        exam_mode="web_practice",
        question_count=5,
        user_prompt="重点考查函数单调性。",
        configured_question_types=["single_choice", "true_false"],
    )

    assert [item.question_type for item in plans] == [
        "single_choice",
        "true_false",
        "single_choice",
        "true_false",
        "single_choice",
    ]
    assert all(item.generation_prompt == "重点考查函数单调性。" for item in plans)
    assert "structured configuration" in rationale

    paper_plans, _ = await generator.plan_exam_question_requirements(
        exam_mode="paper_exam",
        question_count=6,
        configured_question_types=["short_answer", "multiple_choice", "single_choice"],
    )
    assert [item.question_type for item in paper_plans] == [
        "single_choice",
        "single_choice",
        "multiple_choice",
        "multiple_choice",
        "short_answer",
        "short_answer",
    ]

    mastery_plans, _ = await generator.plan_exam_question_requirements(
        exam_mode="mastery_drill",
        question_count=4,
        configured_question_types=["fill_blank", "true_false"],
    )
    assert [item.question_type for item in mastery_plans] == [
        "fill_blank",
        "true_false",
        "fill_blank",
        "true_false",
    ]


@pytest.mark.anyio
async def test_default_mastery_plan_and_prompt_support_all_configurable_types(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_llm_is_called(*_args, **_kwargs):
        raise AssertionError("the default mastery plan must be deterministic")

    monkeypatch.setattr(generator, "acompletion_with_fallback", fail_if_llm_is_called)

    plans, rationale = await generator.plan_exam_question_requirements(
        exam_mode="mastery_drill",
        question_count=10,
    )
    question_types = {item.question_type for item in plans}

    assert question_types == {
        "single_choice",
        "multiple_choice",
        "true_false",
        "fill_blank",
        "short_answer",
    }
    assert "mixed-type" in rationale

    prompt = build_exam_question_requirement_messages(
        exam_mode="mastery_drill",
        requested_question_count=5,
        user_prompt="",
    )[-1]["content"]
    assert "fill_blank 和 short_answer 都可使用" in prompt
    assert "不要使用 fill_blank 或 short_answer" not in prompt


def test_saved_difficulty_overrides_blueprint_model_output() -> None:
    unit = KnowledgeUnit(
        id=1,
        course_id="course-config",
        knowledge_unit_type="concept",
        canonical_name="函数单调性",
        normalized_name="函数单调性",
        summary="函数随自变量变化的趋势。",
        status="active",
    )
    prompt_plan = generator.ExamQuestionRequirementPlan(
        item_order=1,
        question_type="single_choice",
        generation_prompt="重点考查函数单调性。",
    )
    generated = generator.ExamQuestionBlueprint(
        item_order=1,
        knowledge_unit_ids=[1],
        question_type="single_choice",
        difficulty="easy",
        rationale="基础识别",
        generation_prompt="",
    )

    blueprints = generator._validate_blueprints(
        generated=[generated],
        units=[unit],
        question_count=1,
        question_prompt_plans=[prompt_plan],
        configured_difficulty="hard",
    )

    assert blueprints[0].difficulty == "hard"


@pytest.mark.anyio
@pytest.mark.parametrize("frozen_type", CANONICAL_QUESTION_TYPE_KEYS)
async def test_blueprints_inherit_frozen_types_without_replanning(monkeypatch, frozen_type) -> None:
    calls = []
    plans = [
        generator.ExamQuestionRequirementPlan(
            item_order=order, question_type=frozen_type, generation_prompt=f"Requirement {order}",
        )
        for order in range(1, 11)
    ]

    async def allocate(*args, **kwargs):
        calls.append(kwargs)
        return generator.ExamQuestionBlueprintBatch.model_validate({
            "blueprints": [
                {
                    "item_order": order, "knowledge_unit_ids": [1],
                    "question_type": "medium" if order == 8 else frozen_type,
                    "difficulty": "medium", "generation_prompt": "Ignore the frozen requirement",
                }
                for order in range(1, 11)
            ],
        })

    monkeypatch.setattr(generator, "acompletion_with_fallback", allocate)
    blueprints = await generator.allocate_exam_question_knowledge_units(
        exam_mode="web_practice",
        units=[KnowledgeUnit(id=1, course_id="course-config", canonical_name="Lists", normalized_name="lists")],
        question_count=10, question_prompt_plans=plans, configured_difficulty="easy",
    )

    assert len(calls) == 1
    assert [item.question_type for item in blueprints] == [frozen_type] * 10
    assert [item.generation_prompt for item in blueprints] == [item.generation_prompt for item in plans]
    assert all(item.difficulty == "easy" for item in blueprints)
    assert all(item.to_generation_spec().question_type == frozen_type for item in blueprints)


@pytest.mark.parametrize("unit_ids, question_count", [([999], 1), ([1], 2)])
def test_frozen_types_do_not_hide_missing_blueprints_or_invalid_knowledge(unit_ids, question_count) -> None:
    with pytest.raises(ValueError, match="invalid or incomplete"):
        generator._validate_blueprints(
            generated=[generator.ExamQuestionBlueprint(
                item_order=1, knowledge_unit_ids=unit_ids, question_type="medium", difficulty="medium",
            )],
            units=[KnowledgeUnit(id=1, course_id="course-config", canonical_name="Lists", normalized_name="lists")],
            question_count=question_count,
            question_prompt_plans=[generator.ExamQuestionRequirementPlan(
                item_order=1, question_type="single_choice", generation_prompt="Test lists",
            )],
        )


@pytest.mark.parametrize("question_type", ["medium", "case_analysis"])
def test_blueprints_without_frozen_types_reject_unsupported_types(question_type) -> None:
    generated = generator.ExamQuestionBlueprint(
        item_order=1, knowledge_unit_ids=[1], question_type=question_type, difficulty="medium",
    )

    with pytest.raises(UnsupportedQuestionTypeError):
        generator._validate_blueprints(
            generated=[generated],
            units=[KnowledgeUnit(id=1, course_id="course-config", canonical_name="Lists", normalized_name="lists")],
            question_count=1,
        )
