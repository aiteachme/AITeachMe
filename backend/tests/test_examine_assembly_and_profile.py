from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

import app.models as _models

if not all(
    hasattr(_models, name)
    for name in ("Curriculum", "TeachingUnit", "ThemeTreeNode")
):
    pytest.skip(
        "Legacy Examine curriculum/tree models are not present while exams API is offline.",
        allow_module_level=True,
    )

from app.models import (
    Curriculum,
    Difficulty,
    ExamPaper,
    ExamPaperItem,
    KnowledgeNode,
    QuestionTemplate,
    TeachingUnit,
    ThemeTreeNode,
)
from app.repositories import profile_repo
from app.workflows.examine.context import TemplateSelectionHints
from app.workflows.examine.answer_grader import grade_paper
from app.workflows.examine.paper_assembler import assemble_paper
from app.workflows.profile.runtime import generate_report_suggestions
from app.workflows.profile.mastery_updater import update_mastery_from_exam


def _create_curriculum_graph(session):
    curriculum = Curriculum(subject="math", version_no=1, status="published", is_current=True)
    unit_1 = TeachingUnit(
        subject="math",
        canonical_name="函数单元",
        normalized_name="函数单元",
        member_signature="assembly-unit-1",
        status="active",
    )
    unit_2 = TeachingUnit(
        subject="math",
        canonical_name="导数单元",
        normalized_name="导数单元",
        member_signature="assembly-unit-2",
        status="active",
    )
    session.add_all([curriculum, unit_1, unit_2])
    session.commit()

    theme_root = ThemeTreeNode(
        subject="math",
        tree_version_id=curriculum.id,
        title="root",
        node_type="theme",
        unit_refs_json=json.dumps(
            [
                {"teaching_unit_id": unit_1.id},
                {"teaching_unit_id": unit_2.id},
            ],
            ensure_ascii=False,
        ),
    )
    session.add(theme_root)
    session.commit()
    return curriculum, unit_1, unit_2


def _matching_hints(signature: str) -> str:
    return json.dumps(
        TemplateSelectionHints(
            context_signature=signature,
            context_locked=True,
            scope_locked=True,
        ).model_dump(exclude_none=True),
        ensure_ascii=False,
    )


def _generic_hints() -> str:
    return json.dumps(TemplateSelectionHints().model_dump(exclude_none=True), ensure_ascii=False)


def test_assemble_paper_scope_locked_does_not_fallback_outside_scope(session) -> None:
    curriculum, unit_1, unit_2 = _create_curriculum_graph(session)
    signature = "scope-signature"

    session.add_all(
        [
            QuestionTemplate(
                subject="math",
                teaching_unit_id=unit_1.id,
                question_type="single_choice",
                difficulty=Difficulty.MEDIUM.value,
                stem="unit-1-question",
                stem_hash="unit-1-question",
                answer="A",
                explanation="exp",
                selection_hints_json=_matching_hints(signature),
                curriculum_version_id=curriculum.id,
                status="active",
            ),
            QuestionTemplate(
                subject="math",
                teaching_unit_id=unit_2.id,
                question_type="single_choice",
                difficulty=Difficulty.MEDIUM.value,
                stem="unit-2-question",
                stem_hash="unit-2-question",
                answer="A",
                explanation="exp",
                selection_hints_json=_matching_hints(signature),
                curriculum_version_id=curriculum.id,
                status="active",
            ),
        ]
    )
    session.commit()

    with pytest.raises(ValueError, match="指定范围内可用题目不足"):
        assemble_paper(
            session,
            subject="math",
            user_id="local",
            exam_mode="web_practice",
            num_questions=2,
            curriculum_version_id=curriculum.id,
            teaching_unit_ids=[unit_1.id],
            preferred_question_types=["single_choice"],
            preferred_difficulty=Difficulty.MEDIUM.value,
            template_context_signature=signature,
            context_locked=True,
            scope_locked=True,
        )


def test_assemble_paper_records_selection_context_fields(session) -> None:
    curriculum, unit_1, _unit_2 = _create_curriculum_graph(session)
    signature = "scope-context"
    session.add_all(
        [
            QuestionTemplate(
                subject="math",
                teaching_unit_id=unit_1.id,
                question_type="single_choice",
                difficulty=Difficulty.MEDIUM.value,
                stem="scope-question-1",
                stem_hash="scope-question-1",
                answer="A",
                explanation="exp",
                selection_hints_json=_matching_hints(signature),
                curriculum_version_id=curriculum.id,
                status="active",
            ),
            QuestionTemplate(
                subject="math",
                teaching_unit_id=unit_1.id,
                question_type="single_choice",
                difficulty=Difficulty.MEDIUM.value,
                stem="scope-question-2",
                stem_hash="scope-question-2",
                answer="A",
                explanation="exp",
                selection_hints_json=_matching_hints(signature),
                curriculum_version_id=curriculum.id,
                status="active",
            ),
        ]
    )
    session.commit()

    paper = assemble_paper(
        session,
        subject="math",
        user_id="local",
        exam_mode="web_practice",
        num_questions=2,
        curriculum_version_id=curriculum.id,
        teaching_unit_ids=[unit_1.id],
        preferred_question_types=["single_choice"],
        preferred_difficulty=Difficulty.MEDIUM.value,
        template_context_signature=signature,
        context_locked=True,
        scope_locked=True,
    )

    selection_context = json.loads(paper.selection_context_json)
    assert selection_context["scope_locked"] is True
    assert selection_context["template_context_signature"] == signature
    assert selection_context["template_reuse_policy"] == "exact_context_signature"
    assert selection_context["resolved_teaching_unit_ids"] == [unit_1.id]


