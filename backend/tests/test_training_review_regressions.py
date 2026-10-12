"""Provider error redaction remains after custom question types are retired."""

import json
from app.api import exams as exams_api
from app.models import ExamPaper


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
