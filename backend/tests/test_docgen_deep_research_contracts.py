import pytest

from app.workflows.digest.docgen.lib.document_backbone import (
    apply_backbone_to_chapter_plan,
    build_document_backbone,
    fallback_document_backbone,
)
from app.shared.infra.tools.builtin.markdown_processing import normalize_mermaid_blocks
from app.workflows.digest.docgen.lib.asset_requests import (
    ASSET_REQUEST_BEGIN,
    ASSET_REQUEST_END,
    ASSET_REQUEST_LANGUAGE,
    build_asset_request_block,
    replace_asset_requests,
)
from app.workflows.digest.docgen.lib.query_planning import (
    QUERY_CONTEXT_ITEM_CHAR_BUDGET,
    QUERY_CONTEXT_ITEM_COUNT_BUDGET,
    ResearchSubQueryPlan,
    generate_sub_queries,
)
from app.workflows.digest.docgen.lib.publish import build_merged_markdown
from app.workflows.digest.docgen.lib.models import (
    BackboneResearchAgenda,
    ClaimEvidenceBinding,
    ClaimEvidenceMap,
    ClaimItem,
    ClaimLedger,
    ChapterGenerationPlan,
    ChapterGenerationTask,
    ChapterGenerationTaskSeed,
    ConflictItem,
    ConflictReport,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
)
from app.workflows.digest.docgen.nodes.generate_chapters import _chapter_plan_for_writer


def test_document_backbone_builds_claims_and_backfills_chapter_tasks():
    task_seed = ChapterGenerationTaskSeed(
        chapter_index=1,
        confirmed_title="导数基础",
        enhanced_title="导数基础",
        chapter_goal="理解导数定义和几何意义",
        required_elements=["导数定义", "几何意义"],
        retrieval_queries=["导数定义"],
    )
    evidence = HighConfidenceEvidenceUnit(
        evidence_id="ev1",
        source_ref="local://file/1/section/sec1",
        source_type="local",
        evidence_type="definition",
        text="导数描述函数在某一点附近的瞬时变化率。",
        chapter_affinity={1: 0.9},
        confidence=0.9,
    )
    backbone, warnings = build_document_backbone(
        task_seeds=[task_seed],
        agenda=BackboneResearchAgenda(
            topics=["导数基础"],
            glossary_candidates=["导数定义"],
            evidence_unit_ids=["ev1"],
        ),
        evidence_units=[evidence],
        file_summaries=[
            FileMaterialSummary(
                file_id=1,
                filename="calculus.md",
                concepts=["导数定义"],
                definitions=["导数定义"],
                chapter_affinity={1: 1.0},
            )
        ],
    )
    plan = ChapterGenerationPlan(
        subject="calculus",
        chapters=[
            ChapterGenerationTask(
                chapter_index=1,
                confirmed_title="导数基础",
                enhanced_title="导数基础",
                content_points=["导数定义"],
            )
        ],
    )
    updated = apply_backbone_to_chapter_plan(plan=plan, backbone=backbone)

    assert not warnings
    assert backbone.canonical_claim_pool
    assert backbone.source_trust_summary["evidence_unit_count"] == 1
    assert "导数定义" in updated.chapters[0].claim_targets


def test_document_backbone_fallback_is_non_blocking():
    backbone, warnings = fallback_document_backbone(
        task_seeds=[
            ChapterGenerationTaskSeed(
                chapter_index=1,
                confirmed_title="第一章",
                chapter_goal="兜底目标",
            )
        ],
        reason="boom",
    )

    assert backbone.fallback_used
    assert backbone.canonical_claim_pool[0].claim_text == "兜底目标"
    assert warnings[0].warning_id == "bb_fallback_used"


def test_mermaid_normalization_does_not_swallow_following_markdown():
    markdown = """```mermaid
mindmap
  root((TD))
---
``` A --> B[节点]
> [!NOTE]
> 建议配图：不要进入 Mermaid 块
### 再讲正文
正文
"""

    normalized = normalize_mermaid_blocks(markdown)

    assert "```mermaid\nmindmap\n  root((TD))\n```" in normalized
    assert "```mermaid\nflowchart TD\nA --> B[节点]\n```" in normalized
    assert "> [!NOTE]" in normalized
    assert "### 再讲正文" in normalized


def test_mermaid_normalization_drops_indented_context_echo_after_dirty_block():
    markdown = """```mermaid
mindmap
  root((HER-2验证路径))
    # 生物标志物五阶验证全流程
    ## 为什么这章是精准医疗的通关密钥
    这是一段被模型缩进回显的正文
    ---
```

## 后续正文
继续学习。
"""

    normalized = normalize_mermaid_blocks(markdown)

    assert "```mermaid\nmindmap\n  root((HER-2验证路径))\n```" in normalized
    assert "    # 生物标志物" not in normalized
    assert "    ---" not in normalized
    assert normalized.count("```") == 2
    assert "## 后续正文" in normalized


