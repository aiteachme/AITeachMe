from __future__ import annotations

import asyncio
import json

import pytest
from sqlmodel import select

import app.models as _models

if not all(
    hasattr(_models, name)
    for name in ("Curriculum", "TeachingUnit", "ThemeTreeNode")
):
    pytest.skip(
        "Legacy Examine curriculum/tree models are not present while exams API is offline.",
        allow_module_level=True,
    )

from app.models import Curriculum, Difficulty, KnowledgeUnit, QuestionTemplate, TeachingUnit
from app.workflows.examine.application._helpers import _resolve_requested_unit_scope
from app.utils.time import utcnow
from app.workflows.examine.context import (
    ExamStyleProfile,
    NodeExamContext,
    TemplateSelectionHints,
    UnitExamContext,
    build_unit_exam_contexts,
)
from app.workflows.examine.question_builder import (
    _build_knowledge_unit_refs_json,
    _load_existing_template_counts,
    build_question_templates,
)
from app.workflows.examine.question_build_workflow import QuestionBuildWorkflow


def _make_unit_context(*, node_contexts: list[NodeExamContext]) -> UnitExamContext:
    return UnitExamContext(
        subject="math",
        unit_id=11,
        unit_name="Functions",
        unit_summary="summary",
        unit_body="body",
        learning_objectives=["obj"],
        doc_excerpt="excerpt",
        node_contexts=node_contexts,
        unit_mastery_score=0.4,
        recent_mistakes=[],
        weak_node_names=[],
        style_profile=ExamStyleProfile(),
        exam_mode="web_practice",
        preferred_question_types=["single_choice"],
        requested_question_count=3,
    )


def test_build_knowledge_unit_refs_json_falls_back_to_unit_node_and_limits_to_three() -> None:
    context = _make_unit_context(
        node_contexts=[
            NodeExamContext(1, "鍑芥暟", "s1", "b1", "primary", 1.0),
            NodeExamContext(2, "瀵兼暟", "s2", "b2", "secondary", 0.8),
            NodeExamContext(3, "鏋侀檺", "s3", "b3", "secondary", 0.6),
            NodeExamContext(4, "绉垎", "s4", "b4", "secondary", 0.4),
        ]
    )

    payload = json.loads(
        _build_knowledge_unit_refs_json(
            context,
            preferred_node_id=999,
            fallback_node_id=1,
            stem="璇疯鏄庡嚱鏁颁笌瀵兼暟銆佹瀬闄愪箣闂寸殑鍏崇郴銆?,
            answer="瀵兼暟鍜屾瀬闄愰兘渚濊禆鍑芥暟瀹氫箟銆?,
            explanation="杩欓噷娌℃湁鎻愬埌绉垎銆?,
        )
    )

    assert [item["knowledge_unit_id"] for item in payload] == [1, 2, 3]
    assert payload[0]["role"] == "primary"
    assert payload[1]["role"] == "related"
    assert payload[2]["role"] == "related"
    assert round(sum(float(item["coverage_weight"]) for item in payload), 4) == 1.0


def test_build_knowledge_unit_refs_json_single_node_keeps_full_weight() -> None:
    context = _make_unit_context(
        node_contexts=[NodeExamContext(7, "鐭╅樀", "s", "b", "primary", 1.0)]
    )

    payload = json.loads(
        _build_knowledge_unit_refs_json(
            context,
            preferred_node_id=7,
            fallback_node_id=7,
            stem="鐭╅樀鐨勫畾涔夋槸浠€涔堬紵",
            answer="鐭╅樀鏄寜琛屽垪鎺掑垪鐨勬暟琛ㄣ€?,
            explanation="鍙€冧竴涓煡璇嗙偣銆?,
        )
    )

    assert payload == [
        {
            "knowledge_unit_id": 7,
            "coverage_weight": 1.0,
            "role": "primary",
        }
    ]


