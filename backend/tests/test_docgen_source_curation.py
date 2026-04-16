from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import patch

from app.shared.infra.execution import TracedExecutionContext, TracedExecutionResult
from app.shared.infra.search import SourceCurator
from app.shared.infra.search.types import SearchResult
from app.shared.infra.tools.builtin.markdown_processing import append_reference_section, normalize_mermaid_blocks
from app.shared.infra.workflow.context import create_langgraph_dev_context
from app.workflows.digest.docgen.graph import (
    build_enrich_assets_node,
    build_merge_drafts_node,
    build_write_chapters_node,
)
from app.workflows.digest.docgen.lib.publish import (
    _build_chapter_manifest,
    _build_source_scope,
    build_merged_markdown,
)


def test_source_curator_prioritizes_local_and_trusted_sources() -> None:
    curator = SourceCurator(TracedExecutionContext(subject="demo"))
    curated, metadata = asyncio.run(
        curator.curate_sources(
            query="partial derivative geometric meaning examples",
            max_results=3,
            sources=[
                SearchResult(
                    url="https://baidu.com/zhidao/question/123",
                    title="low value qa",
                    snippet="aggregated answer content",
                    score=0.9,
                    source="duckduckgo",
                ),
                SearchResult(
                    url="https://example.com/blog/partial-derivative",
                    title="Partial Derivative Geometry",
                    snippet="intro to geometric meaning and examples",
                    score=0.9,
                    source="duckduckgo",
                ),
                SearchResult(
                    url="https://ocw.mit.edu/courses/partial-derivatives",
                    title="Partial Derivatives Notes",
                    snippet="geometric meaning, cross sections, worked examples",
                    score=0.75,
                    source="bing",
                ),
                SearchResult(
                    url="local://chunk/42",
                    title="local notes",
                    snippet="partial derivative geometric meaning and examples",
                    score=0.2,
                    source="local_rag",
                ),
                SearchResult(
                    url="https://ocw.mit.edu/courses/partial-derivatives",
                    title="Partial Derivatives Notes",
                    snippet="duplicate result",
                    score=0.7,
                    source="bing",
                ),
            ],
        )
    )

    urls = [item.url for item in curated]
    assert urls[0] == "local://chunk/42"
    assert "https://ocw.mit.edu/courses/partial-derivatives" in urls
    assert all("baidu.com/zhidao" not in url for url in urls)
    assert metadata["candidate_count"] == 5
    assert metadata["filtered_count"] == 3
    assert metadata["selected_count"] == 3


def test_source_curator_prioritizes_cjk_matches_over_generic_high_score_results() -> None:
    curator = SourceCurator(TracedExecutionContext(subject="demo"))
    curated, _ = asyncio.run(
        curator.curate_sources(
            query="高等数学 极限 定义 性质",
            max_results=3,
            sources=[
                SearchResult(
                    url="https://example.com/history-overview",
                    title="世界历史概述",
                    snippet="梳理欧洲历史发展脉络。",
                    score=0.98,
                    source="duckduckgo",
                ),
                SearchResult(
                    url="https://math.example.cn/limit-definition",
                    title="高等数学极限的定义与性质",
                    snippet="介绍极限概念、基本性质与典型例题。",
                    score=0.35,
                    source="duckduckgo",
                ),
                SearchResult(
                    url="https://www.zhihu.com/question/limit",
                    title="高数里的极限应该怎么理解",
                    snippet="从定义、几何直观和常见误区解释极限。",
                    score=0.42,
                    source="duckduckgo",
                ),
            ],
        )
    )

    urls = [item.url for item in curated]
    assert urls[0] == "https://math.example.cn/limit-definition"
    assert urls[-1] == "https://example.com/history-overview"


def test_append_reference_section_dedupes_and_is_idempotent() -> None:
    markdown = "# Example Chapter\n\nA short explanation with one source."
    source_details = [
        {"url": "local://chunk/1", "title": "Local Notes", "source": "local_rag"},
        {"url": "https://example.edu/partial", "title": "Partial Derivatives", "source": "bing"},
        {"url": "https://example.edu/partial", "title": "Partial Derivatives", "source": "duckduckgo"},
    ]

    enriched = append_reference_section(markdown, source_details)
    enriched_again = append_reference_section(enriched, source_details)

    assert "## 参考资料与延伸阅读" in enriched
    assert enriched.count("https://example.edu/partial") == 1
    assert "- Local Notes (local_rag)" in enriched
    assert enriched_again.count("## 参考资料与延伸阅读") == 1


def test_normalize_mermaid_blocks_repairs_missing_fences_and_quote_prefix() -> None:
    markdown = """
> ```mermaid
> mindmap
>   root((线性代数))
>     向量空间
>       判别方法
### 题型拆解
- 看清楚封闭性
""".strip()

    normalized = normalize_mermaid_blocks(markdown)

    assert "> ```mermaid" not in normalized
    assert normalized.count("```mermaid") == 1
    assert "root((线性代数))" in normalized
    assert "```" in normalized
    assert "### 题型拆解" in normalized


