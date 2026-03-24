"""Consistency checking and bounded repair."""

from __future__ import annotations

import structlog
from pydantic import BaseModel

from app.workflows.digest.build.models import CoverageReport, DocGap, GraphGap
from app.workflows.digest.state import DocGenState, KGDigestState

logger = structlog.get_logger()


class RepairBudget(BaseModel):
    """修复预算上限"""

    max_chapter_rewrites: int = 2  # 最多重写 2 个章节
    max_chunk_reextracts: int = 4  # 最多重抽 4 个 chunk
    max_llm_calls: int = 5  # 最多额外 5 次 LLM 调用


class RepairResult(BaseModel):
    """修复结果"""

    repaired_chapters: list[int] = []
    reextracted_chunks: list[str] = []
    llm_calls_used: int = 0


async def check_consistency(
    doc_result: DocGenState,
    kg_result: KGDigestState,
) -> CoverageReport:
    """检查文档-图谱一致性

    Args:
        doc_result: 文档构建结果
        kg_result: 图谱构建结果

    Returns:
        CoverageReport: 覆盖缺口报告
    """

    logger.info("consistency_check_started")

    # 1. 检测 doc over graph gaps
    doc_gaps = await _detect_doc_over_graph_gaps(doc_result, kg_result)

    # 2. 检测 graph over doc gaps
    graph_gaps = await _detect_graph_over_doc_gaps(doc_result, kg_result)

    # 3. 检测孤儿信号
    orphan_signals = []  # TODO: 实现

    # 4. 检测分类漂移
    taxonomy_drifts = []  # TODO: 实现

    report = CoverageReport(
        doc_over_graph_gaps=doc_gaps,
        graph_over_doc_gaps=graph_gaps,
        orphan_signals=orphan_signals,
        taxonomy_drifts=taxonomy_drifts,
    )

    logger.info(
        "consistency_check_completed",
        doc_gaps=len(doc_gaps),
        graph_gaps=len(graph_gaps),
        total_gaps=report.gap_count(),
    )

    return report


async def _detect_doc_over_graph_gaps(
    doc_result: DocGenState,
    kg_result: KGDigestState,
) -> list[DocGap]:
    """检测文档覆盖缺口（文档讲了，图谱没有）

    Args:
        doc_result: 文档构建结果
        kg_result: 图谱构建结果

    Returns:
        list[DocGap]: 缺口列表
    """

    # TODO: 实现实际检测逻辑
    # 这里需要：
    # 1. 提取每章的高频词
    # 2. 检查这些词在图谱中的覆盖率
    # 3. 如果覆盖率低于阈值，标记为 gap

    return []


async def _detect_graph_over_doc_gaps(
    doc_result: DocGenState,
    kg_result: KGDigestState,
) -> list[GraphGap]:
    """检测图谱覆盖缺口（图谱有了，文档没讲）

    Args:
        doc_result: 文档构建结果
        kg_result: 图谱构建结果

    Returns:
        list[GraphGap]: 缺口列表
    """

    # TODO: 实现实际检测逻辑
    # 这里需要：
    # 1. 获取高置信度的图谱节点
    # 2. 检查这些节点相关的 chunk 是否被章节覆盖
    # 3. 如果没有覆盖，标记为 gap

    return []


async def bounded_repair(
    coverage_report: CoverageReport,
    budget: RepairBudget,
) -> RepairResult:
    """有预算上限的局部修复

    Args:
        coverage_report: 覆盖缺口报告
        budget: 修复预算

    Returns:
        RepairResult: 修复结果
    """

    logger.info("bounded_repair_started", gap_count=coverage_report.gap_count())

    result = RepairResult()

    # 1. 修复 doc gaps（优先级：severity 高的）
    sorted_doc_gaps = sorted(
        coverage_report.doc_over_graph_gaps,
        key=lambda g: g.severity,
        reverse=True,
    )

    for gap in sorted_doc_gaps[: budget.max_chapter_rewrites]:
        if result.llm_calls_used >= budget.max_llm_calls:
            break

        # TODO: 实现章节重审逻辑
        logger.info("repair_chapter", chapter_index=gap.chapter_index, missing_terms=gap.missing_terms)
        result.repaired_chapters.append(gap.chapter_index)
        result.llm_calls_used += 1

    # 2. 修复 graph gaps（重抽相关 chunk）
    for gap in coverage_report.graph_over_doc_gaps[: budget.max_chunk_reextracts]:
        if result.llm_calls_used >= budget.max_llm_calls:
            break

        # TODO: 实现 chunk 重抽逻辑
        logger.info("reextract_chunks", node_id=gap.node_id, chunk_uids=gap.chunk_uids)
        result.reextracted_chunks.extend(gap.chunk_uids)
        result.llm_calls_used += 1

    logger.info(
        "bounded_repair_completed",
        repaired_chapters=len(result.repaired_chapters),
        reextracted_chunks=len(result.reextracted_chunks),
        llm_calls_used=result.llm_calls_used,
    )

    return result
