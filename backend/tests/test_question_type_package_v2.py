"""Regression tests for the minimal V2 generic text-form contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.schemas.exams import ExamGenerateRequest, MasteryDrillPrepareRequest
from app.shared.kernel.question_type_runtime import assess_custom_question_type_runtime
from app.workflows.examine.exam_grade.lib.grader import (
    CustomRubricCriterionPayload,
    CustomRubricGradePayload,
    _validate_custom_grade_payload,
)
from app.workflows.examine.question_types.answers import normalize_custom_reference_answer
from app.workflows.support.question_type_packages import build_atqskill_archive, validate_atqskill


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V2_EXAMPLE = REPOSITORY_ROOT / "examples" / "question-type-skills" / "experiment_design"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("name", ["feynman_explanation", "experiment_design", "case_analysis", "oral_defense", "scenario_interview", "argument_debate", "source_evaluation"])
@pytest.mark.anyio
async def test_free_fields_survive_generation_snapshot_and_grading(tmp_path, monkeypatch, name):
    import json
    from app.api.exams import _custom_runtime_persistence_payload
    from app.models import ExamPaperItem, KnowledgeUnit
    from app.workflows.examine.question_build.lib import generator
    from app.workflows.examine.exam_grade.lib import grader
    from pydantic import ValidationError

    source = V2_EXAMPLE.parent / name
    if name == "source_evaluation":
        # A seventh type changes both identity and fields without registering code.
        import shutil
        source = tmp_path / "new-type"
        shutil.copytree(V2_EXAMPLE.parent / "case_analysis", source)
        for path in source.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".json"}:
                text = path.read_text("utf-8").replace("case_analysis", name).replace("recommendation", "verdict").replace("reasoning", "rationale")
                path.write_text(text, encoding="utf-8")
    package = build_atqskill_archive(source, tmp_path / "form.atqskill")
    validation = validate_atqskill(package)
    assert validation.valid, validation.errors
    definition = validation.compiled_definition.model_dump(mode="json")
    runtime = dict(registry_id=1, version_id=2, type_key=definition["type_key"],
                   version=definition["version"], package_hash=validation.package_hash,
                   profile_eligible=False, definition=definition)
    reference = definition["reference_cases"][0]["answers"][0]["content"]
    calls = []

    async def generate_stub(messages, *, response_model, **kwargs):
        calls.append("generate")
        data = dict(item_order=1, question_type=definition["type_key"], difficulty="medium",
                    stem=definition["reference_cases"][0]["question"]["stem"],
                    correct_answer="A reference overview.", reference_answer_payload=reference,
                    explanation="Use controlled comparisons and identify the limits of the evidence.",
                    knowledge_unit_refs=[dict(knowledge_unit_id=1, coverage_weight=1, role="primary")])
        with pytest.raises(ValidationError):
            response_model.model_validate({**data, "reference_answer_payload": {**reference, "unknown_field": "extra"}})
        with pytest.raises(ValidationError):
            response_model.model_validate({**data, "reference_answer_payload": {key: value for key, value in reference.items() if key != next(iter(reference))}})
        return response_model.model_validate(data)

    monkeypatch.setattr(generator, "acompletion_with_fallback", generate_stub)
    draft = await generator._generate_one_exam_question(
        unit_by_id={1: KnowledgeUnit(id=1, course_id="course-test", canonical_name="Controlled comparisons", summary="Control confounding variables.")},
        spec=generator.ExamQuestionGenerationSpec(item_order=1, question_type=definition["type_key"], difficulty="medium", knowledge_unit_id=1, knowledge_unit_ids=[1]),
        custom_runtime=runtime,
    )
    frozen = _custom_runtime_persistence_payload(runtime, answer=draft.correct_answer, answer_payload=draft.reference_answer_payload)
    assert frozen["reference_answer"] == reference
    assert frozen["profile_eligible"] is False
    assert list(frozen["reference_answer"]) == [field["key"] for field in definition["answer_fields"]]
    keys = list(reference)

    async def grade_stub(messages, **kwargs):
        calls.append("grade")
        return grader.CustomRubricGradePayload(
            criteria=[dict(key=row["key"], score_ratio=1, evidence=[dict(field_key=key, quote=reference[key][:30]) for key in keys[:2]]) for row in definition["rubric"]],
            feedback_text="Your answer uses the relevant evidence and states appropriate limits.",
        )
    monkeypatch.setattr(grader, "acompletion_with_fallback", grade_stub)
    item = ExamPaperItem(exam_paper_id=1, item_order=1, question_type=definition["type_key"],
        question_type_version_id=2, score=7, difficulty="medium", stem_snapshot=draft.stem,
        answer_snapshot=draft.correct_answer, explanation_snapshot=draft.explanation,
        answer_payload_json=json.dumps(reference),
        answer_schema_snapshot_json=json.dumps(frozen["answer_schema"]),
        reference_answer_snapshot_json=json.dumps(frozen["reference_answer"]),
        grading_spec_snapshot_json=json.dumps(frozen["grading_spec"]),
        runtime_snapshot_json=json.dumps(frozen["runtime_snapshot"]), profile_eligible=False)
    decision = await grader._grade_custom_rubric_item("Course", item)
    assert decision.score_obtained == pytest.approx(7)
    assert all(span["field_label"] for row in decision.grading_detail["criteria"] for span in row["evidence_spans"])
    assert calls == ["generate", "grade"]  # Feedback comes from the same grading call.
    item.answer_payload_json = json.dumps({key: "" for key in keys})
    assert (await grader._grade_custom_rubric_item("Course", item)).score_obtained == 0
    assert calls == ["generate", "grade"]


@pytest.mark.anyio
async def test_mixed_quota_plan_and_backfill_target_only_missing_types():
    from collections import Counter
    from app.api.exams import _mastery_drill_backfill_plan
    from app.models import QuestionTemplate
    from app.workflows.examine.question_build.lib.generator import plan_exam_question_requirements
    types = ["single_choice", "custom_experiment_design", "custom_case_analysis"]
    quotas = dict(zip(types, [2, 3, 1]))
    for mode in ["web_practice", "paper_exam", "mastery_drill"]:
        plans, _ = await plan_exam_question_requirements(exam_mode=mode, question_count=6,
            configured_question_types=types, configured_question_counts=quotas, custom_question_type_keys=types[1:])
        assert Counter(plan.question_type for plan in plans) == quotas
    templates = [QuestionTemplate(course_id="course-test", question_type=key, difficulty="medium", stem=f"Question {i}", stem_hash=f"hash-{i}", answer="answer", explanation="explanation") for i, key in enumerate([types[0]] * 10 + [types[1], types[2]])]
    count, missing = _mastery_drill_backfill_plan(templates=templates, requested_count=6, configured_question_types=types, question_type_counts=quotas)
    assert (count, missing) == (2, [types[1]])


def test_new_selection_rejects_ambiguous_legacy_fields_and_partial_quotas():
    from pydantic import ValidationError
    for data in [
        dict(question_types=["single_choice"], question_type_selections=[dict(registry_id=1)]),
        dict(question_type_selections=[dict(registry_id=1, count=1), dict(question_type="single_choice")]),
        dict(question_type_selections=[dict(registry_id=1), dict(registry_id=1, version_id=2)]),
    ]:
        with pytest.raises(ValidationError):
            ExamGenerateRequest(exam_mode="web_practice", **data)


def test_reference_required_empty_and_nontext_are_invalid_but_unanswered_submission_is_valid():
    from app.workflows.examine.question_types.answers import AnswerPayloadError, normalize_custom_answer
    schema = {"fields": [{"key": "reason", "label": "Reason", "required": True, "max_length": 100}]}
    for payload in [{"reason": ""}, {"reason": 123}]:
        with pytest.raises(AnswerPayloadError):
            normalize_custom_reference_answer(schema, answer=None, answer_payload=payload)
    assert normalize_custom_answer(schema, answer=None, answer_payload={"reason": ""}).payload == {"reason": ""}


def test_v2_example_accepts_unknown_package_key_and_free_answer_fields(tmp_path: Path) -> None:
    package = build_atqskill_archive(V2_EXAMPLE, tmp_path / "experiment-design.atqskill")

    result = validate_atqskill(package)

    assert result.valid is True
    assert result.errors == []
    assert result.preview is not None
    assert result.preview.template_key == "generic_text_form_v2"
    assert result.preview.answer_field_count == 4
    assert result.compiled_definition is not None
    assert result.compiled_definition.schema_version == "aiteachme.question-skill/v2"
    assert [field.key for field in result.compiled_definition.answer_fields] == [
        "hypothesis",
        "procedure",
        "controls",
        "interpretation",
    ]


def test_question_selection_contract_allows_builtin_and_multiple_custom_types() -> None:
    generation = ExamGenerateRequest(
        exam_mode="web_practice",
        question_types=["short_answer"],
        question_type_registry_ids=[11, 12],
    )
    drill = MasteryDrillPrepareRequest(
        num_questions=4,
        question_types=["fill_blank"],
        question_type_registry_ids=[11, 12],
    )

    assert generation.question_types == ["short_answer"]
    assert generation.question_type_registry_ids == [11, 12]
    assert drill.question_types == ["fill_blank"]
    assert drill.question_type_registry_ids == [11, 12]


def test_v2_package_is_ready_when_structured_renderer_is_published(tmp_path: Path) -> None:
    package = build_atqskill_archive(V2_EXAMPLE, tmp_path / "experiment-design.atqskill")
    result = validate_atqskill(package)
    assert result.compiled_definition is not None

    availability = assess_custom_question_type_runtime(
        result.compiled_definition.model_dump(mode="json"),
    )

    assert availability.ready is True
    assert availability.message == ""


def test_reference_answer_normalization_preserves_field_identity() -> None:
    normalized = normalize_custom_reference_answer(
        {
            "fields": [
                {"key": "hypothesis", "label": "假设", "required": True, "max_length": 100},
                {"key": "procedure", "label": "步骤", "required": True, "max_length": 100},
                {"key": "controls", "label": "变量", "required": True, "max_length": 100},
                {"key": "interpretation", "label": "解释", "required": True, "max_length": 100},
            ]
        },
        answer="摘要文本",
        answer_payload={
            "hypothesis": "可检验的假设",
            "procedure": "按顺序执行步骤",
            "controls": "保持其他变量一致",
            "interpretation": "根据结果判断假设",
        },
    )

    assert list(normalized.payload) == [
        "hypothesis",
        "procedure",
        "controls",
        "interpretation",
    ]
    assert "假设" in normalized.display_text
    assert "步骤" in normalized.display_text


def test_structured_grading_evidence_must_identify_the_answer_field() -> None:
    result = CustomRubricGradePayload(
        criteria=[
            CustomRubricCriterionPayload(
                key="testability",
                score_ratio=1.0,
                field_key="hypothesis",
                evidence=["可检验的假设"],
            )
        ],
        feedback_text="假设清晰且可检验。",
    )

    details = _validate_custom_grade_payload(
        result,
        rubric=[{"key": "testability", "label": "可检验性", "weight": 1.0}],
        original_answer_by_field={
            "hypothesis": "可检验的假设",
            "procedure": "按步骤执行",
        },
        require_field_key=True,
    )

    assert details[0]["field_key"] == "hypothesis"
    assert details[0]["evidence"] == ["可检验的假设"]


def test_structured_grading_rejects_evidence_without_field_key() -> None:
    result = CustomRubricGradePayload(
        criteria=[
            CustomRubricCriterionPayload(
                key="testability",
                score_ratio=1.0,
                evidence=["可检验的假设"],
            )
        ],
        feedback_text="假设清晰且可检验。",
    )

    with pytest.raises(RuntimeError, match="answer field"):
        _validate_custom_grade_payload(
            result,
            rubric=[{"key": "testability", "label": "可检验性", "weight": 1.0}],
            original_answer_by_field={"hypothesis": "可检验的假设"},
            require_field_key=True,
        )


def test_numbered_task_constraint_is_generic_and_does_not_depend_on_package_name(tmp_path):
    import shutil
    from app.workflows.examine.question_types.generation import build_custom_question_messages, validate_custom_question_stem
    from app.workflows.support.question_type_packages.validator import validate_compiled_question_type_definition

    source = tmp_path / "custom"
    shutil.copytree(V2_EXAMPLE.parent / "feynman_explanation", source)
    skill = source / "SKILL.md"
    original = skill.read_text("utf-8").replace("package_key: feynman_explanation", "package_key: comparison_report").replace("numbered_task_count: 4", "numbered_task_count: 2")
    skill.write_text(original, encoding="utf-8")
    result = validate_atqskill(build_atqskill_archive(source, tmp_path / "valid.atqskill"))
    assert result.valid, result.errors
    definition = result.compiled_definition
    assert validate_compiled_question_type_definition(definition) == []
    runtime = {"definition": definition.model_dump(mode="json")}
    validate_custom_question_stem(runtime=runtime, stem="Compare:\n\n(1) First task.\n\n(2) Second task.")
    with pytest.raises(ValueError, match="exactly 2"):
        validate_custom_question_stem(runtime=runtime, stem="Only a general paragraph.")
    messages = build_custom_question_messages(runtime=runtime, units=[], spec={})
    assert "exactly 2 blank-line-separated requirements" in messages[0]["content"]
    assert "Feynman explanation template" not in messages[0]["content"]
    for invalid in ("0", "9", "true", "2.5"):
        skill.write_text(original.replace("numbered_task_count: 2", f"numbered_task_count: {invalid}"), encoding="utf-8")
        result = validate_atqskill(build_atqskill_archive(source, tmp_path / "invalid.atqskill"))
        assert not result.valid
        assert any(issue.code == "SCHEMA_INVALID" for issue in result.errors)
