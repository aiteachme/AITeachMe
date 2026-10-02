from __future__ import annotations

import json

import pytest

from app.api import exams as exams_api
from app.models import ExamPaperItem, KnowledgeUnit, QuestionTemplate
from app.shared.infra.exceptions import AITeachMeError, InvalidImportPackageError
from app.shared.kernel.question_types import (
    CANONICAL_QUESTION_TYPE_KEYS,
    UnsupportedQuestionTypeError,
    normalize_question_type_key,
    question_type_grading_kind,
    require_supported_question_type_key,
)
from app.workflows.examine.exam_grade.lib import grader
from app.workflows.examine.question_build.lib import generator
from app.workflows.examine.question_build.lib.generator import ExamQuestionDraft
from app.workflows.examine.question_types.answers import (
    AnswerPayloadError,
    normalize_custom_answer,
)
from app.workflows.examine.question_types.generation import (
    validate_custom_question_stem,
)
from app.workflows.support.export_import.imports import _validate_imported_question_types
from migrations.seed_data.question_types import BUILTIN_QUESTION_TYPE_ROWS


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _paper_item(question_type: str) -> ExamPaperItem:
    return ExamPaperItem(
        exam_paper_id=1,
        question_template_id=1,
        item_order=1,
        stem_snapshot="Explain the concept.",
        answer_snapshot="Reference answer",
        explanation_snapshot="Reference explanation",
        difficulty="medium",
        question_type=question_type,
        score=1.0,
        answer_content="User answer",
    )


