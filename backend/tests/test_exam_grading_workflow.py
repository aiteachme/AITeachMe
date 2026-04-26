import pytest

from app.models import ExamPaperItem
from app.workflows.examine.exam_grade.lib import grader
from app.workflows.examine.exam_grade.lib.grader import (
    ObjectiveFeedbackPayload,
    SubjectiveGradePayload,
    grade_exam_items_with_workflow,
)
from app.workflows.examine.exam_grade.lib.study_guide import (
    ExamStudyGuidePayload,
    generate_exam_study_guide,
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
async def test_grade_exam_items_with_workflow_grades_multiple_choice_and_true_false(monkeypatch):
    async def fake_acompletion_with_fallback(messages, **kwargs):
        return ObjectiveFeedbackPayload(
            feedback_text="The objective answer was checked against the reference answer.",
            error_cause_label=None,
        )

    monkeypatch.setattr(grader, "acompletion_with_fallback", fake_acompletion_with_fallback)

    multiple_choice = ExamPaperItem(
        id=11,
        exam_paper_id=1,
        question_template_id=11,
        item_order=1,
        stem_snapshot="Which statements are correct?",
        options_snapshot_json='["A. Local rate", "B. Always positive", "C. Tangent slope", "D. Area"]',
        answer_snapshot="A,C",
        explanation_snapshot="A derivative describes local rate and tangent slope.",
        difficulty="medium",
        question_type="multiple_choice",
        score=1.0,
        answer_content="C,A",
    )
    true_false = ExamPaperItem(
        id=12,
        exam_paper_id=1,
        question_template_id=12,
        item_order=2,
        stem_snapshot="Differentiability implies continuity.",
        options_snapshot_json=None,
        answer_snapshot="True",
        explanation_snapshot="Differentiability is stronger than continuity.",
        difficulty="easy",
        question_type="true_false",
        score=1.0,
        answer_content="对",
    )

    decisions = await grade_exam_items_with_workflow(subject="math", items=[multiple_choice, true_false])

    assert [decision.is_correct for decision in decisions] == [True, True]
    assert [decision.grading_mode for decision in decisions] == ["objective_rule", "objective_rule"]


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


@pytest.mark.anyio
async def test_generate_exam_study_guide_returns_structured_sections(monkeypatch):
    async def fake_acompletion_with_fallback(messages, **kwargs):
        return ExamStudyGuidePayload(
            overall_summary="本次考卷主要暴露出函数综合应用与公式表达稳定性不足，需要优先围绕错题相关知识点回补。",
            strengths=["基础概念辨识整体稳定。", "作答覆盖率较高。"],
            priority_gaps=["函数综合应用", "公式表达规范", "错题对应知识点复盘"],
            action_steps=["先复盘错题。", "再按知识点回补。", "最后做针对性练习。"],
            review_tasks=["完成函数综合应用复习任务。", "整理本次错题本。"],
            focus_units=[
                {
                    "knowledge_unit_id": 11,
                    "knowledge_unit_name": "函数综合应用",
                    "mastery_score": 0.52,
                    "reason": "掌握度偏低，且本次错题集中出现。",
                }
            ],
        )

    monkeypatch.setattr("app.workflows.examine.exam_grade.lib.study_guide.acompletion_with_fallback", fake_acompletion_with_fallback)

    guide = await generate_exam_study_guide(
        exam_paper_id=9,
        subject="math",
        exam_title="专项练习 · 04/23 12:00",
        score_summary="得分 4/8，共 8 题，正确 4 题，错误或未作答 4 题。",
        wrong_question_summaries=[{"question_stem": "题目A", "user_answer": "A", "correct_answer": "B", "analysis": "误判条件"}],
        weak_points=[{"knowledge_unit_id": 11, "knowledge_unit_name": "函数综合应用", "mastery_score": 0.52, "reason": "掌握度偏低"}],
        pending_reviews=[{"knowledge_unit_name": "函数综合应用", "reason": "建议尽快回顾", "priority": 0.91}],
        generated_at=__import__("datetime").datetime.now(),
    )

    assert guide.exam_paper_id == 9
    assert guide.strengths
    assert guide.priority_gaps
    assert guide.action_steps
    assert guide.focus_units[0].knowledge_unit_name == "函数综合应用"
