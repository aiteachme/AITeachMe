import asyncio

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


def test_sync_markdown_knowledge_graph_retries_failed_section(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    attempts = {"Retry Topic": 0}

    async def fake_extract_candidates_with_diagnostics(**kwargs):
        chunk_title = kwargs["chunk_title"]
        if chunk_title == "Retry Topic":
            attempts[chunk_title] += 1
            if attempts[chunk_title] == 1:
                raise RuntimeError("transient failure")
        return (
            ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        name=chunk_title,
                        knowledge_unit_type="concept",
                        local_summary=f"{chunk_title} extracted.",
                        taxonomy_hint=chunk_title,
                    )
                ],
                edges=[],
            ),
            CandidateExtractionDiagnostics(llm_attempted=True, node_count=1, edge_count=0),
        )

    monkeypatch.setattr(incremental_sync, "extract_candidates_with_diagnostics", fake_extract_candidates_with_diagnostics)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)
    monkeypatch.setattr(incremental_sync, "_DOCS_SYNC_SECTION_RETRY_DELAY_S", 0.0)

    markdown = """# Retry Topic <!-- ATM_KU: ku_retry-topic -->

Body A.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)

    assert attempts["Retry Topic"] == 2
    assert report.unit_change_count == 1


def test_sync_markdown_knowledge_graph_limits_section_concurrency(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    state = {"current": 0, "peak": 0}

    async def fake_extract_candidates_with_diagnostics(**kwargs):
        state["current"] += 1
        state["peak"] = max(state["peak"], state["current"])
        await asyncio.sleep(0.02)
        state["current"] -= 1
        return (
            ChunkExtractionResult(
                nodes=[
                    CandidateNode(
                        name=kwargs["chunk_title"],
                        knowledge_unit_type="concept",
                        local_summary=f"{kwargs['chunk_title']} extracted.",
                        taxonomy_hint=kwargs["chunk_title"],
                    )
                ],
                edges=[],
            ),
            CandidateExtractionDiagnostics(llm_attempted=True, node_count=1, edge_count=0),
        )

    monkeypatch.setattr(incremental_sync, "extract_candidates_with_diagnostics", fake_extract_candidates_with_diagnostics)
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)
    monkeypatch.setattr(incremental_sync, "_DOCS_SYNC_SECTION_CONCURRENCY_LIMIT", 2)

    markdown = """# Topic A <!-- ATM_KU: ku_topic-a -->

Body A.

# Topic B <!-- ATM_KU: ku_topic-b -->

Body B.

# Topic C <!-- ATM_KU: ku_topic-c -->

Body C.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)

    assert report.unit_change_count == 3
    assert state["peak"] <= 2
