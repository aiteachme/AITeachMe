import asyncio

import app.workflows.digest.kg_doc_sync.lib.extraction as extractor
from app.workflows.digest.kg_doc_sync.lib.extraction import ChunkExtractionResult


def test_docs_section_empty_result_retries_with_llm_repair(monkeypatch):
    calls = {"count": 0}

    async def fake_acompletion_structured(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ChunkExtractionResult(nodes=[], edges=[])
        return ChunkExtractionResult(
            nodes=[
                extractor.CandidateNode(
                    name="Derivative",
                    knowledge_unit_type="concept",
                    local_summary="Derivative describes instantaneous rate of change.",
                    taxonomy_hint="Derivative",
                )
            ],
            edges=[],
        )

    monkeypatch.setattr(extractor, "acompletion_structured", fake_acompletion_structured)

    result, diagnostics = asyncio.run(
        extractor.extract_candidates_with_diagnostics(
            chunk_content="# Derivative\nDefinition: derivative describes instantaneous rate of change.",
            chunk_title="Derivative",
            header_path="Derivative",
            doc_source_type="knowledge_doc_markdown",
            allow_markdown_anchor_short_circuit=False,
        )
    )

    assert calls["count"] == 2
    assert diagnostics.used_topic_fallback is False
    assert diagnostics.used_question_fallback is False
    assert any(node.name == "Derivative" for node in result.nodes)


def test_docs_section_empty_result_without_strong_signal_returns_empty(monkeypatch):
    calls = {"count": 0}

    async def fake_acompletion_structured(*args, **kwargs):
        calls["count"] += 1
        return ChunkExtractionResult(nodes=[], edges=[])

    monkeypatch.setattr(extractor, "acompletion_structured", fake_acompletion_structured)

    result, diagnostics = asyncio.run(
        extractor.extract_candidates_with_diagnostics(
            chunk_content="# Short note\nThis is a short paragraph.",
            chunk_title="Short note",
            header_path="Short note",
            doc_source_type="knowledge_doc_markdown",
            allow_markdown_anchor_short_circuit=False,
        )
    )

    assert calls["count"] == 1
    assert diagnostics.used_topic_fallback is False
    assert diagnostics.used_question_fallback is False
    assert result.nodes == []
    assert result.edges == []


def test_docs_section_timeout_fails_without_local_fallback(monkeypatch):
    async def fake_acompletion_structured(*args, **kwargs):
        await asyncio.sleep(0.05)
        return ChunkExtractionResult(nodes=[], edges=[])

    monkeypatch.setattr(extractor, "acompletion_structured", fake_acompletion_structured)
    monkeypatch.setattr(extractor, "_DOCS_SYNC_SECTION_LLM_TIMEOUT_S", 0.01)

    try:
        asyncio.run(
            extractor.extract_candidates_with_diagnostics(
                chunk_content="# Short note\nThis is a short paragraph.",
                chunk_title="Short note",
                header_path="Short note",
                doc_source_type="knowledge_doc_markdown",
                allow_markdown_anchor_short_circuit=False,
            )
        )
    except TimeoutError:
        pass
    else:
        raise AssertionError("expected timeout to fail instead of using local fallback")