def _custom_paper_item(*, answer: str = "极限描述趋近关系，并不等于函数在该点的取值。") -> ExamPaperItem:
    return ExamPaperItem(
        exam_paper_id=1,
        question_template_id=1,
        question_type_registry_id=7,
        question_type_version_id=11,
        item_order=1,
        stem_snapshot="请向初学者解释函数极限，并说明它与函数点值的区别。",
        answer_snapshot="极限描述函数值在自变量趋近某点时的趋向，点值可以不同甚至不存在。",
        explanation_snapshot="应准确说明趋近关系，并区分极限与点值。",
        reference_answer_snapshot_json=json.dumps(
            {"explanation": "极限描述函数值的趋向，点值可以与极限不同。"},
            ensure_ascii=False,
        ),
        grading_spec_snapshot_json=json.dumps(
            {
                "grader_key": "rubric_llm_v1",
                "pass_score": 0.7,
                "grade_prompt": "按冻结评分标准判断。",
                "reference_cases": [],
                "rubric": [
                    {
                        "key": "accuracy",
                        "label": "概念准确性",
                        "weight": 0.6,
                        "description": "概念无实质错误。",
                    },
                    {
                        "key": "boundary",
                        "label": "适用边界",
                        "weight": 0.4,
                        "description": "说明极限与点值的区别。",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        runtime_snapshot_json=json.dumps(
            {
                "type_key": "custom_feynman_explanation",
                "template_key": "feynman_explanation_v1",
                "runtime_key": "structured_subjective_v1",
                "renderer_key": "long_text_v1",
                "grader_key": "rubric_llm_v1",
            }
        ),
        answer_schema_snapshot_json=json.dumps(
            {
                "fields": [
                    {
                        "key": "explanation",
                        "label": "你的解释",
                        "required": True,
                        "min_length": 30,
                        "max_length": 4000,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        difficulty="medium",
        question_type="custom_feynman_explanation",
        score=5.0,
        answer_content=answer,
        answer_payload_json=json.dumps({"explanation": answer}, ensure_ascii=False),
        profile_eligible=False,
    )


def test_custom_answer_normalization_uses_frozen_schema() -> None:
    schema = {
        "fields": [
            {
                "key": "explanation",
                "label": "你的解释",
                "required": True,
                "min_length": 5,
                "max_length": 20,
            }
        ]
    }

    normalized = normalize_custom_answer(
        schema,
        answer=None,
        answer_payload={"explanation": "这是完整解释"},
    )
    assert normalized.payload == {"explanation": "这是完整解释"}
    assert normalized.display_text == "这是完整解释"

    with pytest.raises(AnswerPayloadError) as short_error:
        normalize_custom_answer(
            schema,
            answer=None,
            answer_payload={"explanation": "短"},
        )
    assert short_error.value.code == "QUESTION_ANSWER_TOO_SHORT"

    with pytest.raises(AnswerPayloadError) as unknown_error:
        normalize_custom_answer(
            schema,
            answer=None,
            answer_payload={"explanation": "这是完整解释", "override_score": "1"},
        )
    assert unknown_error.value.code == "QUESTION_ANSWER_FIELD_UNKNOWN"


def test_question_type_contract_matches_seed_and_normalizes_legacy_alias() -> None:
    seed_keys = tuple(str(row["type_key"]) for row in BUILTIN_QUESTION_TYPE_ROWS)

    assert seed_keys == CANONICAL_QUESTION_TYPE_KEYS
    assert normalize_question_type_key(" MULTI_CHOICE ") == "multiple_choice"
    assert require_supported_question_type_key("multi_choice") == "multiple_choice"
    assert question_type_grading_kind("multiple_choice") == "objective"
    assert question_type_grading_kind("short_answer") == "subjective"


def test_question_type_contract_rejects_unknown_type() -> None:
    with pytest.raises(UnsupportedQuestionTypeError, match="dialogue"):
        require_supported_question_type_key("dialogue")


def test_question_generation_schema_accepts_dynamic_type_shape() -> None:
    draft = ExamQuestionDraft.model_validate(
        {
            "item_order": 1,
            "question_type": "custom_feynman_explanation",
            "difficulty": "medium",
            "stem": "Explain this concept to a learner who has not seen it before.",
            "correct_answer": "A complete reference explanation with an example and a boundary.",
            "explanation": "The response should be accurate and explain its reasoning and limits.",
            "knowledge_unit_refs": [{"knowledge_unit_id": 1, "coverage_weight": 1.0}],
        }
    )

    assert draft.question_type == "custom_feynman_explanation"


@pytest.mark.anyio
async def test_dynamic_generation_requires_resolved_runtime() -> None:
    unit = KnowledgeUnit(
        id=1,
        course_id="course",
        knowledge_unit_type="concept",
        canonical_name="Limit",
        normalized_name="limit",
        summary="Definition and boundary behavior.",
        status="active",
    )
    spec = generator.ExamQuestionGenerationSpec(
        item_order=1,
        knowledge_unit_id=1,
        knowledge_unit_ids=[1],
        question_type="custom_feynman_explanation",
        difficulty="medium",
    )

    with pytest.raises(ValueError, match="runtime was not resolved"):
        await generator.generate_exam_questions_for_units(units=[unit], specs=[spec])


@pytest.mark.anyio
async def test_dynamic_generation_uses_frozen_package_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_messages: list[dict[str, str]] = []

    async def run_immediately(items, worker, *, on_result=None, **_kwargs):
        results = []
        for index, item in enumerate(items):
            result = await worker(item)
            results.append(result)
            if on_result is not None:
                await on_result(index, item, result)
        return results

    async def fake_completion(messages, **_kwargs):
        captured_messages.extend(messages)
        return generator.ExamSingleQuestionResponse(
            question=generator.ExamQuestionDraft(
                item_order=1,
                question_type="custom_feynman_explanation",
                difficulty="medium",
                stem=(
                    "请面向初学者解释函数极限，并回答：\n\n"
                    "(1) 函数极限的核心含义是什么？\n\n"
                    "(2) 为什么极限与函数点值不同？\n\n"
                    "(3) 请给出一个具体例子。\n\n"
                    "(4) 请说明一个适用边界。"
                ),
                correct_answer="函数极限描述自变量趋近某点时函数值的稳定趋向，并不要求点值相同。",
                explanation="应说明趋近关系、给出例子，并区分极限与函数在该点的取值。",
                knowledge_unit_refs=[
                    generator.ExamQuestionUnitRef(knowledge_unit_id=1, coverage_weight=1.0),
                ],
            )
        )

    monkeypatch.setattr(generator, "run_llm_tasks", run_immediately)
    monkeypatch.setattr(generator, "acompletion_with_fallback", fake_completion)
    unit = KnowledgeUnit(
        id=1,
        course_id="course",
        knowledge_unit_type="concept",
        canonical_name="函数极限",
        normalized_name="函数极限",
        summary="函数在某点附近的趋近行为。",
        status="active",
    )
    spec = generator.ExamQuestionGenerationSpec(
        item_order=1,
        knowledge_unit_id=1,
        knowledge_unit_ids=[1],
        question_type="custom_feynman_explanation",
        difficulty="medium",
    )
    runtime = {
        "registry_id": 7,
        "version_id": 11,
        "type_key": "custom_feynman_explanation",
        "version": "1.0.0",
        "package_hash": "abc123",
        "profile_eligible": False,
        "definition": {
            "display_name": "费曼解释题",
            "template_key": "feynman_explanation_v1",
            "runtime_key": "structured_subjective_v1",
            "renderer_key": "long_text_v1",
            "grader_key": "rubric_llm_v1",
            "answer_fields": [{"key": "explanation", "label": "你的解释"}],
            "rubric": [{"key": "accuracy", "label": "概念准确性", "weight": 1.0}],
            "reference_cases": [],
            "prompts": {"generate": "冻结的费曼出题要求 ${knowledge_units}"},
        },
    }

    questions = await generator.generate_exam_questions_for_units(
        units=[unit],
        specs=[spec],
        question_type_runtimes=[runtime],
    )

    assert [item.question_type for item in questions] == ["custom_feynman_explanation"]
    assert captured_messages[0]["role"] == "system"
    assert "blank-line-separated (1), (2), ... items" in captured_messages[0]["content"]
    assert "exactly four blank-line-separated requirements" in captured_messages[0]["content"]
    assert "冻结的费曼出题要求" in captured_messages[1]["content"]


def test_feynman_stem_validation_rejects_stacked_wording_and_missing_numbers() -> None:
    runtime = {"definition": {"template_key": "feynman_explanation_v1"}}

    with pytest.raises(ValueError, match="stacked learner-facing wording"):
        validate_custom_question_stem(
            runtime=runtime,
            stem="请像向第一次接触高等数学的人讲解一样，解释函数极限。",
        )
    with pytest.raises(ValueError, match=r"numbered \(1\) through \(4\)"):
        validate_custom_question_stem(
            runtime=runtime,
            stem="请解释函数极限的含义、依据、例子和适用边界。",
        )


def test_feynman_stem_validation_accepts_four_numbered_requirements() -> None:
    validate_custom_question_stem(
        runtime={"definition": {"template_key": "feynman_explanation_v1"}},
        stem=(
            "请面向初学者解释函数极限，并回答：\n\n"
            "(1) 核心含义是什么？\n\n"
            "(2) 为什么需要关注变化趋势？\n\n"
            "(3) 请给出一个具体例子。\n\n"
            "(4) 请说明一个适用边界。"
        ),
    )


@pytest.mark.anyio
async def test_feynman_generation_retries_after_stem_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion_calls = 0

    async def fake_completion(*_args, **_kwargs):
        nonlocal completion_calls
        completion_calls += 1
        stem = (
            "请像向第一次接触高等数学的人讲解一样，解释函数极限。"
            if completion_calls == 1
            else (
                "请面向初学者解释函数极限，并回答：\n\n"
                "(1) 核心含义是什么？\n\n"
                "(2) 为什么极限与函数点值不同？\n\n"
                "(3) 请给出一个具体例子。\n\n"
                "(4) 请说明一个适用边界。"
            )
        )
        return generator.ExamSingleQuestionResponse(
            question=generator.ExamQuestionDraft(
                item_order=1,
                question_type="custom_feynman_explanation",
                difficulty="medium",
                stem=stem,
                correct_answer="函数极限描述函数值随自变量趋近某点时的稳定趋向。",
                explanation="应说明核心含义、依据、例子和边界。",
                knowledge_unit_refs=[
                    generator.ExamQuestionUnitRef(
                        knowledge_unit_id=1,
                        coverage_weight=1.0,
                    )
                ],
            )
        )

    monkeypatch.setattr(generator, "acompletion_with_fallback", fake_completion)
    unit = KnowledgeUnit(
        id=1,
        course_id="course",
        knowledge_unit_type="concept",
        canonical_name="函数极限",
        normalized_name="函数极限",
        summary="函数在某点附近的趋近行为。",
        status="active",
    )
    spec = generator.ExamQuestionGenerationSpec(
        item_order=1,
        knowledge_unit_id=1,
        knowledge_unit_ids=[1],
        question_type="custom_feynman_explanation",
        difficulty="medium",
    )
    runtime = {
        "registry_id": 7,
        "version_id": 11,
        "type_key": "custom_feynman_explanation",
        "definition": {
            "template_key": "feynman_explanation_v1",
            "answer_fields": [{"key": "explanation", "label": "你的解释"}],
            "rubric": [],
            "reference_cases": [],
            "prompts": {"generate": "生成一道费曼解释题。"},
        },
    }

    question = await generator._generate_one_exam_question(
        unit_by_id={1: unit},
        spec=spec,
        custom_runtime=runtime,
    )

    assert completion_calls == 2
    assert "(4)" in question.stem


@pytest.mark.anyio
async def test_grader_rejects_unknown_type_before_scheduling_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    llm_scheduled = False

    async def fail_if_scheduled(*_args, **_kwargs):
        nonlocal llm_scheduled
        llm_scheduled = True
        raise AssertionError("LLM grading must not run for an unsupported question type")

    monkeypatch.setattr(grader, "run_llm_tasks", fail_if_scheduled)

    with pytest.raises(UnsupportedQuestionTypeError, match="dialogue"):
        await grader.grade_exam_items_with_workflow(course_name="Course", items=[_paper_item("dialogue")])

    assert llm_scheduled is False


@pytest.mark.anyio
async def test_objective_types_use_rules_and_existing_explanation_without_scheduling_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_if_scheduled(*_args, **_kwargs):
        raise AssertionError("Objective grading must not enter the LLM scheduler")

    monkeypatch.setattr(grader, "run_llm_tasks", fail_if_scheduled)
    single_choice = _paper_item("single_choice")
    single_choice.answer_snapshot = "A"
    single_choice.answer_content = "A"
    multiple_choice = _paper_item("multiple_choice")
    multiple_choice.answer_snapshot = "A,C"
    multiple_choice.answer_content = "C A"
    true_false = _paper_item("true_false")
    true_false.answer_snapshot = "正确"
    true_false.answer_content = "true"

    decisions = await grader.grade_exam_items_with_workflow(
        course_name="Course",
        items=[single_choice, multiple_choice, true_false],
    )

    assert [decision.is_correct for decision in decisions] == [True, True, True]
    assert all(decision.grading_mode == "objective_rule" for decision in decisions)
    assert all(decision.feedback_text == "Reference explanation" for decision in decisions)


@pytest.mark.anyio
async def test_fill_blank_still_uses_subjective_llm_grading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    llm_called = False

    async def run_immediately(items, worker, **_kwargs):
        return [await worker(item) for item in items]

    async def fake_completion(*_args, **_kwargs):
        nonlocal llm_called
        llm_called = True
        return grader.SubjectiveGradePayload(
            is_correct=True,
            score_obtained=1.0,
            feedback_text="The answer is semantically equivalent to the reference answer.",
            error_cause_label=None,
        )

    monkeypatch.setattr(grader, "run_llm_tasks", run_immediately)
    monkeypatch.setattr(grader, "acompletion_with_fallback", fake_completion)

    decision = (
        await grader.grade_exam_items_with_workflow(
            course_name="Course",
            items=[_paper_item("fill_blank")],
        )
    )[0]

    assert llm_called is True
    assert decision.is_correct is True
    assert decision.grading_mode == "subjective_llm"


@pytest.mark.anyio
async def test_custom_rubric_grading_uses_server_weights_and_exact_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_immediately(items, worker, **_kwargs):
        return [await worker(item) for item in items]

    async def fake_completion(*_args, **_kwargs):
        return grader.CustomRubricGradePayload(
            criteria=[
                grader.CustomRubricCriterionPayload(
                    key="accuracy",
                    score_ratio=1.0,
                    evidence=["极限描述趋近关系"],
                    note="核心概念准确。",
                ),
                grader.CustomRubricCriterionPayload(
                    key="boundary",
                    score_ratio=0.5,
                    evidence=["不等于函数在该点的取值"],
                    note="提到点值区别，但还可补充不存在的情况。",
                ),
            ],
            feedback_text="核心解释正确，建议再补充函数点值不存在时极限仍可能存在的例子。",
            error_cause_label=None,
        )

    monkeypatch.setattr(grader, "run_llm_tasks", run_immediately)
    monkeypatch.setattr(grader, "acompletion_with_fallback", fake_completion)

    decision = (
        await grader.grade_exam_items_with_workflow(
            course_name="高等数学",
            items=[_custom_paper_item()],
        )
    )[0]

    assert decision.grading_mode == "custom_rubric_llm"
    assert decision.is_correct is True
    assert decision.score_max == 5.0
    assert decision.score_obtained == pytest.approx(4.0)
    assert decision.grading_detail["score_ratio"] == pytest.approx(0.8)
    assert [item["key"] for item in decision.grading_detail["criteria"]] == [
        "accuracy",
        "boundary",
    ]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("weights", "ratios", "pass_score", "expected_ratio", "passed"),
    [
        pytest.param([0.1, 0.7, 0.2], [0.75, 0.75, 0.5], 0.7, 0.7, True, id="exact-pass-line"),
        pytest.param([0.33, 0.56, 0.11], [1.0, 1.0, 1.0], 1.0, 1.0, True, id="exact-full-marks"),
        pytest.param(
            [0.1, 0.7, 0.2], [0.75, 0.75, 0.499999999995],
            0.7, 0.699999999999, False, id="genuinely-below-pass-line",
        ),
        pytest.param(
            [0.1, 0.7, 0.2], [0.75, 0.75, 0.500000000005],
            0.7, 0.700000000001, True, id="genuinely-above-pass-line",
        ),
        pytest.param([0.3333] * 3, [1.0] * 3, 1.0, 1.0, True, id="rounded-weights-full-marks"),
        pytest.param([0.3333] * 3, [0.7] * 3, 0.7, 0.7, True, id="rounded-weights-pass-line"),
    ],
)
async def test_custom_rubric_grading_handles_pass_boundaries(
    monkeypatch: pytest.MonkeyPatch,
    weights: list[float],
    ratios: list[float],
    pass_score: float,
    expected_ratio: float,
    passed: bool,
) -> None:
    item = _custom_paper_item()
    item.score = 100.0
    grading_spec = json.loads(item.grading_spec_snapshot_json)
    grading_spec["pass_score"] = pass_score
    grading_spec["rubric"] = [
        {"key": f"criterion_{index}", "label": f"维度 {index}", "weight": weight}
        for index, weight in enumerate(weights)
    ]
    item.grading_spec_snapshot_json = json.dumps(grading_spec, ensure_ascii=False)
    frozen_snapshot = item.grading_spec_snapshot_json

    async def fake_completion(*_args, **_kwargs):
        return grader.CustomRubricGradePayload(
            criteria=[
                grader.CustomRubricCriterionPayload(
                    key=f"criterion_{index}",
                    score_ratio=ratio,
                    evidence=["极限描述趋近关系"],
                )
                for index, ratio in enumerate(ratios)
            ],
            feedback_text="评分严格依据每个维度的表现及其权重计算。",
        )

    monkeypatch.setattr(grader, "acompletion_with_fallback", fake_completion)
    decision = await grader._grade_custom_rubric_item("高等数学", item)

    assert decision.is_correct is passed
    assert decision.grading_detail["score_ratio"] == expected_ratio
    assert decision.score_obtained == pytest.approx(expected_ratio * 100.0, rel=0, abs=1e-13)
    assert sum(row["weight"] for row in decision.grading_detail["criteria"]) == pytest.approx(1.0)
    assert item.grading_spec_snapshot_json == frozen_snapshot


@pytest.mark.anyio
async def test_custom_rubric_grading_retries_invalid_model_evidence_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completion_calls = 0

    async def run_immediately(items, worker, **_kwargs):
        return [await worker(item) for item in items]

    async def fake_completion(*_args, **_kwargs):
        nonlocal completion_calls
        completion_calls += 1
        return grader.CustomRubricGradePayload(
            criteria=[
                grader.CustomRubricCriterionPayload(
                    key="accuracy",
                    score_ratio=1.0,
                    evidence=["模型编造的、不在学生答案中的证据"],
                ),
                grader.CustomRubricCriterionPayload(
                    key="boundary",
                    score_ratio=0.0,
                    evidence=[],
                ),
            ],
            feedback_text="该输出包含无法核验的证据，因此不能作为有效评分结果。",
            error_cause_label="unknown",
        )

    monkeypatch.setattr(grader, "run_llm_tasks", run_immediately)
    monkeypatch.setattr(grader, "acompletion_with_fallback", fake_completion)

    with pytest.raises(RuntimeError, match="custom rubric grading failed"):
        await grader.grade_exam_items_with_workflow(
            course_name="高等数学",
            items=[_custom_paper_item()],
        )

    assert completion_calls == 2


@pytest.mark.anyio
async def test_blank_custom_answer_is_unanswered_without_calling_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run_immediately(items, worker, **_kwargs):
        return [await worker(item) for item in items]

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Blank custom answers must not call the grading model")

    monkeypatch.setattr(grader, "run_llm_tasks", run_immediately)
    monkeypatch.setattr(grader, "acompletion_with_fallback", fail_if_called)

    decision = (
        await grader.grade_exam_items_with_workflow(
            course_name="高等数学",
            items=[_custom_paper_item(answer="")],
        )
    )[0]

    assert decision.is_correct is False
    assert decision.score_obtained == 0.0
    assert decision.grading_detail["score_ratio"] == 0.0
    assert all(item["note"] == "未作答" for item in decision.grading_detail["criteria"])


@pytest.mark.anyio
async def test_single_template_grading_returns_stable_unsupported_type_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_called = False

    async def fail_if_called(**_kwargs):
        nonlocal workflow_called
        workflow_called = True
        raise AssertionError("grading workflow must not run")

    monkeypatch.setattr(exams_api, "run_exam_grade_workflow", fail_if_called)
    template = QuestionTemplate(
        id=1,
        course_id="course",
        question_type="dialogue",
        difficulty="medium",
        stem="Discuss the concept.",
        stem_hash="dialogue",
        answer="Reference answer",
        explanation="Reference explanation",
    )

    with pytest.raises(AITeachMeError) as error:
        await exams_api._grade_question_template_answer(
            course_id="course",
            course_name="Course",
            template=template,
            answer="User answer",
        )

    assert error.value.error_code == "UNSUPPORTED_QUESTION_TYPE"
    assert error.value.status_code == 409
    assert error.value.data == {"question_type": "dialogue"}
    assert workflow_called is False


def test_import_rejects_unknown_runtime_type_and_normalizes_legacy_alias() -> None:
    legacy_records = [{"id": 1, "question_type": "multi_choice"}]
    _validate_imported_question_types("question_template", legacy_records)
    assert legacy_records[0]["question_type"] == "multiple_choice"

    with pytest.raises(InvalidImportPackageError, match="dialogue"):
        _validate_imported_question_types(
            "exam_paper_item",
            [{"id": 2, "question_type": "dialogue"}],
        )
