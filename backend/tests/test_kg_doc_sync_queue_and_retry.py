import asyncio

from sqlmodel import SQLModel, Session, create_engine, select

from app.models.knowledge_unit import KnowledgeUnit

from app.workflows.digest.kg_doc_sync.lib.extraction import (
    CandidateExtractionDiagnostics,
    CandidateNode,
    ChunkExtractionResult,
)
import app.workflows.digest.kg_doc_sync.lib.incremental_sync as incremental_sync
from app.workflows.digest.kg_doc_sync.lib.incremental_sync import sync_markdown_knowledge_graph


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

    monkeypatch.setattr(
        incremental_sync,
        "extract_candidates_with_diagnostics",
        fake_extract_candidates_with_diagnostics,
    )
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)
    monkeypatch.setattr(incremental_sync, "_DOCS_SYNC_SECTION_RETRY_DELAY_S", 0.0)

    markdown = """# Retry Topic <!-- ATM_KU: ku_retry-topic -->

Body A.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)

    assert attempts["Retry Topic"] == 2
    assert report.unit_change_count == 1
    assert report.successful_section_count == 1
    assert report.failed_section_count == 0


def test_sync_markdown_knowledge_graph_keeps_successful_sections_after_terminal_failure(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    attempts = {"Broken Topic": 0, "Good Topic": 0}

    async def fake_extract_candidates_with_diagnostics(**kwargs):
        chunk_title = kwargs["chunk_title"]
        attempts[chunk_title] += 1
        if chunk_title == "Broken Topic":
            raise RuntimeError("permanent extraction failure")
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

    monkeypatch.setattr(
        incremental_sync,
        "extract_candidates_with_diagnostics",
        fake_extract_candidates_with_diagnostics,
    )
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)
    monkeypatch.setattr(incremental_sync, "_DOCS_SYNC_SECTION_RETRY_DELAY_S", 0.0)

    markdown = """# Good Topic

Body A.

# Broken Topic

Body B.
"""

    with Session(engine) as session:
        report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)

    assert attempts["Good Topic"] == 1
    assert attempts["Broken Topic"] == 2
    assert report.unit_change_count == 1
    assert report.successful_section_count == 1
    assert report.failed_section_count == 1
    assert report.llm_error_count == 1


def test_partial_docs_sync_does_not_deprecate_units_from_failed_sections(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    fail_broken = {"enabled": False}

    async def fake_extract_candidates_with_diagnostics(**kwargs):
        chunk_title = kwargs["chunk_title"]
        if chunk_title == "Broken Topic" and fail_broken["enabled"]:
            raise RuntimeError("permanent extraction failure")
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

    monkeypatch.setattr(
        incremental_sync,
        "extract_candidates_with_diagnostics",
        fake_extract_candidates_with_diagnostics,
    )
    monkeypatch.setattr(incremental_sync, "search_knowledge", _empty_search_knowledge)
    monkeypatch.setattr(incremental_sync, "_DOCS_SYNC_SECTION_RETRY_DELAY_S", 0.0)

    markdown = """# Good Topic

Body A.

# Broken Topic

Body B.
"""

    with Session(engine) as session:
        first_report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)
        fail_broken["enabled"] = True
        second_report = sync_markdown_knowledge_graph(session, subject="math", markdown=markdown)
        units = list(session.exec(select(KnowledgeUnit).order_by(KnowledgeUnit.canonical_name)).all())

    assert first_report.unit_change_count == 2
    assert second_report.failed_section_count == 1
    assert second_report.deprecated_unit_count == 0
    assert [(unit.canonical_name, unit.status) for unit in units] == [
        ("Broken Topic", "active"),
        ("Good Topic", "active"),
    ]


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

    monkeypatch.setattr(
        incremental_sync,
        "extract_candidates_with_diagnostics",
        fake_extract_candidates_with_diagnostics,
    )
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
