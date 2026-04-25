import pytest

from app.models.knowledge_unit import KnowledgeUnit
from app.workflows.examine.question_build.lib import generator
from app.workflows.examine.question_build.lib.generator import (
    ExamQuestionBatch,
    ExamQuestionBlueprint,
    ExamQuestionBlueprintBatch,
    ExamQuestionDraft,
    ExamQuestionGenerationSpec,
    ExamQuestionWeightResult,
    assign_question_knowledge_weights,
    generate_exam_questions_for_units,
    plan_exam_question_blueprints,
)


@pytest.mark.anyio
async def test_generate_exam_questions_for_units_returns_validated_llm_questions(monkeypatch):
    observed_messages = []

    async def fake_acompletion_with_fallback(*args, **kwargs):
        observed_messages.extend(args[0])
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
        subject_context="Calculus context: derivatives before Newton iteration.",
        focus_prompt="导数与数值方法",
        user_prompt="更重视理解与应用",
        style_prompt="风格接近高质量阶段测验",
    )

    assert [item.item_order for item in questions] == [1, 2]
    assert questions[0].correct_answer == "瞬时变化率"
    assert questions[0].options is not None and len(questions[0].options) == 4
    assert questions[1].question_type == "short_answer"
    assert "Calculus context: derivatives before Newton iteration." in observed_messages[1]["content"]


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


@pytest.mark.anyio
async def test_plan_exam_question_blueprints_can_select_multiple_related_units(monkeypatch):
    async def fake_acompletion_with_fallback(*args, **kwargs):
        assert kwargs["response_model"] is ExamQuestionBlueprintBatch
        return ExamQuestionBlueprintBatch(
            blueprints=[
                ExamQuestionBlueprint(
                    item_order=1,
                    knowledge_unit_ids=[101, 102],
                    question_type="short_answer",
                    difficulty="medium",
                    rationale="Derivative and Newton iteration can form one application question.",
                )
            ]
        )

    monkeypatch.setattr(generator, "acompletion_with_fallback", fake_acompletion_with_fallback)

    units = [
        KnowledgeUnit(id=101, subject="math", knowledge_unit_type="concept", canonical_name="Derivative", normalized_name="derivative"),
        KnowledgeUnit(id=102, subject="math", knowledge_unit_type="method", canonical_name="Newton Method", normalized_name="newton"),
    ]

    blueprints = await plan_exam_question_blueprints(
        subject="subj_math",
        subject_name="Calculus",
        subject_description="Differential calculus practice.",
        subject_user_intent="Prepare for finals.",
        exam_mode="paper_exam",
        units=units,
        question_count=1,
        requested_difficulty="medium",
        mastery_by_unit_id={101: 0.3, 102: 0.6},
    )

    assert blueprints[0].knowledge_unit_ids == [101, 102]
    assert blueprints[0].question_type == "short_answer"


@pytest.mark.anyio
async def test_assign_question_knowledge_weights_normalizes_refs(monkeypatch):
    async def fake_acompletion_with_fallback(*args, **kwargs):
        assert kwargs["response_model"] is ExamQuestionWeightResult
        return ExamQuestionWeightResult(
            item_order=1,
            knowledge_unit_refs=[
                {"knowledge_unit_id": 101, "coverage_weight": 0.7, "role": "primary"},
                {"knowledge_unit_id": 102, "coverage_weight": 0.7, "role": "secondary"},
                {"knowledge_unit_id": 999, "coverage_weight": 1.0, "role": "secondary"},
            ],
        )

    monkeypatch.setattr(generator, "acompletion_with_fallback", fake_acompletion_with_fallback)

    weighted = await assign_question_knowledge_weights(
        subject="subj_math",
        units=[
            KnowledgeUnit(id=101, subject="math", knowledge_unit_type="concept", canonical_name="Derivative", normalized_name="derivative"),
            KnowledgeUnit(id=102, subject="math", knowledge_unit_type="method", canonical_name="Newton Method", normalized_name="newton"),
        ],
        blueprints=[
            ExamQuestionBlueprint(
                item_order=1,
                knowledge_unit_ids=[101, 102],
                question_type="short_answer",
                difficulty="medium",
            )
        ],
        questions=[
            ExamQuestionDraft(
                item_order=1,
                knowledge_unit_id=101,
                question_type="short_answer",
                difficulty="medium",
                stem="Explain how derivatives guide Newton iteration updates.",
                correct_answer="Use tangent-line linearization to approximate the next root estimate.",
                explanation="The method uses derivative information to build a local linear approximation.",
            )
        ],
    )

    refs = weighted[0].knowledge_unit_refs
    assert [ref.knowledge_unit_id for ref in refs] == [101, 102]
    assert refs[0].role == "primary"
    assert round(sum(ref.coverage_weight for ref in refs), 4) == 1.0