def test_update_mastery_from_exam_only_updates_linked_nodes(session) -> None:
    curriculum = Curriculum(subject="math", version_no=1, status="published", is_current=True)
    unit = TeachingUnit(
        subject="math",
        canonical_name="函数单元",
        normalized_name="函数单元",
        member_signature="profile-unit",
        status="active",
    )
    node_1 = KnowledgeNode(
        subject="math",
        node_type="concept",
        canonical_name="函数",
        normalized_name="函数",
        status="active",
    )
    node_2 = KnowledgeNode(
        subject="math",
        node_type="concept",
        canonical_name="导数",
        normalized_name="导数",
        status="active",
    )
    session.add_all([curriculum, unit, node_1, node_2])
    session.commit()

    paper = ExamPaper(
        subject="math",
        user_id="local",
        exam_mode="web_practice",
        curriculum_version_id=curriculum.id,
        status="graded",
    )
    session.add(paper)
    session.commit()

    item = ExamPaperItem(
        exam_paper_id=paper.id,
        question_template_id=1,
        item_order=1,
        stem_snapshot="函数题",
        answer_snapshot="A",
        explanation_snapshot="exp",
        teaching_unit_id=unit.id,
        node_refs_json=json.dumps(
            [{"knowledge_node_id": node_1.id, "coverage_weight": 1.0, "role": "primary"}],
            ensure_ascii=False,
        ),
        difficulty=Difficulty.MEDIUM.value,
        question_type="single_choice",
        is_correct=True,
    )
    session.add(item)
    session.commit()

    result = update_mastery_from_exam(session, paper.id)

    unit_state = profile_repo.get_knowledge_state(
        session,
        user_id="local",
        subject="math",
        teaching_unit_id=unit.id,
    )
    node_1_state = profile_repo.get_knowledge_state(
        session,
        user_id="local",
        subject="math",
        knowledge_node_id=node_1.id,
    )
    node_2_state = profile_repo.get_knowledge_state(
        session,
        user_id="local",
        subject="math",
        knowledge_node_id=node_2.id,
    )

    assert result.states_updated == 2
    assert unit_state is not None
    assert node_1_state is not None
    assert node_2_state is None


def test_grade_paper_raises_when_short_answer_llm_grading_fails(session) -> None:
    curriculum = Curriculum(subject="math", version_no=1, status="published", is_current=True)
    unit = TeachingUnit(
        subject="math",
        canonical_name="short-answer-unit",
        normalized_name="short-answer-unit",
        member_signature="short-answer-unit",
        status="active",
    )
    paper = ExamPaper(
        subject="math",
        user_id="local",
        exam_mode="web_practice",
        curriculum_version_id=1,
        status="draft",
    )
    session.add_all([curriculum, unit, paper])
    session.commit()

    item = ExamPaperItem(
        exam_paper_id=paper.id,
        question_template_id=1,
        item_order=1,
        stem_snapshot="Explain the derivative concept.",
        answer_snapshot="A derivative is a rate of change.",
        explanation_snapshot="exp",
        teaching_unit_id=unit.id,
        node_refs_json=json.dumps([], ensure_ascii=False),
        difficulty=Difficulty.MEDIUM.value,
        question_type="short_answer",
        answer_content="It is something else.",
        is_correct=None,
    )
    session.add(item)
    session.commit()

    with patch(
        "app.workflows.examine.answer_grader.read_knowledge_doc_text",
        return_value="",
    ), patch(
        "app.workflows.examine.answer_grader._build_knowledge_context",
        return_value="knowledge context",
    ), patch(
        "app.workflows.examine.answer_grader._grade_short_answer_with_llm",
        new=AsyncMock(side_effect=RuntimeError("grading llm failed")),
    ):
        with pytest.raises(RuntimeError, match="short_answer_grading_failed"):
            asyncio.run(grade_paper(session, paper.id, auto_commit=False))


def test_generate_report_suggestions_raises_when_llm_fails() -> None:
    with patch(
        "app.workflows.profile.runtime.acompletion",
        new=AsyncMock(side_effect=RuntimeError("profile llm failed")),
    ):
        with pytest.raises(RuntimeError, match="profile llm failed"):
            asyncio.run(
                generate_report_suggestions(
                    subject="math",
                    overall_mastery=0.42,
                    weak_points=[
                        {
                            "knowledge_point": "derivatives",
                            "mastery_text": "42%",
                        }
                    ],
                )
            )
