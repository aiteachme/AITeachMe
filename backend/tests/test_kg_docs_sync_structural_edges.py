from sqlmodel import Session, SQLModel, create_engine, select

from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.workflows.digest.kg_docs_sync.lib.extraction import CandidateEdge, CandidateNode, ChunkExtractionResult
import app.workflows.digest.kg_docs_sync.lib.incremental_sync as incremental_sync
from app.workflows.digest.kg_docs_sync.lib.incremental_sync import sync_markdown_knowledge_graph


async def _empty_search_knowledge(*args, **kwargs):
    return []


def test_sync_markdown_knowledge_graph_extracts_multiple_units_per_chunk(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates(**kwargs):
        chunk_title = kwargs["chunk_title"]
        if chunk_title == "Derivative":
            return ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        name="Derivative",
                        knowledge_unit_type="concept",
                        local_summary="Derivative is the rate of change.",
                        taxonomy_hint="Derivative",
                    ),
                    CandidateNode(
                        name="Instantaneous Rate of Change",
                        knowledge_unit_type="definition",
                        local_summary="A derivative describes instantaneous rate of change.",
                        taxonomy_hint="Derivative",
                        parent_entity_name="Derivative",
                    ),
                    CandidateNode(
                        name="Tangent Slope",
                        knowledge_unit_type="concept",
                        local_summary="Derivative can be interpreted as tangent slope.",
                        taxonomy_hint="Derivative",
                    ),
                ],
                edges=[
                    CandidateEdge(
                        source_name="Instantaneous Rate of Change",
                        target_name="Derivative",
                        edge_type="derivation",
                        description="The definition supports the derivative concept.",
                    ),
                    CandidateEdge(
                        source_name="Tangent Slope",
                        target_name="Derivative",
                        edge_type="application",
                        description="Tangent slope is an application view of derivative.",
                    ),
                ],
            )
        return ChunkExtractionResult(nodes=[], edges=[])

    monkeypatch.setattr(incremental_sync, "extract_candidates", fake_extract_candidates)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = """# Derivative

Derivative describes change rate and tangent slope.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)
        units = list(session.exec(select(KnowledgeUnit)).all())
        edges = list(session.exec(select(KnowledgeEdge)).all())

    assert report.unit_change_count == 3
    assert {unit.canonical_name for unit in units} == {
        "Derivative",
        "Instantaneous Rate of Change",
        "Tangent Slope",
    }
    assert len(edges) == 2
    assert {edge.edge_type for edge in edges} == {"derivation", "application"}


def test_sync_markdown_knowledge_graph_skips_instructional_headings(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates(**kwargs):
        chunk_title = kwargs["chunk_title"]
        if chunk_title == "Derivative":
            return ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        name="Derivative",
                        knowledge_unit_type="concept",
                        local_summary="Derivative describes change rate.",
                        taxonomy_hint="Derivative",
                    )
                ],
                edges=[],
            )
        if chunk_title == "Geometric Meaning":
            return ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        name="Geometric Meaning",
                        knowledge_unit_type="concept",
                        local_summary="Geometric meaning links derivative to tangent slope.",
                        taxonomy_hint="Derivative",
                    )
                ],
                edges=[],
            )
        return ChunkExtractionResult(nodes=[], edges=[])

    monkeypatch.setattr(incremental_sync, "extract_candidates", fake_extract_candidates)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = """# How To Read This Document

Start with the roadmap.

# Derivative

Derivative describes change rate.

## Learning Goals

Understand the definition and geometric meaning.

## Geometric Meaning

Slope of the tangent line.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)
        units = list(session.exec(select(KnowledgeUnit)).all())

    assert report.unit_change_count == 2
    assert {unit.canonical_name for unit in units} == {"Derivative", "Geometric Meaning"}


def test_sync_markdown_knowledge_graph_uses_llm_extracted_relation_types(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates(**kwargs):
        return ChunkExtractionResult(
            nodes=[
                CandidateNode(
                    name="Derivative",
                    knowledge_unit_type="concept",
                    local_summary="Derivative describes change rate.",
                    taxonomy_hint="Derivative",
                ),
                CandidateNode(
                    name="Limit",
                    knowledge_unit_type="concept",
                    local_summary="Limit underpins derivative definition.",
                    taxonomy_hint="Derivative",
                ),
                CandidateNode(
                    name="Tangent Line",
                    knowledge_unit_type="concept",
                    local_summary="Tangent line gives a geometric view.",
                    taxonomy_hint="Derivative",
                ),
            ],
            edges=[
                CandidateEdge(
                    source_name="Limit",
                    target_name="Derivative",
                    edge_type="prerequisite",
                    description="Limit is a prerequisite for derivative.",
                ),
                CandidateEdge(
                    source_name="Derivative",
                    target_name="Tangent Line",
                    edge_type="similar",
                    description="Derivative is closely related to tangent line interpretation.",
                ),
            ],
        )

    monkeypatch.setattr(incremental_sync, "extract_candidates", fake_extract_candidates)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = """# Derivative

Derivative describes change rate.
"""

    with Session(engine) as session:
        sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)
        edges = list(session.exec(select(KnowledgeEdge)).all())

    assert {(edge.edge_type, edge.description) for edge in edges} == {
        ("prerequisite", "markdown_anchor_sync: Limit is a prerequisite for derivative."),
        ("similar", "markdown_anchor_sync: Derivative is closely related to tangent line interpretation."),
    }