def test_docgen_chapter_metadata_preserves_research_fields_and_builds_overview() -> None:
    captured: dict[str, object] = {}

    class FakePedagogyWriter:
        def __init__(self, context) -> None:
            captured["context"] = context

        async def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return TracedExecutionResult(
                content=(
                    "# Example Chapter\n\n"
                    "## 全局脉络图\n\n"
                    "```mermaid\n"
                    "mindmap\n"
                    "  root((Example Chapter))\n"
                    "    概念关系\n"
                    "``` A[bad trailing graph]\n\n"
                    "## Core Idea\n\n"
                    "One clean explanation."
                )
            )

    requested_at = datetime.utcnow()
    context = create_langgraph_dev_context("digest.docgen.source_test")
    craft_node = build_write_chapters_node(context=context)
    collect_node = build_merge_drafts_node(context=context)
    enrich_node = build_enrich_assets_node(context=context)

    craft_state = {
        "subject": "demo",
        "requested_at": requested_at,
        "build_session_id": "build-1",
        "planner_session_id": "planner-1",
        "confirmed_plan_id": "plan-1",
        "digest_mode": "systematic",
        "tone": "encouraging",
        "chapter_material": {
            "chapter_index": 1,
            "title": "Example Chapter",
            "required_elements": ["definition", "example"],
            "source_file_ids": [11],
            "sources": ["local://chunk/1", "https://example.edu/partial"],
            "source_details": [
                {"url": "local://chunk/1", "title": "Local Notes", "source": "local_rag"},
                {"url": "https://example.edu/partial", "title": "Partial Derivatives", "source": "bing"},
            ],
            "research_summary": "Explain the definition and connect it to an example.",
            "research_ms": 128,
            "local_hits": 2,
            "web_hits": 1,
            "fallback_used": True,
            "compression_mode": "embedding_filter",
            "executed_queries": ["partial derivative meaning", "partial derivative example"],
            "curated_source_count": 2,
            "dense_context": "A compact derivation and one worked example.",
        },
    }

    with patch("app.workflows.digest.docgen.nodes.write_chapters_node.PedagogyWriter", new=FakePedagogyWriter), patch(
        "app.workflows.digest.docgen.nodes.merge_drafts_node.update_knowledge_build_status"
    ):
        craft_result = asyncio.run(craft_node(craft_state))
        collect_result = asyncio.run(
            collect_node(
                {
                    "subject": "demo",
                    "requested_at": requested_at,
                    "digest_mode": "systematic",
                    "document_context": {
                        "subject": "demo",
                        "digest_mode": "systematic",
                        "course_type": "systematic",
                        "retrieval_profile": "docgen_systematic",
                        "tone": "encouraging",
                        "user_goal": "Build a clean study document",
                        "plan_summary": "One focused chapter with clear evidence.",
                        "source_strategy": "local_first",
                    },
                    "chapter_drafts": craft_result["chapter_drafts"],
                }
            )
        )
        enrich_result = asyncio.run(
            enrich_node(
                {
                    "subject": "demo",
                    "requested_at": requested_at,
                    "digest_mode": "systematic",
                    "document_context": {
                        "subject": "demo",
                        "digest_mode": "systematic",
                        "course_type": "systematic",
                        "retrieval_profile": "docgen_systematic",
                        "tone": "encouraging",
                        "user_goal": "Build a clean study document",
                        "plan_summary": "One focused chapter with clear evidence.",
                        "source_strategy": "local_first",
                    },
                    "confirmed_plan": {"build_constraints": {"include_sources": True}},
                    "chapter_metadatas": collect_result["chapter_metadatas"],
                }
            )
        )

    draft = craft_result["chapter_drafts"][0]
    chapter = enrich_result["chapter_metadatas"][0]
    manifest = _build_chapter_manifest(chapter)
    source_scope = _build_source_scope(chapter)

    assert captured["kwargs"]["digest_mode"] == "systematic"
    assert draft["digest_mode"] == "systematic"
    assert draft["course_type"] == "systematic"
    assert draft["retrieval_profile"] == "docgen_systematic"
    assert draft["research_summary"] == "Explain the definition and connect it to an example."
    assert collect_result["chapter_metadatas"][0]["local_hits"] == 2
    assert collect_result["chapter_metadatas"][0]["executed_queries"] == [
        "partial derivative meaning",
        "partial derivative example",
    ]
    assert chapter["markdown"].count("```mermaid") == 1
    assert "``` A[bad trailing graph]" not in chapter["markdown"]
    assert "## Core Idea" in chapter["markdown"]
    assert "## 参考资料与延伸阅读" in chapter["markdown"]
    assert "https://example.edu/partial" in chapter["markdown"]
    assert "## 目录" in enrich_result["merged_markdown"]
    assert "## 章节路线图" in enrich_result["merged_markdown"]
    assert "资料策略：优先基于上传资料整理" in enrich_result["merged_markdown"]
    assert manifest["source_count"] == 2
    assert manifest["fallback_used"] is True
    assert source_scope["local_source_count"] == 1
    assert source_scope["external_source_count"] == 1
    assert source_scope["domains"] == ["example.edu"]


def test_build_merged_markdown_dedupes_curriculum_path_tail_title() -> None:
    merged = build_merged_markdown(
        [
            {
                "chapter_index": 1,
                "title": "线性方程组求解的完整路径",
                "curriculum_path": ["代数基础", "线性方程组求解的完整路径"],
                "markdown": "# 线性方程组求解的完整路径\n\n## 这章先拿下什么\n\n先看主线。",
            }
        ],
        document_context={
            "subject": "线性代数",
            "digest_mode": "systematic",
            "tone": "encouraging",
            "user_goal": "系统整理线性方程组求解",
            "plan_summary": "聚焦线性方程组求解路径。",
        },
    )

    assert "## 代数基础" in merged
    assert "\n## 线性方程组求解的完整路径\n" not in merged
    assert "\n### 线性方程组求解的完整路径 {#ku_线性方程组求解的完整路径}\n" in merged