def test_exam_question_draft_accepts_multiple_choice_and_true_false_shapes():
    multiple_choice = ExamQuestionDraft(
        item_order=1,
        knowledge_unit_id=301,
        question_type="multiple_choice",
        difficulty="medium",
        stem="Which two statements correctly describe derivatives in this context?",
        options=[
            "A. A derivative can describe an instantaneous rate of change.",
            "B. A derivative is always equal to the function value.",
            "C. A derivative can be represented by the slope of a tangent line.",
            "D. A derivative is the area under a curve.",
        ],
        correct_answer="A,C",
        explanation="The derivative captures instantaneous change and tangent slope; function value and area are different concepts.",
    )
    true_false = ExamQuestionDraft(
        item_order=2,
        knowledge_unit_id=301,
        question_type="true_false",
        difficulty="easy",
        stem="True or False: differentiability at a point implies continuity at that point.",
        correct_answer="True",
        explanation="Differentiability is stronger than continuity, so the statement is true.",
    )

    assert multiple_choice.options is not None and len(multiple_choice.options) == 4
    assert multiple_choice.correct_answer == "A,C"
    assert true_false.options is None
    assert true_false.correct_answer == "True"


def test_exam_question_draft_rejects_invalid_multiple_choice_answer():
    with pytest.raises(ValueError, match="multiple_choice correct_answer"):
        ExamQuestionDraft(
            item_order=1,
            knowledge_unit_id=301,
            question_type="multiple_choice",
            difficulty="medium",
            stem="Which statements about derivatives are correct?",
            options=[
                "A. Derivatives measure local change.",
                "B. Derivatives are always positive.",
                "C. Derivatives can be zero.",
                "D. Derivatives equal area.",
            ],
            correct_answer="A,E",
            explanation="This should fail because E is not one of the available option labels.",
        )


def test_exam_question_draft_escapes_text_underscore_placeholders():
    draft = ExamQuestionDraft(
        item_order=1,
        knowledge_unit_id=401,
        question_type="fill_blank",
        difficulty="easy",
        stem=r"从6个球中抽取2个，编号和为7的概率为 $\frac{\text{___}}{\text{___}}$。",
        correct_answer=r"$\frac{\text{___}}{\text{___}}$",
        explanation=r"分子和分母的空位应写成 $\text{___}$。",
    )

    assert r"\text{\_\_\_}" in draft.stem
    assert r"\text{___}" not in draft.stem
    assert r"\text{\_\_\_}" in draft.correct_answer
    assert r"\text{\_\_\_}" in draft.explanation


def test_exam_question_draft_rejects_blank_token_inside_latex():
    with pytest.raises(ValueError, match=r"\{\{blank\}\} placeholders must stay outside LaTeX"):
        ExamQuestionDraft(
            item_order=1,
            knowledge_unit_id=402,
            question_type="fill_blank",
            difficulty="easy",
            stem=r"该概率可以写作 ${{blank}}$。",
            correct_answer=r"$\frac{1}{3}$",
            explanation="填空占位符只能放在正文里，不能放进 LaTeX 公式。",
        )


def test_exam_question_draft_accepts_blank_token_in_body_text():
    draft = ExamQuestionDraft(
        item_order=1,
        knowledge_unit_id=403,
        question_type="fill_blank",
        difficulty="easy",
        stem=r"该概率可以写作 {{blank}}。",
        correct_answer=r"$\frac{1}{3}$",
        explanation="正文里的占位符会由前端渲染成填空线。",
    )

    assert "{{blank}}" in draft.stem
