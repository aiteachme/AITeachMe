import pytest

from app.models.knowledge_unit import KnowledgeUnit
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