def test_build_unit_exam_contexts_uses_revision_content_and_scoped_mistakes(
    session,
    monkeypatch,
) -> None:
    node_1 = KnowledgeUnit(
        subject="math",
        knowledge_unit_type="concept",
        canonical_name="鍑芥暟",
        normalized_name="鍑芥暟",
        summary="old summary",
        body="old body",
        body_markdown="old body",
        status="active",
    )
    node_2 = KnowledgeUnit(
        subject="math",
        knowledge_unit_type="concept",
        canonical_name="瀵兼暟",
        normalized_name="瀵兼暟",
        summary="derivative summary",
        body="derivative body",
        body_markdown="derivative body",
        status="active",
    )
    node_3 = KnowledgeUnit(
        subject="math",
        knowledge_unit_type="concept",
        canonical_name="绉垎",
        normalized_name="绉垎",
        summary="integral summary",
        body="integral body",
        body_markdown="integral body",
        status="active",
    )
    session.add_all([node_1, node_2, node_3])
    session.commit()

    unit_1 = TeachingUnit(
        subject="math",
        canonical_name="鍑芥暟鍗曞厓",
        normalized_name="鍑芥暟鍗曞厓",
        member_signature="unit-1",
        summary="unit summary",
        body_markdown="unit body",
        member_knowledge_unit_refs_json=json.dumps(
            [
                {"knowledge_unit_id": node_1.id, "role": "primary", "score": 1.0},
                {"knowledge_unit_id": node_2.id, "role": "secondary", "score": 0.8},
            ],
            ensure_ascii=False,
        ),
        learning_objectives_json=json.dumps(["鐞嗚В鍑芥暟"], ensure_ascii=False),
        status="active",
    )
    unit_2 = TeachingUnit(
        subject="math",
        canonical_name="绉垎鍗曞厓",
        normalized_name="绉垎鍗曞厓",
        member_signature="unit-2",
        summary="unit2 summary",
        body_markdown="unit2 body",
        member_knowledge_unit_refs_json=json.dumps(
            [{"knowledge_unit_id": node_3.id, "role": "primary", "score": 1.0}],
            ensure_ascii=False,
        ),
        status="active",
    )
    session.add_all([unit_1, unit_2])
    session.commit()

    from app.models import Curriculum, ExamPaper, ExamPaperItem
    from app.repositories.knowledge import knowledge_unit_repo

    curriculum = Curriculum(subject="math", version_no=1, status="published", is_current=True)
    session.add(curriculum)
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

    session.add_all(
        [
            ExamPaperItem(
                exam_paper_id=paper.id,
                question_template_id=1,
                item_order=1,
                stem_snapshot="鍑芥暟閿欓",
                answer_snapshot="A",
                explanation_snapshot="鍑芥暟瑙ｉ噴",
                teaching_unit_id=unit_1.id,
                knowledge_unit_refs_json=json.dumps(
                    [{"knowledge_unit_id": node_1.id, "coverage_weight": 1.0, "role": "primary"}],
                    ensure_ascii=False,
                ),
                difficulty=Difficulty.MEDIUM.value,
                question_type="single_choice",
                is_correct=False,
            ),
            ExamPaperItem(
                exam_paper_id=paper.id,
                question_template_id=2,
                item_order=2,
                stem_snapshot="鍚屽崟鍏冧絾閿欒妭鐐?,
                answer_snapshot="B",
                explanation_snapshot="鏃犲叧鑺傜偣",
                teaching_unit_id=unit_1.id,
                knowledge_unit_refs_json=json.dumps(
                    [{"knowledge_unit_id": node_3.id, "coverage_weight": 1.0, "role": "primary"}],
                    ensure_ascii=False,
                ),
                difficulty=Difficulty.MEDIUM.value,
                question_type="single_choice",
                is_correct=False,
            ),
            ExamPaperItem(
                exam_paper_id=paper.id,
                question_template_id=3,
                item_order=3,
                stem_snapshot="鍒殑鍗曞厓閿欓",
                answer_snapshot="C",
                explanation_snapshot="绉垎瑙ｉ噴",
                teaching_unit_id=unit_2.id,
                knowledge_unit_refs_json=json.dumps(
                    [{"knowledge_unit_id": node_3.id, "coverage_weight": 1.0, "role": "primary"}],
                    ensure_ascii=False,
                ),
                difficulty=Difficulty.MEDIUM.value,
                question_type="single_choice",
                is_correct=False,
            ),
        ]
    )
    session.commit()

    original_get_revision = knowledge_unit_repo.get_knowledge_unit_with_current_revision

    def _fake_get_revision(db_session, node_id: int):
        if node_id == node_1.id:
            node = db_session.get(KnowledgeUnit, node_id)
            assert node is not None
            from app.models.knowledge_unit import KnowledgeRevision

            return node, KnowledgeRevision(
                id=1,
                knowledge_unit_id=node_id,
                revision_no=2,
                title=node.canonical_name,
                summary="revision summary",
                body="revision body",
                revision_reason="test",
            )
        return original_get_revision(db_session, node_id)

    monkeypatch.setattr(knowledge_unit_repo, "get_knowledge_unit_with_current_revision", _fake_get_revision)

    contexts = build_unit_exam_contexts(
        session,
        subject="math",
        user_id="local",
        unit_ids=[unit_1.id],
        questions_per_unit=2,
        exam_mode="web_practice",
    )

    assert len(contexts) == 1
    assert contexts[0].node_contexts[0].summary == "revision summary"
    assert contexts[0].node_contexts[0].body == "revision body"
    assert [item["question_stem"] for item in contexts[0].recent_mistakes] == [
        "鍑芥暟閿欓",
        "鍚屽崟鍏冧絾閿欒妭鐐?,
    ]


