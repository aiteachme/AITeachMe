from __future__ import annotations

import json

from sqlmodel import Session

from app.api.exams import _grade_exam
from app.models import ExamPaper, ExamPaperItem, QuestionTemplate
from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.profile import UserKnowledgeState
from app.repositories import exams_repo, profile_repo
from app.repositories.knowledge import knowledge_relation_repo, knowledge_unit_repo
from app.workflows.digest.application.knowledge_docs.study_plan_service import build_study_plan


def _unit(session: Session, *, subject: str, name: str, summary: str = "") -> KnowledgeUnit:
    unit = knowledge_unit_repo.create_knowledge_unit(
        session,
        KnowledgeUnit(
            subject=subject,
            node_type="concept",
            canonical_name=name,
            normalized_name=name.casefold().replace(" ", "_"),
            summary=summary or name,
            status="active",
        ),
    )
    assert unit.id is not None
    return unit


def test_p4_exam_grading_updates_knowledge_unit_mastery_and_reviews(session: Session) -> None:
    subject = "math"
    unit = _unit(session, subject=subject, name="Linear Function", summary="constant rate of change")
    template = exams_repo.create_question_template(
        session,
        QuestionTemplate(
            subject=subject,
            knowledge_node_id=unit.id,
            question_type="short_answer",
            difficulty="medium",
            stem="Explain Linear Function.",
            stem_hash="linear-function",
            answer="constant rate of change",
            explanation="A linear function has a constant rate of change.",
            node_refs_json=json.dumps(
                [{"knowledge_node_id": unit.id, "coverage_weight": 1.0, "role": "primary"}],
                ensure_ascii=False,
            ),
        ),
    )
    paper = exams_repo.create_exam_paper(
        session,
        ExamPaper(
            subject=subject,
            user_id="local",
            exam_mode="web_practice",
            status="submitted",
            total_items=1,
        ),
    )
    exams_repo.create_exam_paper_items(
        session,
        [
            ExamPaperItem(
                exam_paper_id=paper.id or 0,
                question_template_id=template.id or 0,
                item_order=1,
                stem_snapshot=template.stem,
                answer_snapshot=template.answer,
                explanation_snapshot=template.explanation,
                knowledge_node_id=unit.id,
                node_refs_json=template.node_refs_json,
                difficulty=template.difficulty,
                question_type=template.question_type,
                answer_content="wrong answer",
            )
        ],
    )

    result = _grade_exam(session, paper)

    assert result.mastery_consumed
    assert result.states_updated == 1
    state = profile_repo.get_knowledge_state(
        session,
        user_id="local",
        subject=subject,
        knowledge_node_id=unit.id,
    )
    assert state is not None
    assert state.mastery_score == 0.0
    assert state.review_status == "pending"
    assert state.source_exam_paper_id == paper.id


def test_p4_study_plan_uses_prerequisite_graph_and_mastery(session: Session) -> None:
    subject = "math"
    prerequisite = _unit(session, subject=subject, name="Function", summary="mapping")
    target = _unit(session, subject=subject, name="Linear Function", summary="constant rate")
    knowledge_relation_repo.create_knowledge_edge(
        session,
        KnowledgeEdge(
            subject=subject,
            source_node_id=prerequisite.id or 0,
            target_node_id=target.id or 0,
            edge_type="prerequisite",
            status="active",
        ),
    )
    profile_repo.upsert_knowledge_state(
        session,
        state=UserKnowledgeState(
            user_id="local",
            subject=subject,
            knowledge_node_id=target.id,
            mastery_score=0.4,
            confidence_score=0.2,
            stability_score=0.1,
            total_attempts=2,
            correct_attempts=0,
        ),
    )

    plan = build_study_plan(session, subject=subject, user_id="local")

    items = plan.phases[0].items
    by_title = {item.title: item for item in items}
    assert by_title["Linear Function"].depends_on_ids == [by_title["Function"].id]
    assert "40%" in by_title["Linear Function"].summary