def test_sync_markdown_knowledge_graph_resolves_edges_by_normalized_names(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates(**kwargs):
        return ChunkExtractionResult(
            nodes=[
                CandidateNode(
                    name="Pythagorean Theorem",
                    knowledge_unit_type="theorem",
                    local_summary="The theorem relates the sides of a right triangle.",
                    taxonomy_hint="Pythagorean Theorem",
                ),
                CandidateNode(
                    name="Right Triangle",
                    knowledge_unit_type="concept",
                    local_summary="A right triangle contains one 90-degree angle.",
                    taxonomy_hint="Pythagorean Theorem",
                ),
            ],
            edges=[
                CandidateEdge(
                    source_name="right-triangle",
                    target_name="pythagorean theorem",
                    edge_type="prerequisite",
                    description="Right triangle knowledge is required for the theorem.",
                ),
            ],
        )

    monkeypatch.setattr(incremental_sync, "extract_candidates", fake_extract_candidates)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = """# Pythagorean Theorem

The theorem relates the sides of a right triangle.
"""

    with Session(engine) as session:
        sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)
        edges = list(session.exec(select(KnowledgeEdge)).all())

    assert len(edges) == 1
    assert edges[0].edge_type == "prerequisite"


def test_sync_markdown_knowledge_graph_resolves_cross_section_edges(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates(**kwargs):
        chunk_title = kwargs["chunk_title"]
        if chunk_title == "Derivative":
            return ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        candidate_id="derivative-concept",
                        name="Derivative",
                        knowledge_unit_type="concept",
                        local_summary="Derivative describes change rate.",
                        taxonomy_hint="Derivative",
                    ),
                    CandidateNode(
                        candidate_id="tangent-line-concept",
                        name="Tangent Line",
                        knowledge_unit_type="concept",
                        local_summary="Tangent line gives a geometric view of derivative.",
                        taxonomy_hint="Derivative",
                    ),
                ],
                edges=[
                    CandidateEdge(
                        source_name="Tangent Line",
                        target_name="Derivative",
                        edge_type="application",
                        description="Tangent line is an application view of derivative.",
                    )
                ],
            )
        return ChunkExtractionResult(nodes=[], edges=[])

    monkeypatch.setattr(incremental_sync, "extract_candidates", fake_extract_candidates)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = """# Derivative

Derivative describes change rate.

## Tangent Line

Tangent line gives a geometric interpretation of derivative.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)
        edges = list(session.exec(select(KnowledgeEdge)).all())

    assert report.edge_change_count >= 1
    assert any(
        edge.edge_type == "application"
        and edge.description == "markdown_anchor_sync: Tangent line is an application view of derivative."
        for edge in edges
    )


def test_sync_markdown_knowledge_graph_builds_structural_edges_from_header_hierarchy(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates(**kwargs):
        chunk_title = kwargs["chunk_title"]
        if chunk_title == "Derivative":
            return ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        name="Derivative",
                        knowledge_unit_type="concept",
                        local_summary="Derivative describes change rate.",
                        taxonomy_hint="Derivative",
                    )
                ],
                edges=[],
            )
        if chunk_title == "Tangent Line":
            return ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        name="Tangent Line",
                        knowledge_unit_type="concept",
                        local_summary="Tangent line gives a geometric view of derivative.",
                        taxonomy_hint="Derivative",
                    )
                ],
                edges=[],
            )
        return ChunkExtractionResult(nodes=[], edges=[])

    monkeypatch.setattr(incremental_sync, "extract_candidates", fake_extract_candidates)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = """# Derivative

Derivative describes change rate.

## Tangent Line

Tangent line gives a geometric interpretation of derivative.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)
        edges = list(session.exec(select(KnowledgeEdge)).all())

    assert report.edge_change_count == 1
    assert len(edges) == 1
    assert edges[0].edge_type == "derivation"
    assert edges[0].description == "markdown_anchor_sync: Tangent Line 属于主题 Derivative。"
