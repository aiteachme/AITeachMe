import pytest

from app.models.knowledge_unit import KnowledgeUnit
from app.workflows.examine.question_build.lib import generator
from app.workflows.examine.question_build.lib.generator import (
    ExamQuestionBatch,
    ExamQuestionBlueprint,
    ExamQuestionBlueprintBatch,
    ExamQuestionDraft,
    ExamQuestionGenerationSpec,
    ExamSingleQuestionResponse,
    ExamQuestionWeightResult,
    assign_question_knowledge_weights,
    generate_exam_questions_for_units,
    plan_exam_question_blueprints,
)


@pytest.mark.anyio
async def test_generate_exam_questions_for_units_returns_validated_llm_questions(monkeypatch):
    observed_messages = []

    async def fake_acompletion_with_fallback(*args, **kwargs):
        assert kwargs["response_model"] is ExamQuestionBatch
        observed_messages.extend(args[0])
        return ExamQuestionBatch(
            questions=[
                ExamQuestionDraft(
                    item_order=1,
                    knowledge_unit_id=101,
                    question_type="single_choice",
                    difficulty="medium",
                    stem="Which option best describes the core meaning of a derivative?",
                    options=["Instantaneous rate of change", "Area accumulation", "Vector cross product", "Set union"],
                    correct_answer="A",
                    explanation="A derivative describes local instantaneous change, which is its core definition.",
                ),
                ExamQuestionDraft(
                    item_order=2,
                    knowledge_unit_id=102,
                    question_type="short_answer",
                    difficulty="hard",
                    stem="Explain why Newton iteration usually needs a reasonable initial value.",
                    correct_answer="A nearby initial value makes local linearization more likely to converge.",
                    explanation="Newton iteration depends on local tangent approximations, so distant starts may diverge.",
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
    assert questions[0].correct_answer == "A"
    assert questions[0].options is not None and len(questions[0].options) == 4
    assert questions[1].question_type == "short_answer"
    assert "Calculus context: derivatives before Newton iteration." in observed_messages[1]["content"]


@pytest.mark.anyio
async def test_generate_exam_questions_for_units_rejects_misaligned_llm_output(monkeypatch):
    async def fake_acompletion_with_fallback(*args, **kwargs):
        assert kwargs["response_model"] is ExamSingleQuestionResponse
        return ExamSingleQuestionResponse(
            question=ExamQuestionDraft(
                item_order=1,
                knowledge_unit_id=999,
                question_type="fill_blank",
                difficulty="easy",
                stem="In the definition of a limit, the process emphasizes {{blank}}.",
                correct_answer="approach behavior",
                explanation="This intentionally uses the wrong unit id so alignment validation fails.",
            )
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
async def test_generate_exam_questions_for_units_reports_failed_item_order(monkeypatch):
    async def fake_acompletion_with_fallback(*args, **kwargs):
        item_order = kwargs["extra_metadata"]["item_order"]
        if item_order == 2:
            raise RuntimeError("output truncated by max_tokens")
        return ExamSingleQuestionResponse(
            question=ExamQuestionDraft(
                item_order=item_order,
                knowledge_unit_id=301,
                question_type="short_answer",
                difficulty="medium",
                stem="Explain the core idea behind this related knowledge unit.",
                correct_answer="It connects the concept to a concrete reasoning step.",
                explanation="This valid response lets the test isolate the failing item order.",
            )
        )

    monkeypatch.setattr(generator, "acompletion_with_fallback", fake_acompletion_with_fallback)

    units = [
        KnowledgeUnit(
            id=301,
            subject="math",
            knowledge_unit_type="concept",
            canonical_name="Derivative",
            normalized_name="derivative",
            status="active",
        ),
    ]
    specs = [
        ExamQuestionGenerationSpec(
            item_order=1,
            knowledge_unit_id=301,
            question_type="short_answer",
            difficulty="medium",
        ),
        ExamQuestionGenerationSpec(
            item_order=2,
            knowledge_unit_id=301,
            question_type="short_answer",
            difficulty="medium",
        ),
    ]

    with pytest.raises(ValueError, match=r"item_order values=\[2\]"):
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
            "A derivative can describe an instantaneous rate of change.",
            "A derivative is always equal to the function value.",
            "A derivative can be represented by the slope of a tangent line.",
            "A derivative is the area under a curve.",
        ],
        correct_indices=[0, 2],
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
    assert multiple_choice.correct_indices == [0, 2]
    assert true_false.options is None
    assert true_false.correct_answer == "True"


def test_exam_question_draft_accepts_boolean_true_false_answer():
    draft = ExamQuestionDraft(
        item_order=1,
        knowledge_unit_id=301,
        question_type="true_false",
        difficulty="easy",
        stem="True or False: a zero derivative always means a global maximum.",
        correct_answer=False,
        explanation="A zero derivative identifies a critical point, not necessarily a global maximum.",
    )

    assert draft.correct_answer == "False"


def test_exam_question_draft_accepts_labeled_single_choice_answer():
    draft = ExamQuestionDraft(
        item_order=1,
        knowledge_unit_id=301,
        question_type="single_choice",
        difficulty="medium",
        stem="Which statement best describes the derivative at a point?",
        options=[
            "Local instantaneous rate of change",
            "Total accumulated area",
            "A set membership operation",
            "A vector cross product",
        ],
        correct_indices=[0],
        explanation="The label answer should normalize to the full option text.",
    )

    assert draft.correct_answer == "A"
    assert draft.correct_indices == [0]


def test_exam_question_draft_accepts_option_mapping():
    draft = ExamQuestionDraft(
        item_order=1,
        knowledge_unit_id=301,
        question_type="single_choice",
        difficulty="medium",
        stem="Which condition makes this optimization interpretation correct?",
        options={
            "A": "The derivative is zero at the candidate point.",
            "B": "The function must be constant everywhere.",
            "C": "The input variable has no domain restrictions.",
            "D": "The graph must be a straight line.",
        },
        correct_indices=[0],
        explanation="Dictionary options are normalized into labeled option strings.",
    )

    assert draft.options == [
        "The derivative is zero at the candidate point.",
        "The function must be constant everywhere.",
        "The input variable has no domain restrictions.",
        "The graph must be a straight line.",
    ]
    assert draft.correct_answer == "A"
    assert draft.correct_indices == [0]


def test_exam_question_draft_strips_option_labels_from_llm_output():
    draft = ExamQuestionDraft(
        item_order=1,
        knowledge_unit_id=301,
        question_type="single_choice",
        difficulty="medium",
        stem="Which condition makes this optimization interpretation correct?",
        options=[
            "A. The derivative is zero at the candidate point.",
            "B. The function must be constant everywhere.",
            "C. The input variable has no domain restrictions.",
            "D. The graph must be a straight line.",
        ],
        correct_answer="The derivative is zero at the candidate point.",
        explanation="Labeled options are accepted as fallback but normalized to plain text.",
    )

    assert draft.options == [
        "The derivative is zero at the candidate point.",
        "The function must be constant everywhere.",
        "The input variable has no domain restrictions.",
        "The graph must be a straight line.",
    ]
    assert draft.correct_answer == "A"


def test_exam_question_draft_rejects_invalid_multiple_choice_answer():
    with pytest.raises(ValueError, match="multiple_choice correct_indices"):
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


def test_exam_single_question_response_accepts_direct_question_payload():
    parsed = ExamSingleQuestionResponse.model_validate(
        {
            "item_order": 1,
            "knowledge_unit_id": 101,
            "question_type": "short_answer",
            "difficulty": "medium",
            "stem": "Explain why a derivative can describe local change.",
            "correct_answer": "It gives the instantaneous rate of change at a point.",
            "explanation": "The direct payload shape is accepted because some models omit the wrapper key.",
        }
    )

    assert parsed.question.item_order == 1
    assert parsed.question.knowledge_unit_id == 101
