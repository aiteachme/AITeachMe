from __future__ import annotations

from sqlmodel import Session

from app.models.knowledge_relation import EvidenceLink, KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.repositories.knowledge import knowledge_relation_repo, knowledge_unit_repo
from app.workflows.digest.application.knowledge_graph.query import KnowledgeGraphQueryService


def _unit(session: Session, *, subject: str, name: str, knowledge_unit_type: str = "concept") -> KnowledgeUnit:
    unit = knowledge_unit_repo.create_knowledge_unit(
        session,
        KnowledgeUnit(
            subject=subject,
            knowledge_unit_type=knowledge_unit_type,
            canonical_name=name,
            normalized_name=name.casefold().replace(" ", "_"),
            status="active",
            summary=f"Summary for {name}",
        ),
    )
    assert unit.id is not None
    return unit


def _edge(
    session: Session,
    *,
    subject: str,
    source: KnowledgeUnit,
    target: KnowledgeUnit,
    edge_type: str = "prerequisite",
) -> KnowledgeEdge:
    edge = knowledge_relation_repo.create_knowledge_edge(
        session,
        KnowledgeEdge(
            subject=subject,
            source_node_id=source.id or 0,
            target_node_id=target.id or 0,
            edge_type=edge_type,
            description=f"{source.canonical_name} -> {target.canonical_name}",
            status="active",
            confidence=0.9,
        ),
    )
    assert edge.id is not None
    return edge


def test_p3_lists_relations_and_finds_path(session: Session) -> None:
    subject = "math"
    function = _unit(session, subject=subject, name="Function")
    linear = _unit(session, subject=subject, name="Linear Function")
    slope = _unit(session, subject=subject, name="Slope")
    _edge(session, subject=subject, source=function, target=linear)
    _edge(session, subject=subject, source=linear, target=slope)

    service = KnowledgeGraphQueryService(session)

    relations = service.list_knowledge_unit_relations(
        subject=subject,
        knowledge_unit_id=linear.id or 0,
        direction="incoming",
    )
    assert [item.source_node_name for item in relations] == ["Function"]

    path = service.find_knowledge_path(
        subject=subject,
        source_knowledge_unit_id=function.id or 0,
        target_knowledge_unit_id=slope.id or 0,
        max_depth=3,
    )
    assert path.found
    assert [node.canonical_name for node in path.nodes] == ["Function", "Linear Function", "Slope"]
    assert [edge.edge_type for edge in path.edges] == ["prerequisite", "prerequisite"]


def test_p3_focus_subgraph_and_relation_explanation(session: Session) -> None:
    subject = "math"
    function = _unit(session, subject=subject, name="Function")
    linear = _unit(session, subject=subject, name="Linear Function")
    example = _unit(session, subject=subject, name="Linear Function Example", knowledge_unit_type="example")
    prerequisite = _edge(session, subject=subject, source=function, target=linear)
    _edge(session, subject=subject, source=example, target=linear, edge_type="example_of")
    knowledge_relation_repo.create_evidence_link(
        session,
        EvidenceLink(
            subject=subject,
            entity_type="edge",
            entity_id=prerequisite.id or 0,
            document_id=1,
            chunk_id=10,
            quote_text="Linear functions require the idea of a function.",
            evidence_role="supports",
            field_scope="edge_description",
        ),
    )

    service = KnowledgeGraphQueryService(session)

    subgraph = service.get_focus_subgraph(
        subject=subject,
        center_knowledge_unit_id=linear.id,
        hops=1,
    )
    assert {node.canonical_name for node in subgraph.nodes} == {
        "Function",
        "Linear Function",
        "Linear Function Example",
    }
    assert {edge.edge_type for edge in subgraph.edges} == {"prerequisite", "example_of"}

    explanation = service.explain_relation_path(
        subject=subject,
        source_knowledge_unit_id=function.id or 0,
        target_knowledge_unit_id=linear.id or 0,
    )
    assert explanation.path.found
    assert explanation.evidence[0].edge_id == prerequisite.id
    assert explanation.evidence[0].evidence[0].quote_text == "Linear functions require the idea of a function."
