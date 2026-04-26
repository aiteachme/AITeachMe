import asyncio

import app.workflows.digest.kg_doc_sync.lib.extraction as extractor
from app.workflows.digest.kg_doc_sync.lib.extraction import ChunkExtractionResult


def test_docs_fallback_qualifies_generic_subsection_heading(monkeypatch):
    async def fake_acompletion_structured(*args, **kwargs):
        return ChunkExtractionResult(nodes=[], edges=[])

    monkeypatch.setattr(extractor, "acompletion_structured", fake_acompletion_structured)

    result, diagnostics = asyncio.run(
        extractor.extract_candidates_with_diagnostics(
            chunk_content="导数的几何意义是切线斜率。",
            chunk_title="几何意义",
            header_path="导数 > 几何意义",
            doc_source_type="knowledge_doc_markdown",
            allow_markdown_anchor_short_circuit=False,
        )
    )

    assert diagnostics.used_topic_fallback is True
    assert [node.name for node in result.nodes] == ["导数的几何意义"]
    assert result.nodes[0].knowledge_unit_type == "remark"


def test_docs_fallback_does_not_expand_section_into_key_term_shells(monkeypatch):
    async def fake_acompletion_structured(*args, **kwargs):
        return ChunkExtractionResult(nodes=[], edges=[])

    monkeypatch.setattr(extractor, "acompletion_structured", fake_acompletion_structured)

    result, diagnostics = asyncio.run(
        extractor.extract_candidates_with_diagnostics(
            chunk_content="定义：导数表示函数的瞬时变化率。\n公式：f'(x)=\\lim_{h\\to0}\\frac{f(x+h)-f(x)}{h}",
            chunk_title="导数",
            header_path="导数",
            doc_source_type="knowledge_doc_markdown",
            allow_markdown_anchor_short_circuit=False,
        )
    )

    assert diagnostics.used_topic_fallback is True
    names = {node.name for node in result.nodes}
    assert "瞬时变化率" not in names
    assert names == {"导数", "导数定义", "导数公式"}
