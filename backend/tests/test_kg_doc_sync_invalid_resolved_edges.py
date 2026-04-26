from sqlmodel import SQLModel, Session, create_engine, select

from app.models.knowledge_relation import KnowledgeEdge
from app.workflows.digest.kg_doc_sync.lib.extraction import (
    CandidateExtractionDiagnostics,
    CandidateEdge,
    CandidateNode,
    ChunkExtractionResult,
)
import app.workflows.digest.kg_doc_sync.lib.incremental_sync as incremental_sync
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import sync_markdown_knowledge_graph


async def _empty_search_knowledge(*args, **kwargs):
    return []


def test_sync_markdown_knowledge_graph_skips_invalid_edges_after_resolution(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates_with_diagnostics(**kwargs):
        chunk_title = kwargs["chunk_title"]
        if chunk_title == "Theorem Topic":
            return (
                ChunkExtractionResult(
                    nodes=[
                        CandidateNode(
                            name="Key Theorem",
                            knowledge_unit_type="theorem",
                            local_summary="Theorem summary.",
                            taxonomy_hint="Theorem Topic",
                        )
                    ],
                    edges=[
                        CandidateEdge(
                            source_name="Key Theorem",
                            target_name="Example 1",
                            edge_type="similar",
                            description="Invalid theorem-example similarity edge.",
                        )
                    ],
                ),
                CandidateExtractionDiagnostics(llm_attempted=True, node_count=1, edge_count=1),
            )
        return (
            ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        name="Example 1",
                        knowledge_unit_type="example",
                        local_summary="Example summary.",
                        taxonomy_hint="Example Topic",
                        parent_entity_name="Example Topic",
                    )
                ],
                edges=[],
            ),
            CandidateExtractionDiagnostics(llm_attempted=True, node_count=1, edge_count=0),
        )

    monkeypatch.setattr(incremental_sync, "extract_candidates_with_diagnostics", fake_extract_candidates_with_diagnostics)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = """# Theorem Topic <!-- ATM_KU: ku_theorem-topic -->

Body A.

# Example Topic <!-- ATM_KU: ku_example-topic -->

Body B.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)
        edges = session.exec(select(KnowledgeEdge)).all()

    assert report.unit_change_count == 2
    assert edges == []
