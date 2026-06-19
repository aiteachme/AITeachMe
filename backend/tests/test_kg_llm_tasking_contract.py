"""KG-doc-sync LLM task scheduling contracts."""

from __future__ import annotations

import pytest

from app.workflows.digest.kg_doc_sync.lib import extraction
from app.workflows.digest.kg_doc_sync.lib.extraction import (
    CandidateEdge,
    CandidateNode,
    ChunkExtractionResult,
)
from app.workflows.digest.kg_doc_sync.prompts.section_graph import SYSTEM_PROMPT_KNOWLEDGE_EXTRACT


def test_kg_prompt_requires_renderable_formula_names() -> None:
    assert "$...$" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert "$$...$$" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert "不要输出裸" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert "\\sqrt{}" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert "\\frac{}" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert "\\infty" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert "端点必须精确匹配本次返回的节点名" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT


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


def test_kg_prompt_rejects_lesson_plan_wrappers_at_generation_time() -> None:
    prompt = SYSTEM_PROMPT_KNOWLEDGE_EXTRACT

    assert "不要做关键词提取" in prompt
    assert "可复习、可教学、可出题的知识单元" in prompt
    assert "学习目标、课程安排、题量计划、检测说明和纯流程壳不入图" in prompt
    assert "只保留那个真实知识对象" in prompt
    assert "节点命名决策流程" in prompt
    assert "图示”“方法步骤”“单元测试”“重点检查概念理解”“讲后纠错与回顾" in prompt
    assert "小测与错题回看" in prompt
    assert "错题回看方法" in prompt
    assert "不能把它包装成 `procedure`" in prompt
    assert "计算条件遗漏" in prompt
    assert "学习活动不能直接入图" in prompt
    assert "概率事件判断误区" in prompt
    assert "图表分析结论表达" in prompt
    assert "整理”“判定题”“图表分析" in prompt
    assert "统计数据整理方法" in prompt
    assert "几何判定条件识别" in prompt
    assert "节点名去掉课程上下文后仍必须是一个可教学、可出题的学科对象" in prompt


def test_candidate_node_schema_rejects_review_container_names_in_contract_text() -> None:
    schema = CandidateNode.model_json_schema()
    name_description = schema["properties"]["name"]["description"]

    assert "禁止输出学习活动/复盘容器" in name_description
    assert "错题回看方法" in name_description
    assert "小测与错题回看" in name_description
    assert "整理" in name_description
    assert "判定题" in name_description


def test_kg_prompt_rejects_symbol_fragments_and_placeholder_case_names_at_generation_time() -> None:
    prompt = SYSTEM_PROMPT_KNOWLEDGE_EXTRACT

    assert "\\delta_2" in prompt
    assert "\\dots" in prompt
    assert "案例一" in prompt
    assert "ε-δ 证明中的 δ 取值策略" in prompt
    assert "三角不等式放缩法" in prompt
    assert "procedure` 必须是可复用的具体方法或流程名" in prompt


def test_kg_prompt_requires_connected_course_graph_at_generation_time() -> None:
    prompt = SYSTEM_PROMPT_KNOWLEDGE_EXTRACT

    assert "图谱必须尽量连通" in prompt
    assert "不要让一批节点只以孤岛形式出现" in prompt
    assert "必须填写 `taxonomy_hint`" in prompt
    assert "优先返回能互相连起来的一组节点和关系" in prompt


def test_kg_extraction_contract_allows_richer_section_outputs() -> None:
    schema = ChunkExtractionResult.model_json_schema()

    assert "内容充实的知识小节通常应覆盖 4-7 个真实节点" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert "本片段最多 12 个节点、18 条关系" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert "默认 8 题练习会从约 32 个候选知识单元中规划题目" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert "完整试卷最多会使用 60 个候选单元" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert "`topic` 主要用于连通结构，不能替代可出题单元" in SYSTEM_PROMPT_KNOWLEDGE_EXTRACT
    assert schema["properties"]["nodes"]["maxItems"] == 12
    assert schema["properties"]["edges"]["maxItems"] == 18