def test_existing_template_counts_respect_curriculum_and_context_signature(session) -> None:
    curriculum_current = Curriculum(subject="math", version_no=1, status="published", is_current=True)
    curriculum_old = Curriculum(subject="math", version_no=2, status="archived", is_current=False)
    unit = TeachingUnit(
        subject="math",
        canonical_name="鍑芥暟鍗曞厓",
        normalized_name="鍑芥暟鍗曞厓",
        member_signature="unit-counts",
        status="active",
    )
    session.add_all([curriculum_current, curriculum_old, unit])
    session.commit()

    generic_hints = TemplateSelectionHints().model_dump(exclude_none=True)
    matched_hints = TemplateSelectionHints(
        context_signature="sig-1",
        context_locked=True,
        scope_locked=True,
    ).model_dump(exclude_none=True)
    mismatched_hints = TemplateSelectionHints(
        context_signature="sig-2",
        context_locked=True,
        scope_locked=True,
    ).model_dump(exclude_none=True)

    session.add_all(
        [
            QuestionTemplate(
                subject="math",
                teaching_unit_id=unit.id,
                question_type="single_choice",
                difficulty=Difficulty.MEDIUM.value,
                stem="generic",
                stem_hash="generic",
                answer="A",
                explanation="exp",
                selection_hints_json=json.dumps(generic_hints, ensure_ascii=False),
                curriculum_version_id=curriculum_current.id,
                status="active",
            ),
            QuestionTemplate(
                subject="math",
                teaching_unit_id=unit.id,
                question_type="single_choice",
                difficulty=Difficulty.MEDIUM.value,
                stem="matched",
                stem_hash="matched",
                answer="A",
                explanation="exp",
                selection_hints_json=json.dumps(matched_hints, ensure_ascii=False),
                curriculum_version_id=curriculum_current.id,
                status="active",
            ),
            QuestionTemplate(
                subject="math",
                teaching_unit_id=unit.id,
                question_type="single_choice",
                difficulty=Difficulty.MEDIUM.value,
                stem="mismatched",
                stem_hash="mismatched",
                answer="A",
                explanation="exp",
                selection_hints_json=json.dumps(mismatched_hints, ensure_ascii=False),
                curriculum_version_id=curriculum_current.id,
                status="active",
            ),
            QuestionTemplate(
                subject="math",
                teaching_unit_id=unit.id,
                question_type="single_choice",
                difficulty=Difficulty.MEDIUM.value,
                stem="old-curriculum",
                stem_hash="old-curriculum",
                answer="A",
                explanation="exp",
                selection_hints_json=json.dumps(generic_hints, ensure_ascii=False),
                curriculum_version_id=curriculum_old.id,
                status="active",
            ),
        ]
    )
    session.commit()

    contextual_counts = _load_existing_template_counts(
        session,
        subject="math",
        unit_ids=[unit.id],
        preferred_question_types=["single_choice"],
        difficulty_focus=Difficulty.MEDIUM.value,
        curriculum_version_id=curriculum_current.id,
        context_signature="sig-1",
        context_locked=True,
    )
    generic_counts = _load_existing_template_counts(
        session,
        subject="math",
        unit_ids=[unit.id],
        preferred_question_types=["single_choice"],
        difficulty_focus=Difficulty.MEDIUM.value,
        curriculum_version_id=curriculum_current.id,
        context_signature="ignored",
        context_locked=False,
    )

    assert contextual_counts[unit.id] == 1
    assert generic_counts[unit.id] == 1


