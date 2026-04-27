import json

from sqlmodel import SQLModel, Session, create_engine

from app.api.exams import (
    _build_paper_preview,
    _effective_exam_paper_status,
    _exam_knowledge_graph_edges,
    _generated_question_item_responses,
    _paper_generation_event_payload,
    _paper_preview_for_response,
    _question_type_for_order,
    _require_generated_questions_by_order,
)
from app.models import ExamPaper, ExamPaperItem
from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.workflow.result import err_result, ok_result


def test_require_generated_questions_by_order_accepts_declared_partial_results():
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
            "failed_questions": [
                {
                    "item_order": 1,
                    "question_type": "short_answer",
                    "difficulty": "medium",
                    "error_message": "LLM output did not validate.",
                }
            ],
            "error": "",
        }
    )

    generated_by_order = _require_generated_questions_by_order(build_result=build_result, expected_orders=[1, 2])

    assert sorted(generated_by_order) == [2]


def test_require_generated_questions_by_order_accepts_unrecorded_missing_results():
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
            "failed_questions": [],
            "error": "",
        }
    )

    generated_by_order = _require_generated_questions_by_order(build_result=build_result, expected_orders=[1, 2])

    assert sorted(generated_by_order) == [2]


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


def test_exam_knowledge_graph_edges_include_relation_payload_and_filter_by_units():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            [
                KnowledgeUnit(
                    id=101,
                    subject="math",
                    knowledge_unit_type="concept",
                    canonical_name="Limit",
                    normalized_name="limit",
                    status="active",
                ),
                KnowledgeUnit(
                    id=102,
                    subject="math",
                    knowledge_unit_type="concept",
                    canonical_name="Derivative",
                    normalized_name="derivative",
                    status="active",
                ),
                KnowledgeUnit(
                    id=103,
                    subject="math",
                    knowledge_unit_type="concept",
                    canonical_name="Integral",
                    normalized_name="integral",
                    status="active",
                ),
            ]
        )
        session.add_all(
            [
                KnowledgeEdge(
                    subject="math",
                    source_node_id=101,
                    target_node_id=102,
                    edge_type="prerequisite",
                    description="markdown_anchor_sync: Limit supports derivative definition.",
                    weight=0.8,
                    confidence=0.97,
                    status="active",
                ),
                KnowledgeEdge(
                    subject="math",
                    source_node_id=102,
                    target_node_id=103,
                    edge_type="application",
                    description="Derivative leads to integral intuition.",
                    status="active",
                ),
            ]
        )
        session.commit()

        edges = _exam_knowledge_graph_edges(session, subject="math", unit_ids=[101, 102])

    assert edges == [
        {
            "edge_id": 1,
            "source_id": 101,
            "target_id": 102,
            "edge_type": "prerequisite",
            "description": "Limit supports derivative definition.",
            "weight": 0.8,
            "confidence": 0.97,
        }
    ]


def _preview_item(
    order: int,
    *,
    question_type: str,
    difficulty: str = "medium",
    stem: str = "Question stem",
    unit_id: int = 1,
    is_correct: bool | None = None,
) -> ExamPaperItem:
    return ExamPaperItem(
        id=order,
        exam_paper_id=1,
        question_template_id=order,
        item_order=order,
        stem_snapshot=stem,
        options_snapshot_json=json.dumps(["A", "B", "C", "D"]) if question_type == "single_choice" else None,
        answer_snapshot="A",
        explanation_snapshot="Explanation",
        difficulty=difficulty,
        question_type=question_type,
        is_correct=is_correct,
    )


def test_build_paper_preview_dedupes_keywords_limits_rows_and_counts_overflow():
    items = [
        _preview_item(1, question_type="single_choice", difficulty="easy", unit_id=1),
        _preview_item(2, question_type="fill_blank", difficulty="medium", unit_id=1),
        _preview_item(3, question_type="short_answer", difficulty="hard", unit_id=2),
        _preview_item(4, question_type="single_choice", unit_id=2),
        _preview_item(5, question_type="fill_blank", unit_id=3),
        _preview_item(6, question_type="short_answer", unit_id=3),
        _preview_item(7, question_type="single_choice", unit_id=1),
        _preview_item(8, question_type="fill_blank", unit_id=2),
    ]
    units = {
        1: KnowledgeUnit(id=1, subject="math", knowledge_unit_type="concept", canonical_name="Derivative", normalized_name="derivative"),
        2: KnowledgeUnit(id=2, subject="math", knowledge_unit_type="concept", canonical_name="Limit", normalized_name="limit"),
        3: KnowledgeUnit(id=3, subject="math", knowledge_unit_type="concept", canonical_name="Integral", normalized_name="integral"),
    }

    links_by_item_id = {
        1: [{"knowledge_unit_id": 1, "coverage_weight": 1.0, "role": "primary"}],
        2: [{"knowledge_unit_id": 1, "coverage_weight": 1.0, "role": "primary"}],
        3: [{"knowledge_unit_id": 2, "coverage_weight": 1.0, "role": "primary"}],
        4: [{"knowledge_unit_id": 2, "coverage_weight": 1.0, "role": "primary"}],
        5: [{"knowledge_unit_id": 3, "coverage_weight": 1.0, "role": "primary"}],
        6: [{"knowledge_unit_id": 3, "coverage_weight": 1.0, "role": "primary"}],
        7: [{"knowledge_unit_id": 1, "coverage_weight": 1.0, "role": "primary"}],
        8: [{"knowledge_unit_id": 2, "coverage_weight": 1.0, "role": "primary"}],
    }

    preview = _build_paper_preview(items, knowledge_unit_by_id=units, links_by_item_id=links_by_item_id)

    assert preview.keywords == ["Derivative", "Limit", "Integral"]
    assert [row.shape for row in preview.rows] == ["choice", "blank", "short", "choice", "blank", "short", "choice"]
    assert [row.density for row in preview.rows[:3]] == [1, 2, 3]
    assert [row.result_status for row in preview.rows[:3]] == ["ungraded", "ungraded", "ungraded"]
    assert preview.overflow_count == 1


