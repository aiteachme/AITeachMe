from sqlmodel import SQLModel, Session, create_engine

from app.workflows.digest.kg_docs_sync.lib.extraction import (
    CandidateExtractionDiagnostics,
    CandidateNode,
    ChunkExtractionResult,
)
import app.workflows.digest.kg_docs_sync.lib.incremental_sync as incremental_sync
from app.workflows.digest.kg_docs_sync.lib.incremental_sync import sync_markdown_knowledge_graph


async def _empty_search_knowledge(*args, **kwargs):
    return []


def test_sync_markdown_knowledge_graph_reuses_existing_unit_for_duplicate_names(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    async def fake_extract_candidates_with_diagnostics(**kwargs):
        chunk_title = kwargs["chunk_title"]
        return (
            ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        name="Example 1",
                        knowledge_unit_type="example",
                        local_summary=f"{chunk_title} example.",
                        taxonomy_hint=chunk_title,
                        parent_entity_name=chunk_title,
                    )
                ],
                edges=[],
            ),
            CandidateExtractionDiagnostics(llm_attempted=True, node_count=1, edge_count=0),
        )

    monkeypatch.setattr(incremental_sync, "extract_candidates_with_diagnostics", fake_extract_candidates_with_diagnostics)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = """# Topic A <!-- ATM_KU: ku_topic-a -->

Body A.

# Topic B <!-- ATM_KU: ku_topic-b -->

Body B.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)

    assert report.unit_change_count >= 1
