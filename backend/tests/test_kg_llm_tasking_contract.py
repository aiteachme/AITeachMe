"""KG-doc-sync LLM task scheduling contracts."""

from __future__ import annotations

import pytest

from app.workflows.digest.kg_doc_sync.lib import extraction
from app.workflows.digest.kg_doc_sync.lib.extraction import (
    CandidateEdge,
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


@pytest.mark.anyio
async def test_kg_section_extraction_keeps_llm_contract_names_and_cleans_display_wrappers(monkeypatch) -> None:
    async def fake_run_llm_tasks(items, worker, *, max_concurrent=None, on_result=None):
        del max_concurrent, on_result
        return [await worker(item) for item in items]

    async def fake_structured(*args, **kwargs):
        del args, kwargs
        return ChunkExtractionResult(
            nodes=[
                CandidateNode(
                    name="**分部积分法**",
                    knowledge_unit_type="procedure",
                    local_summary="说明分部积分法的拆分思路。",
                ),
                CandidateNode(
                    name="$\\int u\\,dv = uv-\\int v\\,du$",
                    knowledge_unit_type="formula_model",
                    local_summary="分部积分公式。",
                ),
            ],
            edges=[
                CandidateEdge(
                    source_name="$\\int u\\,dv = uv-\\int v\\,du$",
                    target_name="**分部积分法**",
                    edge_type="applies_to",
                    description="方法使用公式。",
                ),
            ],
        )

    monkeypatch.setattr(extraction, "run_llm_tasks", fake_run_llm_tasks)
    monkeypatch.setattr(extraction, "acompletion_structured", fake_structured)

    result, diagnostics = await extraction.extract_candidates_with_diagnostics(
        "分部积分法把积分拆成两个因子处理，公式为 $\\int u\\,dv = uv-\\int v\\,du$。",
        "分部积分法",
        "不定积分 / 分部积分法",
        doc_source_type="knowledge_doc_markdown",
        allow_markdown_anchor_short_circuit=False,
    )

    assert [node.name for node in result.nodes] == ["分部积分法", "\\int u\\,dv = uv-\\int v\\,du"]
    assert all("**" not in node.name and "$" not in node.name for node in result.nodes)
    assert [(edge.source_name, edge.target_name, edge.edge_type) for edge in result.edges] == [
        ("\\int u\\,dv = uv-\\int v\\,du", "分部积分法", "applies_to")
    ]
    assert diagnostics.node_count == 2