def test_paper_preview_for_response_falls_back_for_legacy_empty_json():
    paper = ExamPaper(subject="math", user_id="local", exam_mode="web_practice", paper_preview_json="{}")
    item = _preview_item(1, question_type="fill_blank", unit_id=1)
    units = {
        1: KnowledgeUnit(id=1, subject="math", knowledge_unit_type="concept", canonical_name="Derivative", normalized_name="derivative"),
    }

    preview = _paper_preview_for_response(
        paper,
        [item],
        knowledge_unit_by_id=units,
        links_by_item_id={1: [{"knowledge_unit_id": 1, "coverage_weight": 1.0, "role": "primary"}]},
    )

    assert preview.keywords == ["Derivative"]
    assert preview.rows[0].shape == "blank"


def test_paper_preview_for_response_regenerates_legacy_five_row_preview():
    old_preview = {
        "keywords": ["Derivative"],
        "question_types": ["single_choice", "fill_blank", "short_answer"],
        "rows": [
            {"order": order, "type": "single_choice", "shape": "choice", "difficulty": "medium", "density": 2}
            for order in range(1, 6)
        ],
        "overflow_count": 3,
    }
    paper = ExamPaper(
        subject="math",
        user_id="local",
        exam_mode="web_practice",
        paper_preview_json=json.dumps(old_preview),
    )
    items = [
        _preview_item(order, question_type="single_choice" if order % 2 else "fill_blank", unit_id=1)
        for order in range(1, 9)
    ]
    units = {
        1: KnowledgeUnit(id=1, subject="math", knowledge_unit_type="concept", canonical_name="Derivative", normalized_name="derivative"),
    }

    preview = _paper_preview_for_response(
        paper,
        items,
        knowledge_unit_by_id=units,
        links_by_item_id={int(item.id or 0): [{"knowledge_unit_id": 1, "coverage_weight": 1.0, "role": "primary"}] for item in items},
    )

    assert [row.order for row in preview.rows] == [1, 2, 3, 4, 5, 6, 7]
    assert preview.overflow_count == 1


def test_paper_preview_for_response_regenerates_with_graded_result_status():
    old_preview = {
        "keywords": ["Derivative"],
        "question_types": ["single_choice"],
        "rows": [
            {"order": 1, "type": "single_choice", "shape": "choice", "difficulty": "medium", "density": 2},
            {"order": 2, "type": "single_choice", "shape": "choice", "difficulty": "medium", "density": 2},
        ],
        "overflow_count": 0,
    }
    paper = ExamPaper(
        subject="math",
        user_id="local",
        exam_mode="web_practice",
        paper_preview_json=json.dumps(old_preview),
    )
    items = [
        _preview_item(1, question_type="single_choice", unit_id=1, is_correct=True),
        _preview_item(2, question_type="single_choice", unit_id=1, is_correct=False),
    ]
    units = {
        1: KnowledgeUnit(id=1, subject="math", knowledge_unit_type="concept", canonical_name="Derivative", normalized_name="derivative"),
    }

    preview = _paper_preview_for_response(
        paper,
        items,
        knowledge_unit_by_id=units,
        links_by_item_id={int(item.id or 0): [{"knowledge_unit_id": 1, "coverage_weight": 1.0, "role": "primary"}] for item in items},
    )

    assert [row.result_status for row in preview.rows] == ["correct", "incorrect"]


def test_generated_question_item_responses_restore_streamed_drafts():
    context = {
        "generated_questions": [
            {
                "item_order": 2,
                "question_type": "short_answer",
                "difficulty": "medium",
                "stem": "Explain why the derivative describes local change.",
                "correct_answer": "It measures instantaneous rate of change.",
                "explanation": "The derivative captures local change through tangent slope.",
                "knowledge_unit_refs": [
                    {"knowledge_unit_id": 101, "coverage_weight": 0.7, "role": "primary"},
                    {"knowledge_unit_id": 102, "coverage_weight": 0.3, "role": "secondary"},
                ],
            }
        ]
    }
    units = {
        101: KnowledgeUnit(id=101, subject="math", knowledge_unit_type="concept", canonical_name="Derivative", normalized_name="derivative"),
        102: KnowledgeUnit(id=102, subject="math", knowledge_unit_type="method", canonical_name="Tangent Line", normalized_name="tangent-line"),
    }

    responses = _generated_question_item_responses(
        context,
        knowledge_unit_by_id=units,
        mastery_by_unit_id={101: 0.42},
    )

    assert len(responses) == 1
    assert responses[0].id < 0
    assert responses[0].item_order == 2
    assert responses[0].question_template_id == 0
    assert responses[0].knowledge_unit_links[0].knowledge_unit_name == "Derivative"
    assert responses[0].knowledge_unit_links[0].mastery_score == 0.42


def test_effective_exam_status_uses_failed_generation_context_as_fallback():
    paper = ExamPaper(
        id=7,
        subject="math",
        user_id="local",
        exam_mode="web_practice",
        status="generating",
        selection_context_json=json.dumps(
            {
                "generation_status": "failed",
                "error_message": "LLM timeout",
            }
        ),
    )

    assert _effective_exam_paper_status(paper) == "failed"

    payload = _paper_generation_event_payload(paper)

    assert payload["status"] == "failed"
    assert payload["error_message"] == "LLM timeout"
