import json

from app.api.exams import _build_paper_preview, _paper_preview_for_response, _question_type_for_order, _require_generated_questions_by_order
from app.models import ExamPaper, ExamPaperItem
from app.models.knowledge_unit import KnowledgeUnit
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.workflow.result import err_result, ok_result


def test_require_generated_questions_by_order_raises_when_workflow_returns_partial_results():
    build_result = ok_result(
        {
            "generated_questions": [
                {
                    "item_order": 2,
                    "knowledge_unit_id": 102,
                    "question_type": "short_answer",
                    "difficulty": "medium",
                    "stem": "Explain why the derivative describes local change.",
                    "correct_answer": "It measures instantaneous rate of change.",
                    "explanation": "This is enough structure for the API helper test.",
                }
            ],
            "error": "",
        }
    )

    try:
        _require_generated_questions_by_order(build_result=build_result, expected_orders=[1, 2])
        raise AssertionError("Expected AITeachMeError to be raised for missing item_order.")
    except AITeachMeError as exc:
        assert exc.error_code == "EXAM_QUESTION_BUILD_INCOMPLETE"
        assert exc.status_code == 502
        assert "missing item_order values: [1]" in exc.detail


def test_require_generated_questions_by_order_raises_when_workflow_fails():
    build_result = err_result("workflow_execution_failed", "LLM timeout")

    try:
        _require_generated_questions_by_order(build_result=build_result, expected_orders=[1])
        raise AssertionError("Expected AITeachMeError to be raised for workflow failure.")
    except AITeachMeError as exc:
        assert exc.error_code == "EXAM_QUESTION_BUILD_FAILED"
        assert exc.status_code == 502
        assert exc.detail == "LLM timeout"


def test_question_type_for_order_only_returns_single_choice_and_fill_blank():
    generated = {
        _question_type_for_order(exam_mode="paper_exam", difficulty="medium", item_order=order)
        for order in range(1, 9)
    } | {
        _question_type_for_order(exam_mode="web_practice", difficulty=difficulty, item_order=order)
        for difficulty in ["easy", "medium", "hard"]
        for order in range(1, 9)
    }

    assert generated == {"single_choice", "fill_blank"}


def _preview_item(
    order: int,
    *,
    question_type: str,
    difficulty: str = "medium",
    stem: str = "Question stem",
    unit_id: int = 1,
) -> ExamPaperItem:
    return ExamPaperItem(
        exam_paper_id=1,
        question_template_id=order,
        item_order=order,
        stem_snapshot=stem,
        options_snapshot_json=json.dumps(["A", "B", "C", "D"]) if question_type == "single_choice" else None,
        answer_snapshot="A",
        explanation_snapshot="Explanation",
        knowledge_unit_id=unit_id,
        knowledge_unit_refs_json=json.dumps([{"knowledge_unit_id": unit_id, "coverage_weight": 1.0, "role": "primary"}]),
        difficulty=difficulty,
        question_type=question_type,
    )


def test_build_paper_preview_dedupes_keywords_limits_rows_and_counts_overflow():
    items = [
        _preview_item(1, question_type="single_choice", difficulty="easy", unit_id=1),
        _preview_item(2, question_type="fill_blank", difficulty="medium", unit_id=1),
        _preview_item(3, question_type="short_answer", difficulty="hard", unit_id=2),
        _preview_item(4, question_type="single_choice", unit_id=2),
        _preview_item(5, question_type="fill_blank", unit_id=3),
        _preview_item(6, question_type="short_answer", unit_id=3),
    ]
    units = {
        1: KnowledgeUnit(id=1, subject="math", knowledge_unit_type="concept", canonical_name="Derivative", normalized_name="derivative"),
        2: KnowledgeUnit(id=2, subject="math", knowledge_unit_type="concept", canonical_name="Limit", normalized_name="limit"),
        3: KnowledgeUnit(id=3, subject="math", knowledge_unit_type="concept", canonical_name="Integral", normalized_name="integral"),
    }

    preview = _build_paper_preview(items, knowledge_unit_by_id=units)

    assert preview.keywords == ["Derivative", "Limit", "Integral"]
    assert [row.shape for row in preview.rows] == ["choice", "blank", "short", "choice", "blank"]
    assert [row.density for row in preview.rows[:3]] == [1, 2, 3]
    assert preview.overflow_count == 1


def test_build_paper_preview_uses_content_rules_for_dominant_type():
    units = {
        1: KnowledgeUnit(id=1, subject="cs", knowledge_unit_type="concept", canonical_name="Python", normalized_name="python"),
    }
    code_preview = _build_paper_preview(
        [_preview_item(1, question_type="short_answer", stem="Read this Python function: def score(x): return x + 1")],
        knowledge_unit_by_id=units,
    )
    chart_preview = _build_paper_preview(
        [_preview_item(1, question_type="short_answer", stem="Analyze the trend in this chart and axis labels")],
        knowledge_unit_by_id=units,
    )
    formula_preview = _build_paper_preview(
        [_preview_item(1, question_type="short_answer", stem="Use the formula f(x)=x^2 to calculate the derivative")],
        knowledge_unit_by_id=units,
    )

    assert code_preview.dominant_type == "code"
    assert chart_preview.dominant_type == "chart"
    assert formula_preview.dominant_type == "formula"


def test_paper_preview_for_response_falls_back_for_legacy_empty_json():
    paper = ExamPaper(subject="math", user_id="local", exam_mode="web_practice", paper_preview_json="{}")
    item = _preview_item(1, question_type="fill_blank", unit_id=1)
    units = {
        1: KnowledgeUnit(id=1, subject="math", knowledge_unit_type="concept", canonical_name="Derivative", normalized_name="derivative"),
    }

    preview = _paper_preview_for_response(paper, [item], knowledge_unit_by_id=units)

    assert preview.keywords == ["Derivative"]
    assert preview.rows[0].shape == "blank"
