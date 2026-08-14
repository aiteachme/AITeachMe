from __future__ import annotations

import pytest

from app.api import exams as exams_api
from app.models import ExamPaperItem, QuestionTemplate
from app.shared.infra.exceptions import AITeachMeError, InvalidImportPackageError
from app.shared.kernel.question_types import (
    CANONICAL_QUESTION_TYPE_KEYS,
    UnsupportedQuestionTypeError,
    normalize_question_type_key,
    question_type_grading_kind,
    require_supported_question_type_key,
)
from app.workflows.examine.exam_grade.lib import grader
from app.workflows.examine.question_build.lib.generator import ExamQuestionDraft
from app.workflows.support.export_import.imports import _validate_imported_question_types
from migrations.seed_data.question_types import BUILTIN_QUESTION_TYPE_ROWS
from pydantic import ValidationError


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


def test_question_generation_schema_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError):
        ExamQuestionDraft.model_validate(
            {
                "item_order": 1,
                "question_type": "dialogue",
                "difficulty": "medium",
                "stem": "Discuss the concept.",
                "correct_answer": "Reference answer",
                "explanation": "Reference explanation",
                "knowledge_unit_refs": [{"knowledge_unit_id": 1, "coverage_weight": 1.0}],
            }
        )


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
