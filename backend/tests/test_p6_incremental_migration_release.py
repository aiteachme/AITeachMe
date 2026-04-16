from __future__ import annotations

import asyncio

from sqlmodel import Session, select

from app.api.exams import _pick_knowledge_units
from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.subject import Subject
from app.repositories.knowledge import knowledge_relation_repo, knowledge_unit_repo
from app.workflows.digest.application.knowledge_graph.incremental_sync import sync_markdown_knowledge_graph
from app.workflows.digest.application.knowledge_graph.migration import normalize_knowledge_graph
from app.workflows.digest.application.knowledge_graph.release import (
    enable_computable_textbook_rollout,
    get_release_snapshot,
    rollback_computable_textbook_rollout,
)
from app.workflows.interact.chat.lib.retrieval import retrieve_context


def _subject(session: Session, slug: str = "math") -> Subject:
    subject = Subject(user_id="local", slug=slug, name=slug, normalized_name=slug)
    session.add(subject)
    session.commit()
    session.refresh(subject)
    return subject


def test_p6_incremental_markdown_sync_preserves_anchor_identity_and_diffs(session: Session) -> None:
    _subject(session)
    first = """
# Function {#ku_function}

A mapping between sets.

# Linear Function {#ku_linear_function} [type: definition] [prerequisite: Function] [related: Slope]

A linear function has a constant rate of change.
""".strip()

    report_1 = sync_markdown_knowledge_graph(session, subject="math", markdown=first, build_revision_no=1)

    assert set(report_1.anchors_seen) == {"ku_function", "ku_linear_function"}
    assert len(report_1.created_unit_ids) == 2
    assert len(report_1.created_edge_ids) == 2
    linear = session.exec(
        select(KnowledgeUnit).where(
            KnowledgeUnit.subject == "math",
            KnowledgeUnit.canonical_name == "Linear Function",
        )
    ).one()

    second = """
# Function {#ku_function}

A mapping between inputs and outputs.

# Affine Function {#ku_linear_function} [type: definition] [prerequisite: Function]

An affine function preserves the linear-rate idea with an offset.
""".strip()

    report_2 = sync_markdown_knowledge_graph(session, subject="math", markdown=second, build_revision_no=2)
    session.refresh(linear)

    assert linear.id in report_2.updated_unit_ids
    assert linear.canonical_name == "Affine Function"
    assert linear.status == "active"
    assert report_2.deprecated_edge_ids
    assert report_2.elapsed_ms < 1000


def test_p6_migration_normalizes_current_knowledge_graph_types(session: Session) -> None:
    _subject(session, "legacy")
    unit = KnowledgeUnit(
        subject="legacy",
        knowledge_unit_type="topic",
        canonical_name="Current Topic",
        normalized_name="current_topic",
        summary="needs normalization",
        status="active",
        type_source="old",
    )
    session.add(unit)
    session.commit()
    session.refresh(unit)
    other = knowledge_unit_repo.create_knowledge_unit(
        session,
        KnowledgeUnit(
            subject="legacy",
            knowledge_unit_type="concept",
            canonical_name="Other",
            normalized_name="other",
            status="active",
        ),
    )
    session.add(
        KnowledgeEdge(
            subject="legacy",
            source_node_id=unit.id or 0,
            target_node_id=other.id or 0,
            edge_type="requires",
            status="active",
        )
    )
    session.commit()

    report = normalize_knowledge_graph(session, subject="legacy")

    assert report.normalized_units >= 1
    assert report.normalized_edges == 1
    session.refresh(unit)
    assert unit.knowledge_unit_type == "concept"
    assert unit.type_source == "manual"


def test_p6_release_snapshot_and_rollback_restore_previous_revision(session: Session) -> None:
    _subject(session, "release")
    old_unit = knowledge_unit_repo.create_knowledge_unit(
        session,
        KnowledgeUnit(
            subject="release",
            knowledge_unit_type="concept",
            canonical_name="Old Unit",
            normalized_name="old_unit",
            status="active",
            build_revision_no=1,
        ),
    )
    new_unit = knowledge_unit_repo.create_knowledge_unit(
        session,
        KnowledgeUnit(
            subject="release",
            knowledge_unit_type="concept",
            canonical_name="New Unit",
            normalized_name="new_unit",
            status="deprecated",
            build_revision_no=2,
        ),
    )

    first = enable_computable_textbook_rollout(session, subject="release", revision_no=1)
    second = enable_computable_textbook_rollout(session, subject="release", revision_no=2, rollout_percent=25)

    assert first.rollback_available is False
    assert second.rollback_available is True
    assert second.observability["rollout_percent"] == 25

    rolled_back = rollback_computable_textbook_rollout(session, subject="release")
    session.refresh(old_unit)
    session.refresh(new_unit)

    assert rolled_back.active_revision_no == 1
    assert old_unit.status == "active"
    assert new_unit.status == "deprecated"
    assert get_release_snapshot(session, subject="release").observability["active_unit_count"] == 1


def test_p6_regression_retrieval_and_exam_hit_synced_knowledge_units(session: Session) -> None:
    _subject(session, "regression")
    markdown = """
# Derivative {#ku_derivative}

Derivative measures instantaneous rate of change.
""".strip()
    sync_markdown_knowledge_graph(session, subject="regression", markdown=markdown, build_revision_no=1)

    retrieved = asyncio.run(
        retrieve_context(
            session=session,
            query="What is a Derivative?",
            subject="regression",
            top_k=3,
            similarity_threshold=0.2,
            user_id="local",
        )
    )
    picked = _pick_knowledge_units(
        session,
        subject="regression",
        focus_prompt="Derivative",
        limit=3,
    )

    assert retrieved[0].knowledge_unit_name == "Derivative"
    assert picked[0].canonical_name == "Derivative"