def test_resolve_requested_unit_scope_filters_cross_subject_units(session) -> None:
    math_unit = TeachingUnit(
        subject="math",
        canonical_name="鍑芥暟鍗曞厓",
        normalized_name="鍑芥暟鍗曞厓",
        member_signature="math-scope-unit",
        status="active",
    )
    physics_unit = TeachingUnit(
        subject="physics",
        canonical_name="鍔涘鍗曞厓",
        normalized_name="鍔涘鍗曞厓",
        member_signature="physics-scope-unit",
        status="active",
    )
    session.add_all([math_unit, physics_unit])
    session.commit()

    resolved = _resolve_requested_unit_scope(
        session,
        subject="math",
        teaching_unit_ids=[math_unit.id, physics_unit.id],
        theme_tree_node_id=None,
    )

    assert resolved == [math_unit.id]


def test_resolve_requested_unit_scope_keeps_explicit_invalid_units_empty(session) -> None:
    math_unit = TeachingUnit(
        subject="math",
        canonical_name="鍑芥暟鍗曞厓",
        normalized_name="鍑芥暟鍗曞厓",
        member_signature="math-explicit-unit",
        status="active",
    )
    physics_unit = TeachingUnit(
        subject="physics",
        canonical_name="鍔涘鍗曞厓",
        normalized_name="鍔涘鍗曞厓",
        member_signature="physics-explicit-unit",
        status="active",
    )
    curriculum = Curriculum(subject="math", version_no=1, status="published", is_current=True)
    session.add_all([math_unit, physics_unit, curriculum])
    session.commit()

    from app.models import ThemeTreeNode

    theme_node = ThemeTreeNode(
        subject="math",
        tree_version_id=curriculum.id,
        title="鍑芥暟涓婚",
        knowledge_unit_type="theme",
        unit_refs_json=json.dumps([{"teaching_unit_id": math_unit.id}], ensure_ascii=False),
    )
    session.add(theme_node)
    session.commit()

    resolved = _resolve_requested_unit_scope(
        session,
        subject="math",
        teaching_unit_ids=[physics_unit.id],
        theme_tree_node_id=theme_node.id,
    )

    assert resolved == []


