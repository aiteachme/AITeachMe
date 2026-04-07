"""Consistency checking and bounded repair for unified digest builds."""

from __future__ import annotations

import re

import structlog

from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.kg.state import KGDigestState
from app.workflows.digest.unified.models import (
    CoverageReport,
    DocGap,
    GraphGap,
    OrphanSignal,
    RepairBudget,
    RepairResult,
    TaxonomyDrift,
    TopicAnchorSnapshot,
)

logger = structlog.get_logger()

TOKEN_PATTERN = re.compile(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}")


async def check_consistency(doc_state: DocGenState, kg_state: KGDigestState) -> CoverageReport:
    """Check cross-lane coverage using shared chunk identities."""

    chapter_metadatas = doc_state.get("chapter_metadatas", [])
    topic_snapshot = kg_state.get("topic_anchor_snapshot") or TopicAnchorSnapshot()

    report = CoverageReport(
        doc_over_graph_gaps=_detect_doc_over_graph_gaps(chapter_metadatas, topic_snapshot),
        graph_over_doc_gaps=_detect_graph_over_doc_gaps(chapter_metadatas, topic_snapshot),
        orphan_signals=_detect_orphan_signals(chapter_metadatas, topic_snapshot),
        taxonomy_drifts=_detect_taxonomy_drifts(chapter_metadatas, topic_snapshot),
    )
    logger.info(
        "unified_consistency_completed",
        doc_gap_count=len(report.doc_over_graph_gaps),
        graph_gap_count=len(report.graph_over_doc_gaps),
        orphan_signal_count=len(report.orphan_signals),
        taxonomy_drift_count=len(report.taxonomy_drifts),
    )
    return report


async def bounded_repair(coverage_report: CoverageReport, budget: RepairBudget) -> RepairResult:
    """Select limited repair actions without creating unbounded loops."""

    repaired_chapters = [
        gap.chapter_index
        for gap in sorted(
            coverage_report.doc_over_graph_gaps,
            key=lambda item: item.severity,
            reverse=True,
        )[: budget.max_chapter_rewrites]
    ]
    remaining_budget = max(budget.max_llm_calls - len(repaired_chapters), 0)
    reextracted_chunks: list[str] = []
    for gap in coverage_report.graph_over_doc_gaps[: budget.max_chunk_reextracts]:
        if remaining_budget <= 0:
            break
        reextracted_chunks.extend(gap.chunk_uids[:1])
        remaining_budget -= 1

    result = RepairResult(
        repaired_chapters=repaired_chapters,
        reextracted_chunks=list(dict.fromkeys(reextracted_chunks)),
        llm_calls_used=len(repaired_chapters) + len(reextracted_chunks),
    )
    logger.info(
        "unified_bounded_repair_completed",
        repaired_chapter_count=len(result.repaired_chapters),
        reextracted_chunk_count=len(result.reextracted_chunks),
        llm_calls_used=result.llm_calls_used,
    )
    return result


def _detect_doc_over_graph_gaps(
    chapter_metadatas: list[dict],
    topic_snapshot: TopicAnchorSnapshot,
) -> list[DocGap]:
    gaps: list[DocGap] = []
    for chapter in chapter_metadatas:
        chapter_chunk_uids = set(chapter.get("chunk_uids", []))
        overlapping_anchors = [
            anchor
            for anchor in topic_snapshot.anchors
            if chapter_chunk_uids & set(anchor.chunk_uids)
        ]
        if overlapping_anchors:
            continue

        terms = _collect_chapter_terms(chapter)
        gaps.append(
            DocGap(
                chapter_index=int(chapter.get("chapter_index", 0)),
                chapter_title=str(chapter.get("title", "")),
                missing_terms=terms[:6],
                severity=1.0 if chapter_chunk_uids else 0.5,
            )
        )
    return gaps


def _detect_graph_over_doc_gaps(
    chapter_metadatas: list[dict],
    topic_snapshot: TopicAnchorSnapshot,
) -> list[GraphGap]:
    chapter_chunk_uid_sets = [set(chapter.get("chunk_uids", [])) for chapter in chapter_metadatas]
    gaps: list[GraphGap] = []
    for anchor in topic_snapshot.anchors:
        anchor_chunk_uids = set(anchor.chunk_uids)
        covered = any(anchor_chunk_uids & chapter_chunk_uid_set for chapter_chunk_uid_set in chapter_chunk_uid_sets)
        if covered:
            continue
        gaps.append(
            GraphGap(
                node_name=anchor.topic_name,
                node_type=anchor.node_type,
                chunk_uids=anchor.chunk_uids,
                no_chapter_coverage=True,
            )
        )
    return gaps


def _detect_orphan_signals(
    chapter_metadatas: list[dict],
    topic_snapshot: TopicAnchorSnapshot,
) -> list[OrphanSignal]:
    orphan_signals: list[OrphanSignal] = []
    for chapter in chapter_metadatas:
        chunk_uids = set(chapter.get("chunk_uids", []))
        covered_anchor_count = sum(
            1
            for anchor in topic_snapshot.anchors
            if chunk_uids & set(anchor.chunk_uids)
        )
        if covered_anchor_count > 0:
            continue
        orphan_signals.append(
            OrphanSignal(
                chapter_index=int(chapter.get("chapter_index", 0)),
                chapter_title=str(chapter.get("title", "")),
                orphan_type="chapter_without_anchor",
                orphan_count=max(len(chunk_uids), 1),
            )
        )
    return orphan_signals


def _detect_taxonomy_drifts(
    chapter_metadatas: list[dict],
    topic_snapshot: TopicAnchorSnapshot,
) -> list[TaxonomyDrift]:
    drifts: list[TaxonomyDrift] = []
    for chapter in chapter_metadatas:
        chapter_chunk_uids = set(chapter.get("chunk_uids", []))
        chapter_terms = set(_collect_chapter_terms(chapter))
        for anchor in topic_snapshot.anchors:
            anchor_chunk_uids = set(anchor.chunk_uids)
            if not chapter_chunk_uids or not (chapter_chunk_uids & anchor_chunk_uids):
                continue
            anchor_terms = set(_tokenize(anchor.topic_name))
            overlap = chapter_terms & anchor_terms
            if overlap:
                continue
            union_count = len(chapter_terms | anchor_terms) or 1
            drifts.append(
                TaxonomyDrift(
                    chunk_uids=sorted(chapter_chunk_uids & anchor_chunk_uids),
                    doc_name=str(chapter.get("title", "")),
                    graph_name=anchor.topic_name,
                    semantic_distance=1.0 - (len(overlap) / union_count),
                )
            )
    return drifts


def _collect_chapter_terms(chapter: dict) -> list[str]:
    raw_terms = [
        str(chapter.get("title", "")),
        *[str(term) for term in chapter.get("section_titles", [])],
        *[str(tag) for tag in chapter.get("tags", [])],
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for token in _tokenize(" ".join(raw_terms)):
        lowered = token.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(token)
    return deduped


def _tokenize(text: str) -> list[str]:
    return [match.group(0) for match in TOKEN_PATTERN.finditer(text)]

