"""Boundary regressions found while reviewing generic training contracts."""

from __future__ import annotations

import json
from pathlib import Path
import re
import shutil

import pytest
from pydantic import ValidationError

from app.api import exams as exams_api
from app.models import ExamPaper, ExamPaperItem
from app.schemas.exams import ExamSubmitRequest
from app.shared.infra.exceptions import AITeachMeError
from app.workflows.examine.question_build.lib.generator import (
    ExamQuestionDraft,
    _custom_generation_response_model,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("field_key", ["model_dump", "model_config", "model_fields"])
def test_author_field_names_survive_dynamic_model_roundtrip(field_key: str) -> None:
    fields = [
        {"key": key, "label": key, "required": True, "min_length": 2, "max_length": 100}
        for key in [field_key, "answer_field_0"]
    ]
    response_model = _custom_generation_response_model({
        "definition": {"schema_version": "aiteachme.question-skill/v2", "answer_fields": fields},
    })
    reference = {field["key"]: "A supported reference answer." for field in fields}
    question = {
        "item_order": 1,
        "question_type": "custom_unknown_fields",
        "difficulty": "medium",
        "stem": "Explain the evidence for this conclusion.",
        "correct_answer": "A reference overview.",
        "reference_answer_payload": reference,
        "explanation": "Evaluate the supporting evidence.",
        "knowledge_unit_refs": [{"knowledge_unit_id": 1, "coverage_weight": 1, "role": "primary"}],
    }
    response = response_model.model_validate({"question": question})
    draft = ExamQuestionDraft.model_validate(response.question.model_dump(by_alias=True))
    assert draft.reference_answer_payload == reference
    schema = response_model.model_json_schema()["$defs"]["CustomReferenceAnswer"]
    assert set(schema["properties"]) == set(reference)
    assert set(schema["required"]) == set(reference)
    with pytest.raises(ValidationError):
        response_model.model_validate({"question": {**question, "reference_answer_payload": {field_key: "Only one field."}}})


def _structured_item() -> ExamPaperItem:
    return ExamPaperItem(
        id=12, exam_paper_id=7, item_order=2, question_type="custom_case_analysis",
        question_type_version_id=5, difficulty="medium", stem_snapshot="Explain your decision.",
        answer_snapshot="Reference", explanation_snapshot="Explanation",
        answer_schema_snapshot_json=json.dumps({"fields": [
            {"key": key, "label": key, "required": True, "max_length": 100}
            for key in ["decision", "reason"]
        ]}),
    )


def test_omitted_multifield_item_matches_explicit_blank_submission() -> None:
    builtin = ExamPaperItem(
        id=11, exam_paper_id=7, item_order=1, question_type="fill_blank",
        difficulty="easy", stem_snapshot="Complete this.", answer_snapshot="yes", explanation_snapshot="Why",
    )
    items = [builtin, _structured_item()]
    first = ExamSubmitRequest(answers=[{"item_order": 1, "answer": "yes"}])
    retry = ExamSubmitRequest(answers=[
        {"item_order": 2, "answer_payload": {"reason": "", "decision": ""}},
        {"item_order": 1, "answer": "yes"},
    ])
    first_values = exams_api._resolve_exam_submission_values(items, first)
    retry_values = exams_api._resolve_exam_submission_values(items, retry)
    assert first_values == retry_values
    assert first_values[1] == {12: {"decision": "", "reason": ""}}


def test_explicit_multifield_payload_still_requires_declared_keys() -> None:
    request = ExamSubmitRequest(answers=[{"item_order": 2, "answer_payload": {"decision": ""}}])
    with pytest.raises(AITeachMeError) as error:
        exams_api._resolve_exam_submission_values([_structured_item()], request)
    assert error.value.error_code == "QUESTION_ANSWER_FIELD_REQUIRED"


def test_public_generation_errors_hide_provider_details_without_rewriting_diagnostics() -> None:
    raw_error = "Knowledge-unit filtering failed: litellm.AuthenticationError: API key is disabled; Authorization: Bearer sk-review-fixture"
    context = {
        "generation_status": "failed",
        "filter_strategy": "llm_graph_failed",
        "filter_rationale": raw_error,
        "error_message": raw_error,
        "failed_questions": [{"item_order": 1, "error_message": raw_error}],
    }
    paper = ExamPaper(
        id=7, course_id="course-test", user_id="user-test", exam_mode="web_practice",
        status="failed", total_items=1, selection_context_json=json.dumps(context),
    )
    event = exams_api._paper_generation_event_payload(paper, error_message=raw_error)
    detail_context = exams_api._public_paper_selection_context(context, reveal_solutions=False)
    for payload in [event, detail_context]:
        rendered = json.dumps(payload, ensure_ascii=False, default=str)
        assert "API Key" in rendered
        assert "停用" in rendered
        assert "litellm" not in rendered
        assert "sk-review-fixture" not in rendered
        assert "Knowledge-unit filtering failed" not in rendered
    assert event["failed_question_count"] == 1
    assert context["error_message"] == raw_error
    assert json.loads(paper.selection_context_json) == context


@pytest.mark.parametrize("name", ["feynman_explanation", "experiment_design"])
@pytest.mark.anyio
async def test_import_accepted_rounded_weights_can_receive_full_marks(tmp_path, monkeypatch, name):
    from app.workflows.support.question_type_packages import build_atqskill_archive, validate_atqskill
    from app.workflows.examine.exam_grade.lib import grader

    source = Path(__file__).resolve().parents[2] / "examples" / "question-type-skills" / name
    folder = tmp_path / "source"
    shutil.copytree(source, folder)
    skill = folder / "SKILL.md"
    text = re.sub(r"(weight: )(\d+(?:\.\d+)?)(?=\s|$)",
                  lambda match: f"{match[1]}{float(match[2]) - 0.00025}", skill.read_text("utf-8"), count=1)
    skill.write_text(text, encoding="utf-8")
    result = validate_atqskill(build_atqskill_archive(folder, tmp_path / "rounded.atqskill"))
    assert result.valid, result.errors
    definition = result.compiled_definition
    assert definition is not None
    assert sum(row.weight for row in definition.rubric) == pytest.approx(0.99975)

    item = _structured_item()
    answer = {row.key: "The learner provides relevant evidence." for row in definition.answer_fields}
    item.score = 5
    item.answer_payload_json = json.dumps(answer)
    item.answer_schema_snapshot_json = json.dumps({"fields": [row.model_dump() for row in definition.answer_fields]})
    item.reference_answer_snapshot_json = json.dumps(answer)
    item.runtime_snapshot_json = json.dumps({"grader_key": definition.grader_key})
    item.grading_spec_snapshot_json = json.dumps({
        "pass_score": definition.pass_score,
        "rubric": [row.model_dump() for row in definition.rubric],
    })
    frozen_grading_spec = item.grading_spec_snapshot_json

    async def grade_stub(*_args, **_kwargs):
        return grader.CustomRubricGradePayload(
            criteria=[{"key": row.key, "score_ratio": 1, "evidence": [{
                "field_key": next(iter(answer)), "quote": "relevant evidence",
            }]} for row in definition.rubric],
            feedback_text="The answer satisfies every rubric criterion.",
        )

    monkeypatch.setattr(grader, "acompletion_with_fallback", grade_stub)
    decision = await grader._grade_custom_rubric_item("Course", item)
    assert decision.score_obtained == pytest.approx(5)
    assert decision.is_correct
    assert item.grading_spec_snapshot_json == frozen_grading_spec


@pytest.mark.anyio
async def test_package_feedback_guidance_reaches_the_same_grading_call(monkeypatch):
    from app.workflows.examine.exam_grade.lib import grader

    item = _structured_item()
    item.score = 4
    item.answer_payload_json = json.dumps({"decision": "Compare both groups.", "reason": "Control the variables."})
    item.runtime_snapshot_json = json.dumps({"grader_key": "rubric_llm_v1"})
    item.grading_spec_snapshot_json = json.dumps({
        "pass_score": 0.7,
        "rubric": [{"key": "accuracy", "label": "Accuracy", "weight": 1, "description": "Justified decisions"}],
        "grade_prompt": "Use ${rubric}; compare ${reference_examples}. Context: ${course_name} ${course_description} ${knowledge_units} ${difficulty} ${answer_schema}.",
        "feedback_prompt": "FEEDBACK_STYLE: give one strength and one next step using ${rubric}.",
    })
    calls = []

    async def grade_stub(messages, **_kwargs):
        calls.append(messages)
        payload = json.loads(messages[-1]["content"].split("\n\n", 1)[1])
        assert "FEEDBACK_STYLE" in payload["package_feedback_guidance"]
        assert "${rubric}" not in payload["package_feedback_guidance"]
        assert "${" not in payload["package_grading_guidance"]
        assert payload["difficulty"] == "medium"
        assert [row["key"] for row in payload["answer_schema"]["fields"]] == ["decision", "reason"]
        return grader.CustomRubricGradePayload(
            criteria=[{"key": "accuracy", "score_ratio": 0.5,
                       "evidence": [{"field_key": "decision", "quote": "Compare both groups."}]}],
            feedback_text="You compare groups; explain why the controls matter.",
        )

    monkeypatch.setattr(grader, "acompletion_with_fallback", grade_stub)
    decision = await grader._grade_custom_rubric_item("Course", item)
    assert len(calls) == 1
    assert decision.score_obtained == 2
    assert not decision.is_correct


@pytest.mark.anyio
async def test_invalid_evidence_retry_gets_validation_feedback(monkeypatch):
    from app.workflows.examine.exam_grade.lib import grader

    item = _structured_item()
    item.answer_payload_json = json.dumps({"decision": "Compare both groups.", "reason": "Control the variables."})
    item.runtime_snapshot_json = json.dumps({"grader_key": "rubric_llm_v1"})
    item.grading_spec_snapshot_json = json.dumps({"pass_score": 0.7, "rubric": [
        {"key": "accuracy", "label": "Accuracy", "weight": 1, "description": "Correct reasoning"},
    ]})
    calls = []

    async def grade_stub(messages, **_kwargs):
        calls.append([dict(message) for message in messages])
        if len(calls) == 2:
            assert len(messages) == len(calls[0]) + 1
            assert "accuracy" in messages[-1]["content"]
            assert "verbatim" in messages[-1]["content"]
        return grader.CustomRubricGradePayload(
            criteria=[{"key": "accuracy", "score_ratio": 1, "evidence": [{
                "field_key": "decision", "quote": "Compare the groups." if len(calls) == 1 else "Compare both groups.",
            }]}], feedback_text="Compare the groups using controlled measurements.",
        )

    monkeypatch.setattr(grader, "acompletion_with_fallback", grade_stub)
    decision = await grader._grade_custom_rubric_item("Course", item)
    assert len(calls) == 2
    assert decision.is_correct


@pytest.mark.anyio
async def test_single_question_workflow_failure_is_retryable_without_a_score(monkeypatch):
    from app.shared.infra.workflow.result import WorkflowError

    item = ExamPaperItem(exam_paper_id=1, question_template_id=1, item_order=1,
                         question_type="short_answer", difficulty="medium", stem_snapshot="Why?",
                         answer_snapshot="Reference", explanation_snapshot="Explanation")

    async def fail(**_kwargs):
        raise WorkflowError(code="workflow_failed", detail="Provider internal diagnostic sk-fixture")

    monkeypatch.setattr(exams_api, "run_exam_grade_workflow", fail)
    with pytest.raises(AITeachMeError) as failure:
        await exams_api._grade_exam_paper_item_answer(course_id="course-test", course_name="Course", item=item, answer="An answer.")
    assert failure.value.status_code == 502
    assert failure.value.error_code == "QUESTION_TEMPLATE_GRADE_FAILED"
    assert "重试" in failure.value.detail
    assert "sk-fixture" not in failure.value.detail
