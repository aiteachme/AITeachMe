import pytest

from app.models import ExamPaperItem
from app.workflows.examine.exam_grade.lib import grader
from app.workflows.examine.exam_grade.lib.grader import (
    ObjectiveFeedbackPayload,
    SubjectiveGradePayload,
    grade_exam_items_with_workflow,
)


@pytest.mark.anyio
async def test_grade_exam_items_with_workflow_uses_rule_based_grading_for_objective_questions(monkeypatch):
    captured_messages: list[dict[str, object]] = []

    async def fake_acompletion_with_fallback(messages, **kwargs):
        captured_messages.append({"messages": messages, "kwargs": kwargs})
        return ObjectiveFeedbackPayload(
            feedback_text="你选错了关键选项，应该关注题干中的限定条件。",
            error_cause_label="careless_mistake",
        )

    monkeypatch.setattr(grader, "acompletion_with_fallback", fake_acompletion_with_fallback)

    item = ExamPaperItem(
        id=1,
        exam_paper_id=1,
        question_template_id=1,
        item_order=1,
        stem_snapshot="下列哪一项最符合导数的定义？",
        options_snapshot_json='["平均变化率","瞬时变化率","面积和","极限值"]',
        answer_snapshot="瞬时变化率",
        explanation_snapshot="导数描述函数在某点附近的瞬时变化率。",
        difficulty="medium",
        question_type="single_choice",
        score=1.0,
        answer_content="平均变化率",
    )

    [decision] = await grade_exam_items_with_workflow(subject="math", items=[item])

    assert decision.is_correct is False
    assert decision.score_obtained == 0.0
    assert decision.grading_mode == "objective_rule"
    assert decision.error_cause_label == "careless_mistake"
    assert captured_messages, "objective questions should still call the LLM for personalized feedback"


@pytest.mark.anyio
async def test_grade_exam_items_with_workflow_uses_llm_for_subjective_questions(monkeypatch):
    async def fake_acompletion_with_fallback(messages, **kwargs):
        return SubjectiveGradePayload(
            is_correct=True,
            score_obtained=0.9,
            feedback_text="虽然公式书写与标准答案不同，但核心推导与最终结论一致，可判为正确。",
            error_cause_label=None,
        )

    monkeypatch.setattr(grader, "acompletion_with_fallback", fake_acompletion_with_fallback)

    item = ExamPaperItem(
        id=2,
        exam_paper_id=1,
        question_template_id=2,
        item_order=2,
        stem_snapshot="请说明二项式定理展开式的通项公式。",
        options_snapshot_json=None,
        answer_snapshot="第k+1项为 C(n,k)a^(n-k)b^k。",
        explanation_snapshot="关键是识别组合数与指数变化规律。",
        difficulty="hard",
        question_type="short_answer",
        score=1.0,
        answer_content="通项可以写成组合数乘以 a 的 n-k 次方再乘 b 的 k 次方。",
    )

    [decision] = await grade_exam_items_with_workflow(subject="math", items=[item])

    assert decision.is_correct is True
    assert decision.score_obtained == pytest.approx(0.9)
    assert decision.grading_mode == "subjective_llm"
    assert "核心推导" in decision.feedback_text
