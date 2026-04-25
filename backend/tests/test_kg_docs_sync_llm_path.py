from sqlmodel import SQLModel, Session, create_engine

from app.workflows.digest.kg_file_ingest.lib.extractor import (
    CandidateNode,
    ChunkExtractionResult,
)
import app.workflows.digest.kg_file_ingest.lib.extractor as extractor
import app.workflows.support.knowledge_graph.incremental_sync as incremental_sync
from app.workflows.support.knowledge_graph.incremental_sync import (
    sync_markdown_knowledge_graph,
)


async def _empty_search_knowledge(*args, **kwargs):
    return []


def test_sync_markdown_knowledge_graph_disables_markdown_anchor_short_circuit(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    observed_flags: list[bool] = []
    observed_contexts: list[str] = []

    async def fake_extract_candidates_with_diagnostics(**kwargs):
        observed_flags.append(bool(kwargs.get("allow_markdown_anchor_short_circuit", True)))
        observed_contexts.append(str(kwargs.get("subject_context") or ""))
        return (
            ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        name=kwargs["chunk_title"],
                        knowledge_unit_type="concept",
                        local_summary=f"{kwargs['chunk_title']} extracted through llm lane.",
                        taxonomy_hint=kwargs["chunk_title"],
                    )
                ],
                edges=[],
            ),
            extractor.CandidateExtractionDiagnostics(
                llm_attempted=True,
                node_count=1,
                edge_count=0,
            ),
        )

    monkeypatch.setattr(incremental_sync, "extract_candidates_with_diagnostics", fake_extract_candidates_with_diagnostics)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)

    markdown = """# Derivative <!-- ATM_KU: ku_derivative -->

Derivative describes change rate.

## Geometric Meaning <!-- ATM_KU: ku_geometric-meaning -->

Derivative can represent the slope of a tangent line.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(
            session,
            subject="math",
            markdown=markdown,
            subject_context="Calculus context for graph extraction.",
        )

    assert report.unit_change_count == 2
    assert report.section_count == 2
    assert report.llm_section_count == 2
    assert report.fallback_section_count == 0
    assert observed_flags == [False, False]
    assert observed_contexts == [
        "Calculus context for graph extraction.",
        "Calculus context for graph extraction.",
    ]
