import pytest

from app.models.knowledge_unit import KnowledgeUnit
from app.workflows.examine.question_build.lib import generator
from app.workflows.examine.question_build.lib.generator import (
    ExamQuestionBatch,
    ExamQuestionDraft,
    ExamQuestionGenerationSpec,
    generate_exam_questions_for_units,
)


@pytest.mark.anyio
async def test_generate_exam_questions_for_units_returns_validated_llm_questions(monkeypatch):
    async def fake_acompletion_with_fallback(*args, **kwargs):
        return ExamQuestionBatch(
            questions=[
                ExamQuestionDraft(
                    item_order=1,
                    knowledge_unit_id=101,
                    question_type="single_choice",
                    difficulty="medium",
                    stem="下列哪一项最能说明导数的核心含义？",
                    options=["瞬时变化率", "面积和", "向量叉积", "集合并集"],
                    correct_answer="瞬时变化率",
                    explanation="导数描述函数在某一点附近的瞬时变化率，这是最核心的定义。",
                ),
                ExamQuestionDraft(
                    item_order=2,
                    knowledge_unit_id=102,
                    question_type="short_answer",
                    difficulty="hard",
                    stem="说明牛顿迭代法为何通常需要一个较好的初始值，并指出其局限。",
                    correct_answer="初始值若足够接近真实根，局部线性化才更可能收敛；离得过远时可能震荡、发散或收敛到别的根。",
                    explanation="题目考查对牛顿迭代法收敛条件与局限的理解，而不是只会套公式。",
                ),
            ]
        )

    monkeypatch.setattr(generator, "acompletion_with_fallback", fake_acompletion_with_fallback)

    units = [
        KnowledgeUnit(
            id=101,
            subject="math",
            knowledge_unit_type="concept",
            canonical_name="导数",
            summary="函数在某一点的瞬时变化率。",
            normalized_name="daoshu",
            status="active",
        ),
        KnowledgeUnit(
            id=102,
            subject="math",
            knowledge_unit_type="method",
            canonical_name="牛顿迭代法",
            summary="利用切线近似逐步逼近方程根的数值方法。",
            normalized_name="niudun-diedaifa",
            status="active",
        ),
    ]
    specs = [
        ExamQuestionGenerationSpec(
            item_order=1,
            knowledge_unit_id=101,
            question_type="single_choice",
            difficulty="medium",
        ),
        ExamQuestionGenerationSpec(
            item_order=2,
            knowledge_unit_id=102,
            question_type="short_answer",
            difficulty="hard",
        ),
    ]

    questions = await generate_exam_questions_for_units(
        subject="math",
        exam_mode="paper_exam",
        units=units,
        specs=specs,
        focus_prompt="导数与数值方法",
        user_prompt="更重视理解与应用",
        style_prompt="风格接近高质量阶段测验",
    )

    assert [item.item_order for item in questions] == [1, 2]
    assert questions[0].correct_answer == "瞬时变化率"
    assert questions[0].options is not None and len(questions[0].options) == 4
    assert questions[1].question_type == "short_answer"


@pytest.mark.anyio
async def test_generate_exam_questions_for_units_rejects_misaligned_llm_output(monkeypatch):
    async def fake_acompletion_with_fallback(*args, **kwargs):
        return ExamQuestionBatch(
            questions=[
                ExamQuestionDraft(
                    item_order=1,
                    knowledge_unit_id=999,
                    question_type="fill_blank",
                    difficulty="easy",
                    stem="极限的定义中，趋近过程强调的是 ____ 。",
                    correct_answer="变量的逼近关系",
                    explanation="这是一个用于触发校验失败的错误样例。",
                )
            ]
        )

    monkeypatch.setattr(generator, "acompletion_with_fallback", fake_acompletion_with_fallback)

    units = [
        KnowledgeUnit(
            id=201,
            subject="math",
            knowledge_unit_type="concept",
            canonical_name="极限",
            summary="描述变量无限逼近某个值时函数行为的概念。",
            normalized_name="jixian",
            status="active",
        ),
    ]
    specs = [
        ExamQuestionGenerationSpec(
            item_order=1,
            knowledge_unit_id=201,
            question_type="fill_blank",
            difficulty="easy",
        ),
    ]

    with pytest.raises(ValueError, match="knowledge_unit_id"):
        await generate_exam_questions_for_units(
            subject="math",
            exam_mode="web_practice",
            units=units,
            specs=specs,
        )