def test_question_build_workflow_passes_context_fields_to_builder(session, monkeypatch) -> None:
    node = KnowledgeUnit(
        subject="math",
        knowledge_unit_type="concept",
        canonical_name="鍑芥暟",
        normalized_name="鍑芥暟",
        summary="summary",
        body="body",
        body_markdown="body",
        status="active",
    )
    unit = TeachingUnit(
        subject="math",
        canonical_name="鍑芥暟鍗曞厓",
        normalized_name="鍑芥暟鍗曞厓",
        member_signature="workflow-unit",
        member_knowledge_unit_refs_json=json.dumps(
            [{"knowledge_unit_id": 1, "role": "primary", "score": 1.0}],
            ensure_ascii=False,
        ),
        status="active",
    )
    session.add_all([node, unit])
    session.commit()
    unit.member_knowledge_unit_refs_json = json.dumps(
        [{"knowledge_unit_id": node.id, "role": "primary", "score": 1.0}],
        ensure_ascii=False,
    )
    session.add(unit)
    session.commit()

    captured: dict[str, object] = {}

    async def _fake_build_question_templates(*args, **kwargs):
        del args
        captured.update(kwargs)
        return []

    monkeypatch.setattr(
        "app.workflows.examine.question_build_workflow.build_question_templates",
        _fake_build_question_templates,
    )

    result = asyncio.run(
        QuestionBuildWorkflow.run(
            subject="math",
            user_id="local",
            unit_ids=[unit.id],
            questions_per_unit=2,
            job_id=123,
            exam_mode="web_practice",
            preferred_question_types=["single_choice"],
            curriculum_version_id=99,
            template_context_signature="ctx-signature",
            context_locked=True,
            scope_locked=True,
            focus_teaching_unit_ids=[unit.id],
            focus_node_ids=[node.id],
            session=session,
        )
    )

    assert result["error"] is None
    assert captured["curriculum_version_id"] == 99
    assert captured["template_context_signature"] == "ctx-signature"
    assert captured["context_locked"] is True
    assert captured["scope_locked"] is True
    assert captured["focus_teaching_unit_ids"] == [unit.id]
    assert captured["focus_node_ids"] == [node.id]


def test_build_question_templates_raises_and_does_not_persist_when_any_unit_generation_fails(
    session,
    monkeypatch,
) -> None:
    context_1 = _make_unit_context(
        node_contexts=[NodeExamContext(1, "Functions", "summary", "body", "primary", 1.0)]
    )
    context_2 = UnitExamContext(
        subject="math",
        unit_id=12,
        unit_name="Limits",
        unit_summary="summary",
        unit_body="body",
        learning_objectives=["obj"],
        doc_excerpt="excerpt",
        node_contexts=[NodeExamContext(2, "Limits", "summary", "body", "primary", 1.0)],
        unit_mastery_score=0.4,
        recent_mistakes=[],
        weak_node_names=[],
        style_profile=ExamStyleProfile(),
        exam_mode="web_practice",
        preferred_question_types=["single_choice"],
        requested_question_count=3,
    )

    monkeypatch.setattr(
        "app.workflows.examine.question_builder.build_unit_exam_contexts",
        lambda *args, **kwargs: [context_1, context_2],
    )
    monkeypatch.setattr(
        "app.workflows.examine.question_builder._load_existing_template_counts",
        lambda *args, **kwargs: {context_1.unit_id: 0, context_2.unit_id: 0},
    )
    monkeypatch.setattr(
        "app.workflows.examine.question_builder._load_existing_hashes",
        lambda *args, **kwargs: {},
    )

    async def fake_try_llm_generate_templates(context, **kwargs):
        del kwargs
        if context.unit_id == context_2.unit_id:
            raise RuntimeError("unit llm failed")
        return []

    monkeypatch.setattr(
        "app.workflows.examine.question_builder._try_llm_generate_templates",
        fake_try_llm_generate_templates,
    )

    with pytest.raises(RuntimeError, match="question_builder_generation_failed"):
        asyncio.run(
            build_question_templates(
                session,
                subject="math",
                user_id="local",
                unit_ids=[context_1.unit_id, context_2.unit_id],
                questions_per_unit=3,
                exam_mode="web_practice",
                curriculum_version_id=1,
            )
        )

    assert list(session.exec(select(QuestionTemplate)).all()) == []
