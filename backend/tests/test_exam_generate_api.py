from app.api.exams import _question_type_for_order, _require_generated_questions_by_order
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