def test_merged_markdown_preserves_chapter_heading_levels():
    merged = build_merged_markdown(
        [
            {
                "chapter_index": 1,
                "title": "第一章",
                "markdown": "# 第一章\n\n## 核心内容\n\n正文",
            }
        ],
        document_context={"subject": "demo", "include_sources": False},
    )

    assert "\n# 第一章\n\n## 核心内容\n\n正文" in merged
    assert "\n## 第一章\n\n### 核心内容" not in merged


def test_writer_plan_preserves_structured_contract_lists():
    required = [f"覆盖点 {index}" for index in range(20)]
    claims = [
        ClaimItem(claim_id=f"c{index}", claim_text=f"主张 {index}")
        for index in range(12)
    ]
    bindings = [
        ClaimEvidenceBinding(claim_id=f"c{index}", evidence_ids=[f"e{index}"])
        for index in range(12)
    ]
    conflicts = [
        ConflictItem(conflict_id=f"conf{index}", detail=f"冲突 {index}", severity="warning")
        for index in range(12)
    ]

    plan = _chapter_plan_for_writer(
        ChapterGenerationTask(
            chapter_index=1,
            confirmed_title="长合同章节",
            enhanced_title="长合同章节",
            content_points=required,
            concept_targets=["核心概念"],
        ),
        total_chapters=1,
        claim_ledger=ClaimLedger(items=claims),
        claim_evidence_map=ClaimEvidenceMap(bindings=bindings),
        conflict_report=ConflictReport(items=conflicts),
    )

    assert plan["required_elements"] == [*required, "核心概念"]
    assert plan["execution_contract"]["coverage_requirements"] == [*required, "核心概念"]
    assert len(plan["execution_contract"]["claim_targets"]) == len(claims)
    assert len(plan["execution_contract"]["evidence_bindings"]) == len(bindings)
    assert len(plan["execution_contract"]["conflict_warnings"]) == len(conflicts)


@pytest.mark.anyio
async def test_query_planning_context_budget_only_affects_prompt_summary():
    original_context = [
        {"title": f"ctx-{index}", "detail": "x" * (QUERY_CONTEXT_ITEM_CHAR_BUDGET + 50)}
        for index in range(QUERY_CONTEXT_ITEM_COUNT_BUDGET + 3)
    ]
    captured_prompt = ""

    async def fake_llm(messages, **_kwargs):
        nonlocal captured_prompt
        captured_prompt = messages[-1]["content"]
        return ResearchSubQueryPlan(queries=["导数定义 几何意义", "导数定义 例题"])

    queries = await generate_sub_queries(
        "导数定义",
        context=original_context,
        max_queries=2,
        llm_caller=fake_llm,
    )

    assert queries == ["导数定义 几何意义", "导数定义 例题"]
    assert len(original_context) == QUERY_CONTEXT_ITEM_COUNT_BUDGET + 3
    assert len(original_context[0]["detail"]) == QUERY_CONTEXT_ITEM_CHAR_BUDGET + 50
    assert "ctx-0" in captured_prompt
    assert f"ctx-{QUERY_CONTEXT_ITEM_COUNT_BUDGET + 2}" not in captured_prompt
    assert "x" * (QUERY_CONTEXT_ITEM_CHAR_BUDGET + 1) not in captured_prompt


@pytest.mark.anyio
async def test_complex_asset_request_protocol_is_processed_without_collision():
    request = build_asset_request_block(
        "mermaid",
        "graph LR\n    A[字长] -->|决定| B[单次处理数据量]",
    )
    markdown = f"## 核心关系图\n{request}\n## 后续正文\n"

    async def render(description: str) -> str:
        return f"```mermaid\n{description}\n```"

    replaced = await replace_asset_requests(markdown, kind="mermaid", renderer=render)

    assert ASSET_REQUEST_LANGUAGE not in replaced
    assert ASSET_REQUEST_BEGIN not in replaced
    assert ASSET_REQUEST_END not in replaced
    assert "```mermaid\ngraph LR" in replaced
    assert "A[字长] -->|决定| B[单次处理数据量]" in replaced
    assert "## 后续正文" in replaced


@pytest.mark.anyio
async def test_asset_request_protocol_tolerates_fenced_description():
    request = build_asset_request_block(
        "mermaid",
        "```mermaid\ngraph LR\nA[发现] --> B[验证]\n```",
    )
    markdown = f"## 图示\n{request}\n## 正文\n"

    async def render(description: str) -> str:
        return f"```mermaid\n{description}\n```"

    replaced = await replace_asset_requests(markdown, kind="mermaid", renderer=render)

    assert ASSET_REQUEST_LANGUAGE not in replaced
    assert ASSET_REQUEST_BEGIN not in replaced
    assert ASSET_REQUEST_END not in replaced
    assert "```mermaid\ngraph LR\nA[发现] --> B[验证]\n```" in replaced
    assert "## 正文" in replaced
