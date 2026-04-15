from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.shared.infra.search.types import ScrapedPage, SearchResult
from app.shared.infra.workflow.context import create_langgraph_dev_context
from app.workflows.digest.planner.concept_grounding import (
    build_planner_concept_queries,
    collect_planner_concept_briefing,
)
from app.workflows.digest.planner.graph import build_planner_graph
from app.workflows.digest.shared.models import FastTopicHints, SectionPacket, SharedInputs, SubjectProfile


def _build_shared_inputs() -> SharedInputs:
    return SharedInputs(
        section_packets=[
            SectionPacket(
                digest_chunk_uid="chunk_1",
                source_file_id=1,
                source_filename="math.md",
                chunk_index=0,
                page_num=1,
                title="极限",
                header_path="第一章 > 极限",
                level=2,
                normalized_content="极限描述变量逼近某个值时的变化趋势，连续与导数都以它为基础。",
                preview="极限描述变量逼近某个值时的变化趋势。",
                char_count=32,
            )
        ],
        fast_hints=FastTopicHints(chapter_candidates=["极限", "连续", "导数"]),
        subject_profile=SubjectProfile(
            subject_slug="subj_math",
            subject_name="高等数学",
            discipline="数学",
            sub_discipline="微积分",
            key_topics=["极限", "导数", "微分"],
            has_heavy_formulas=True,
        ),
    )


def test_build_planner_concept_queries_prefers_subject_and_topic_hints() -> None:
    queries = build_planner_concept_queries(
        subject="subj_math",
        user_goal="系统学习极限、导数与微分的基础概念",
        shared_inputs=_build_shared_inputs(),
        latest_plan={
            "chapter_plan": [
                {"title": "极限：定义与性质"},
                {"title": "导数：概念与运算"},
            ]
        },
    )

    assert queries[0] == "高等数学 基础概念 知识框架"
    assert len(queries) <= 4
    assert any("极限 定义 关键性质" == item for item in queries)
    assert any("导数 定义 关键性质" == item for item in queries)


def test_collect_planner_concept_briefing_merges_local_and_web_evidence(monkeypatch) -> None:
    shared_inputs = _build_shared_inputs()
    queries = build_planner_concept_queries(
        subject="subj_math",
        user_goal="系统学习极限、导数与微分的基础概念",
        shared_inputs=shared_inputs,
    )
    responses = {
        ("local_rag", queries[0]): [
            SearchResult(
                url="local://section/0",
                title="高等数学 - 基础框架",
                snippet="高等数学通常先梳理极限、连续、导数和微分之间的关系。",
                source="local_rag",
            )
        ],
        ("local_rag", queries[1]): [
            SearchResult(
                url="local://section/1",
                title="极限 - 定义与性质",
                snippet="极限研究变量在逼近过程中的稳定趋势，是连续与导数的前置概念。",
                source="local_rag",
            )
        ],
        ("duckduckgo", queries[0]): [
            SearchResult(
                url="https://example.com/gaodengshuxue",
                title="高等数学 - 百度百科",
                snippet="高等数学是研究函数、极限、微分和积分的基础课程。",
                source="duckduckgo",
            )
        ],
        ("duckduckgo", queries[1]): [
            SearchResult(
                url="https://example.com/jixian",
                title="极限 - 百度百科",
                snippet="极限是分析学中的核心概念，用来描述变化过程的逼近结果。",
                source="duckduckgo",
            )
        ],
    }

    class FakeRetriever:
        def __init__(self, name: str):
            self.name = name

        async def traced_search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
            return list(responses.get((self.name, query), []))[:max_results]

    monkeypatch.setattr(
        "app.workflows.digest.planner.concept_grounding.get_settings",
        lambda: SimpleNamespace(web_search_retriever="duckduckgo", planner_allow_external_search=True),
    )
    monkeypatch.setattr(
        "app.workflows.digest.planner.concept_grounding.get_retriever",
        lambda name, **kwargs: FakeRetriever(name),
    )
    monkeypatch.setattr(
        "app.workflows.digest.planner.concept_grounding.read_urls",
        lambda urls: asyncio.sleep(
            0,
            result=[
                ScrapedPage(
                    url="https://example.com/gaodengshuxue",
                    title="高等数学 - 百度百科",
                    content="高等数学研究函数、极限、微分和积分的基础理论，并强调这些概念之间的结构关系。",
                    success=True,
                ),
                ScrapedPage(
                    url="https://example.com/jixian",
                    title="极限 - 百度百科",
                    content="极限描述变量在某个过程中逐步逼近目标值，是连续与导数的前置概念。",
                    success=True,
                ),
            ],
        ),
    )

    briefing = asyncio.run(
        collect_planner_concept_briefing(
            subject="subj_math",
            user_goal="系统学习极限、导数与微分的基础概念",
            shared_inputs=shared_inputs,
        )
    )

    assert briefing.local_hit_count == 2
    assert briefing.web_hit_count == 2
    assert briefing.web_read_count == 2
    assert "快速概念检索锚点：" in briefing.briefing
    assert "[本地/local_rag]" in briefing.briefing
    assert "[外部/duckduckgo]" in briefing.briefing
    assert "建议优先覆盖的概念锚点" in briefing.briefing
    assert "极限" in briefing.topic_hints
    assert "结构关系" in briefing.briefing


def test_planner_graph_compiles_with_ground_concepts_node() -> None:
    compiled = build_planner_graph(
        context=create_langgraph_dev_context("digest.planner.concept_grounding_test")
    ).compile()

    node_ids = {node.id for node in compiled.get_graph().nodes.values()}

    assert "load_context" in node_ids
    assert "ground_concepts" in node_ids
    assert "draft_plan" in node_ids
