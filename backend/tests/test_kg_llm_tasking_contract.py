"""KG-doc-sync LLM task scheduling contracts."""

from __future__ import annotations

import pytest

from app.workflows.digest.kg_doc_sync.lib import extraction
from app.workflows.digest.kg_doc_sync.lib.extraction import (
    CandidateNode,
    ChunkExtractionResult,
)


@pytest.mark.anyio
async def test_kg_section_extraction_uses_run_llm_tasks(monkeypatch) -> None:
    scheduler_calls: list[dict[str, object]] = []

    async def fake_run_llm_tasks(items, worker, *, max_concurrent=None, on_result=None):
        queued = list(items)
        scheduler_calls.append({"items": queued, "max_concurrent": max_concurrent})
        results = []
        for index, item in enumerate(queued):
            result = await worker(item)
            if on_result is not None:
                await on_result(index, item, result)
            results.append(result)
        return results

    async def fake_structured(*args, **kwargs):
        assert kwargs.get("response_model") is ChunkExtractionResult
        return ChunkExtractionResult(
            nodes=[
                CandidateNode(
                    name="函数单调性",
                    knowledge_unit_type="concept",
                    local_summary="函数值随自变量变化的趋势。",
                    taxonomy_hint="函数图像",
                )
            ]
        )

    monkeypatch.setattr(extraction, "run_llm_tasks", fake_run_llm_tasks)
    monkeypatch.setattr(extraction, "acompletion_structured", fake_structured)

    result, diagnostics = await extraction.extract_candidates_with_diagnostics(
        "函数单调性描述函数值随自变量增加而增加或减少，是分析函数图像的重要概念。",
        "函数单调性",
        "函数图像 / 函数单调性",
        allow_markdown_anchor_short_circuit=False,
    )

    assert [node.name for node in result.nodes] == ["函数单调性"]
    assert diagnostics.llm_attempted is True
    assert diagnostics.node_count == 1
    assert scheduler_calls == [{"items": [None], "max_concurrent": 1}]
