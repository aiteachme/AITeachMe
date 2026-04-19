from sqlmodel import Session, SQLModel, create_engine, select

from app.models.knowledge_relation import KnowledgeEdge
from app.workflows.support.knowledge_graph.incremental_sync import sync_markdown_knowledge_graph


def test_sync_markdown_knowledge_graph_creates_structural_edges():
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    markdown = """# Derivative

Derivative describes change rate.

## Geometric Meaning

Slope of the tangent line.

## Rules

Common derivative rules.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)
        edges = list(session.exec(select(KnowledgeEdge)).all())

    assert report.edge_change_count >= 2
    assert len(edges) >= 2
    assert all(edge.edge_type == "derivation" for edge in edges)
