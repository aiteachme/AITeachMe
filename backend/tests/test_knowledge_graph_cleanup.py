from sqlmodel import Session, SQLModel, create_engine, select

from app.models import ExamPaper, ExamPaperItem, KnowledgeEdge, KnowledgeUnit, QuestionKnowledgeUnitLink, QuestionTemplate, UserKnowledgeState
from app.workflows.digest.kg_doc_sync.lib.cleanup import clear_subject_graph_entities


def test_clear_subject_graph_entities_detaches_foreign_keys_before_delete():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        unit_a = KnowledgeUnit(
            subject="math",
            knowledge_unit_type="concept",
            canonical_name="Derivative",
            normalized_name="derivative",
            status="active",
        )
        session.add(unit_a)
        session.flush()

        unit_b = KnowledgeUnit(
            subject="math",
            knowledge_unit_type="concept",
            canonical_name="Slope",
            normalized_name="slope",
            status="active",
            merged_into_knowledge_unit_id=unit_a.id,
        )
        session.add(unit_b)
        session.flush()

        edge = KnowledgeEdge(
            subject="math",
            source_node_id=unit_b.id,
            target_node_id=unit_a.id,
            edge_type="derivation",
            status="active",
        )
        template = QuestionTemplate(
            subject="math",
            question_type="single_choice",
            difficulty="medium",
            stem="What is a derivative?",
            stem_hash="stem-1",
            answer="rate of change",
            explanation="Derivative measures rate of change.",
        )
        paper = ExamPaper(subject="math", exam_mode="practice")
        state = UserKnowledgeState(subject="math", knowledge_unit_id=unit_a.id)
        session.add(edge)
        session.add(template)
        session.add(paper)
        session.add(state)
        session.flush()

        item = ExamPaperItem(
            exam_paper_id=paper.id,
            question_template_id=template.id,
            item_order=1,
            stem_snapshot="What is a derivative?",
            answer_snapshot="rate of change",
            explanation_snapshot="Derivative measures rate of change.",
            difficulty="medium",
            question_type="single_choice",
        )
        session.add(item)
        session.flush()
        session.add(
            QuestionKnowledgeUnitLink(
                question_template_id=template.id,
                knowledge_unit_id=unit_a.id,
                coverage_weight=1.0,
                role="primary",
            )
        )
        session.add(
            QuestionKnowledgeUnitLink(
                exam_paper_item_id=item.id,
                knowledge_unit_id=unit_a.id,
                coverage_weight=1.0,
                role="primary",
            )
        )
        session.commit()

        counts = clear_subject_graph_entities(session, subject="math")

        remaining_units = list(session.exec(select(KnowledgeUnit)).all())
        remaining_edges = list(session.exec(select(KnowledgeEdge)).all())
        stored_template = session.get(QuestionTemplate, template.id)
        stored_item = session.get(ExamPaperItem, item.id)
        stored_state = session.get(UserKnowledgeState, state.id)
        remaining_links = list(session.exec(select(QuestionKnowledgeUnitLink)).all())

    assert counts["knowledge_unit"] == 2
    assert counts["knowledge_edge"] == 1
    assert counts["detached_question_template"] == 1
    assert counts["detached_exam_paper_item"] == 1
    assert counts["detached_user_knowledge_state"] == 1
    assert counts["detached_unit_merge_ref"] == 1
    assert remaining_units == []
    assert remaining_edges == []
    assert stored_template is not None
    assert stored_item is not None
    assert remaining_links == []
    assert stored_state is not None and stored_state.knowledge_unit_id is None
