"""Incremental knowledge-doc to knowledge-graph synchronization."""

from __future__ import annotations

import asyncio
import contextvars
import json
from dataclasses import dataclass, replace
from time import perf_counter
import threading

import structlog
from sqlmodel import Session, select

from app.models.knowledge_graph_sync import KnowledgeGraphSourceRef, KnowledgeGraphSyncRun
from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.knowledge_taxonomy import (
    normalize_knowledge_unit_type,
    normalize_relation_type,
    validate_relation_direction,
)
from app.repositories import knowledge_relation_repo, knowledge_unit_repo
from app.shared.infra.embedding import aembed_texts
from app.shared.infra.search.api import search_knowledge
from app.utils.knowledge_helpers import normalize_name
from app.utils.time import utcnow
from app.workflows.digest.common.markdown_knowledge_anchors import build_knowledge_unit_anchor
from app.workflows.digest.common.markdown_knowledge_anchors import (
    MarkdownKnowledgeUnit,
    MarkdownSectionChunk,
    extract_markdown_chapter_chunks,
    extract_markdown_section_chunks,
    validate_knowledge_unit_anchors,
)
from app.workflows.digest.kg_doc_sync.lib.extraction import (
    CandidateExtractionDiagnostics,
    ChunkExtractionResult,
    docs_section_llm_max_content_chars,
    docs_section_llm_timeout_s,
    extract_candidates,
    extract_candidates_with_diagnostics,
)
from app.workflows.digest.kg_doc_sync.lib.candidate_quality import (
    filter_docs_candidate_result,
    is_low_quality_docs_unit_name,
)
from app.workflows.digest.kg_doc_sync.lib.models import (
    ChapterSourceContext,
    KnowledgeSyncExtractionPayload,
    KnowledgeSyncReport,
    KnowledgeSyncRunContext,
    MarkdownExtractedEdge,
    PendingMarkdownExtractedEdge,
    SectionExtractionContext,
    SectionExtractionPayload,
)
from app.workflows.digest.kg_doc_sync.lib.ontology import default_relation_for_unit_type
from app.workflows.digest.kg_doc_sync.lib.sync_runs import (
    create_sync_run,
    finish_sync_run,
    get_sync_run_or_raise,
    mark_knowledge_graph_sync_run_failed,
    sync_run_metrics,
)

_ANCHOR_ALIAS_SOURCE = "markdown_anchor"
_SYNC_EDGE_MARKER = "markdown_anchor_sync"
_RAG_DEDUP_TOP_K = 6
_RAG_DEDUP_SIMILARITY_THRESHOLD = 0.82
_DEFAULT_DOCS_SYNC_CHAPTER_CONCURRENCY_LIMIT = 10
_DOCS_SYNC_MAX_PARALLEL_EXTRACTIONS = 10
_DOCS_SYNC_SPLIT_MIN_CHILD_SECTIONS = 2
_DOCS_SYNC_SPLIT_MIN_CHAPTER_CHARS = 9000
_DEFAULT_DOCS_SYNC_CHAPTER_MAX_RETRIES = 2
_DEFAULT_DOCS_SYNC_CHAPTER_RETRY_DELAY_S = 0.4
_DOCS_SYNC_CHAPTER_CONCURRENCY_LIMIT = _DEFAULT_DOCS_SYNC_CHAPTER_CONCURRENCY_LIMIT
_DOCS_SYNC_CHAPTER_MAX_RETRIES = _DEFAULT_DOCS_SYNC_CHAPTER_MAX_RETRIES
_DOCS_SYNC_CHAPTER_RETRY_DELAY_S = _DEFAULT_DOCS_SYNC_CHAPTER_RETRY_DELAY_S
_DOCS_SYNC_SECTION_CONCURRENCY_LIMIT = _DOCS_SYNC_CHAPTER_CONCURRENCY_LIMIT
_DOCS_SYNC_SECTION_MAX_RETRIES = _DOCS_SYNC_CHAPTER_MAX_RETRIES
_DOCS_SYNC_SECTION_RETRY_DELAY_S = _DOCS_SYNC_CHAPTER_RETRY_DELAY_S
_DEFAULT_EXTRACT_CANDIDATES = extract_candidates
_ASYNC_BRIDGE_LOCK = threading.Lock()
_ASYNC_BRIDGE_READY = threading.Event()
_ASYNC_BRIDGE_LOOP: asyncio.AbstractEventLoop | None = None
_ASYNC_BRIDGE_THREAD: threading.Thread | None = None

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class _ExtractionTask:
    task_index: int
    source_chapter_index: int
    chunk: MarkdownSectionChunk
    chapter_context: ChapterSourceContext
    source_kind: str


def _as_mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return []


def _safe_int(value: object, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_int_list(value: object) -> list[int]:
    cleaned: list[int] = []
    seen: set[int] = set()
    for item in _as_list(value) if isinstance(value, (list, tuple)) else ([] if value is None else [value]):
        parsed = _safe_int(item)
        if parsed <= 0 or parsed in seen:
            continue
        seen.add(parsed)
        cleaned.append(parsed)
    return cleaned


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _source_quote(text: str, *, max_chars: int = 500) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if len(cleaned) > max_chars:
        return cleaned[: max(0, max_chars - 3)].rstrip() + "..."
    return cleaned


def _structured_context_payload(value: dict[str, object] | None) -> dict[str, object]:
    return dict(value or {})


def _chapter_context_lookup(structured_context: dict[str, object]) -> dict[int, ChapterSourceContext]:
    lookup: dict[int, ChapterSourceContext] = {}
    for item in _as_list(structured_context.get("chapters")):
        payload = _as_mapping(item)
        chapter_index = _safe_int(payload.get("chapter_index"))
        if chapter_index <= 0:
            continue
        lookup[chapter_index] = ChapterSourceContext(
            knowledge_document_id=(_safe_int(payload.get("knowledge_document_id")) or None),
            chapter_index=chapter_index,
            title=str(payload.get("title") or "").strip(),
            summary=str(payload.get("summary") or "").strip(),
            source_file_ids=_clean_int_list(payload.get("source_file_ids")),
        )
    return lookup


def _chapter_context_for_index(
    chapter_contexts: dict[int, ChapterSourceContext],
    chapter_index: int,
) -> ChapterSourceContext:
    return chapter_contexts.get(chapter_index) or ChapterSourceContext(chapter_index=chapter_index)


def _document_backbone_payload(structured_context: dict[str, object]) -> dict[str, object]:
    manifest = _as_mapping(structured_context.get("docgen_manifest"))
    backbone = _as_mapping(manifest.get("document_backbone_snapshot"))
    if backbone:
        return backbone
    summary = _as_mapping(structured_context.get("document_summary_json"))
    return _as_mapping(summary.get("document_backbone"))


def sync_markdown_knowledge_graph(
    session: Session,
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None = None,
    enable_rag_dedup: bool = False,
    subject_context: str | None = None,
    structured_context: dict[str, object] | None = None,
    build_session_id: str | None = None,
) -> KnowledgeSyncReport:
    """Synchronize knowledge units and knowledge images from Markdown into the graph."""

    started_at = perf_counter()
    run_context = initialize_knowledge_graph_sync_run(
        session,
        subject=subject,
        markdown=markdown,
        build_revision_no=build_revision_no,
        structured_context=structured_context,
        build_session_id=build_session_id,
        started_at=started_at,
    )
    try:
        payload = extract_knowledge_graph_items(
            markdown=markdown,
            subject_context=subject_context,
            run_context=run_context,
        )
    except Exception as exc:
        mark_knowledge_graph_sync_run_failed(
            session,
            sync_run_id=run_context.sync_run_id,
            error_message=str(exc),
        )
        session.flush()
        raise
    return persist_knowledge_graph_items(
        session,
        run_context=run_context,
        payload=payload,
        enable_rag_dedup=enable_rag_dedup,
    )


def initialize_knowledge_graph_sync_run(
    session: Session,
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None = None,
    structured_context: dict[str, object] | None = None,
    build_session_id: str | None = None,
    started_at: float | None = None,
) -> KnowledgeSyncRunContext:
    """Validate Markdown anchors and create a running sync-run row."""

    validation = validate_knowledge_unit_anchors(markdown)
    if not validation.ok:
        raise ValueError(
            "invalid Markdown KnowledgeUnit anchors: "
            f"duplicates={validation.duplicate_anchors}, invalid={validation.invalid_anchors}"
        )

    normalized_context = _structured_context_payload(structured_context)
    revision_no = build_revision_no or _next_revision_no(session, subject)
    doc_version_no = _safe_int(normalized_context.get("doc_version_no"))
    sync_run = create_sync_run(
        session,
        subject=subject,
        build_session_id=build_session_id,
        doc_version_no=doc_version_no,
        graph_revision_no=revision_no,
    )
    if sync_run.id is None:
        raise RuntimeError("knowledge_graph_sync_run_id_missing")
    return KnowledgeSyncRunContext(
        subject=subject,
        build_revision_no=revision_no,
        sync_run_id=sync_run.id,
        doc_version_no=doc_version_no,
        structured_context=normalized_context,
        started_at=started_at or perf_counter(),
    )


def extract_knowledge_graph_items(
    *,
    markdown: str,
    subject_context: str | None,
    run_context: KnowledgeSyncRunContext,
) -> KnowledgeSyncExtractionPayload:
    """Extract units and edges without writing graph rows."""

    units, extracted_edges, diagnostics_totals = _extract_markdown_graph_items(
        markdown,
        subject_context=subject_context,
        structured_context=run_context.structured_context,
    )
    return KnowledgeSyncExtractionPayload(
        units=units,
        extracted_edges=extracted_edges,
        diagnostics_totals=diagnostics_totals,
    )


def persist_knowledge_graph_items(
    session: Session,
    *,
    run_context: KnowledgeSyncRunContext,
    payload: KnowledgeSyncExtractionPayload,
    enable_rag_dedup: bool = False,
) -> KnowledgeSyncReport:
    """Persist extracted graph items and finish the sync run."""

    units = payload.units
    extracted_edges = payload.extracted_edges
    diagnostics_totals = payload.diagnostics_totals
    sync_run = get_sync_run_or_raise(session, run_context.sync_run_id)
    report = KnowledgeSyncReport(
        subject=run_context.subject,
        build_revision_no=run_context.build_revision_no,
        sync_run_id=sync_run.id,
        doc_version_no=run_context.doc_version_no,
        synced_unit_keys=[item.anchor for item in units],
        section_count=int(diagnostics_totals.get("section_count", 0) or 0),
        chapter_count=int(diagnostics_totals.get("chapter_count", 0) or 0),
        chapter_split_count=int(diagnostics_totals.get("chapter_split_count", 0) or 0),
        chapter_task_count=int(diagnostics_totals.get("chapter_task_count", 0) or 0),
        subsection_task_count=int(diagnostics_totals.get("subsection_task_count", 0) or 0),
        successful_section_count=int(diagnostics_totals.get("successful_section_count", 0) or 0),
        failed_section_count=int(diagnostics_totals.get("failed_section_count", 0) or 0),
        llm_section_count=int(diagnostics_totals.get("llm_section_count", 0) or 0),
        markdown_short_circuit_section_count=int(diagnostics_totals.get("markdown_short_circuit_section_count", 0) or 0),
        llm_error_count=int(diagnostics_totals.get("llm_error_count", 0) or 0),
        empty_llm_result_count=int(diagnostics_totals.get("empty_llm_result_count", 0) or 0),
        empty_repair_attempt_count=int(diagnostics_totals.get("empty_repair_attempt_count", 0) or 0),
        empty_repair_success_count=int(diagnostics_totals.get("empty_repair_success_count", 0) or 0),
        total_extracted_node_count=int(diagnostics_totals.get("total_extracted_node_count", 0) or 0),
        total_extracted_edge_count=int(diagnostics_totals.get("total_extracted_edge_count", 0) or 0),
        backbone_unit_count=int(diagnostics_totals.get("backbone_unit_count", 0) or 0),
        backbone_edge_count=int(diagnostics_totals.get("backbone_edge_count", 0) or 0),
        stable_anchor_count=len({item.anchor for item in units if item.anchor}),
    )
    report.knowledge_image_count = sum(len(item.knowledge_images) for item in units)

    try:
        _apply_extracted_graph_items(
            session,
            subject=run_context.subject,
            units=units,
            extracted_edges=extracted_edges,
            sync_run=sync_run,
            build_revision_no=run_context.build_revision_no,
            enable_rag_dedup=enable_rag_dedup,
            report=report,
        )
    except Exception as exc:
        finish_sync_run(
            session,
            sync_run,
            status="failed",
            metrics=sync_run_metrics(report),
            error_message=str(exc),
        )
        session.flush()
        raise
    report.elapsed_ms = int((perf_counter() - run_context.started_at) * 1000)
    finish_sync_run(session, sync_run, status="completed", metrics=sync_run_metrics(report))
    session.commit()
    logger.info(
        "knowledge_docs_sync_complete",
        subject=run_context.subject,
        build_revision_no=run_context.build_revision_no,
        sync_run_id=sync_run.id,
        doc_version_no=report.doc_version_no,
        chapter_count=report.chapter_count,
        section_count=report.section_count,
        llm_section_count=report.llm_section_count,
        unit_change_count=report.unit_change_count,
        edge_change_count=report.edge_change_count,
        source_ref_count=report.source_ref_count,
        backbone_unit_count=report.backbone_unit_count,
        backbone_edge_count=report.backbone_edge_count,
        elapsed_ms=report.elapsed_ms,
    )
    return report


def _apply_extracted_graph_items(
    session: Session,
    *,
    subject: str,
    units: list[MarkdownKnowledgeUnit],
    extracted_edges: list[MarkdownExtractedEdge],
    sync_run: KnowledgeGraphSyncRun,
    build_revision_no: int,
    enable_rag_dedup: bool,
    report: KnowledgeSyncReport,
) -> None:
    unit_by_anchor: dict[str, KnowledgeUnit] = {}
    for item in units:
        unit, created = _upsert_unit(
            session,
            subject=subject,
            item=item,
            build_revision_no=build_revision_no,
            enable_rag_dedup=enable_rag_dedup,
        )
        if unit.id is None:
            continue
        unit_by_anchor[item.anchor] = unit
        if created:
            report.created_unit_ids.append(unit.id)
        else:
            report.updated_unit_ids.append(unit.id)
        if _create_source_ref_for_unit(session, sync_run=sync_run, subject=subject, unit=unit, item=item):
            report.source_ref_count += 1

    seen_edge_keys: set[tuple[int, int, str]] = set()
    for extracted_edge in extracted_edges:
        source = unit_by_anchor.get(extracted_edge.source_anchor)
        target = unit_by_anchor.get(extracted_edge.target_anchor)
        if source is None or target is None or source.id is None or target.id is None:
            continue
        if not validate_relation_direction(
            edge_type=extracted_edge.edge_type,
            source_type=source.knowledge_unit_type,
            target_type=target.knowledge_unit_type,
        ):
            logger.warning(
                "knowledge_docs_sync_edge_skipped_invalid_direction",
                edge_type=extracted_edge.edge_type,
                source_type=source.knowledge_unit_type,
                target_type=target.knowledge_unit_type,
                source_anchor=extracted_edge.source_anchor,
                target_anchor=extracted_edge.target_anchor,
            )
            continue
        edge, created = _upsert_edge(
            session,
            subject=subject,
            source_node_id=source.id,
            target_node_id=target.id,
            edge_type=extracted_edge.edge_type,
            description=extracted_edge.description,
            build_revision_no=build_revision_no,
        )
        if edge.id is not None:
            seen_edge_keys.add((edge.source_node_id, edge.target_node_id, edge.edge_type))
            (report.created_edge_ids if created else report.updated_edge_ids).append(edge.id)
            if _create_source_ref_for_edge(
                session,
                sync_run=sync_run,
                subject=subject,
                edge=edge,
                extracted_edge=extracted_edge,
            ):
                report.source_ref_count += 1

    if report.failed_section_count > 0:
        logger.warning(
            "knowledge_docs_sync_deprecation_skipped_after_partial_extraction",
            subject=subject,
            sync_run_id=sync_run.id,
            failed_section_count=report.failed_section_count,
            synced_unit_count=len(report.synced_unit_keys),
            seen_edge_count=len(seen_edge_keys),
        )
        return

    report.deprecated_unit_ids.extend(
        _deprecate_removed_anchor_units(
            session,
            subject=subject,
            active_anchors=set(report.synced_unit_keys),
            build_revision_no=build_revision_no,
        )
    )
    report.deprecated_edge_ids.extend(
        _deprecate_removed_sync_edges(
            session,
            subject=subject,
            seen_edge_keys=seen_edge_keys,
            build_revision_no=build_revision_no,
        )
    )


def _next_revision_no(session: Session, subject: str) -> int:
    units = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.subject == subject)).all()
    edges = session.exec(select(KnowledgeEdge).where(KnowledgeEdge.subject == subject)).all()
    current = max(
        [0]
        + [int(item.build_revision_no or 0) for item in units]
        + [int(item.build_revision_no or 0) for item in edges]
    )
    return current + 1


def _create_source_ref_for_unit(
    session: Session,
    *,
    sync_run: KnowledgeGraphSyncRun,
    subject: str,
    unit: KnowledgeUnit,
    item: MarkdownKnowledgeUnit,
) -> bool:
    if unit.id is None:
        return False
    source_ref = KnowledgeGraphSourceRef(
        subject=subject,
        entity_type="unit",
        entity_id=unit.id,
        sync_run_id=sync_run.id,
        knowledge_document_id=item.knowledge_document_id,
        chapter_index=int(item.chapter_index or 0),
        anchor=item.anchor,
        source_kind=item.source_kind,
        source_file_ids_json=_json_dumps(_clean_int_list(item.source_file_ids)),
        quote_text=_source_quote(item.quote_text or item.summary or item.body_markdown),
        confidence=1.0,
    )
    session.add(source_ref)
    session.flush()
    return True


def _create_source_ref_for_edge(
    session: Session,
    *,
    sync_run: KnowledgeGraphSyncRun,
    subject: str,
    edge: KnowledgeEdge,
    extracted_edge: MarkdownExtractedEdge,
) -> bool:
    if edge.id is None:
        return False
    source_ref = KnowledgeGraphSourceRef(
        subject=subject,
        entity_type="edge",
        entity_id=edge.id,
        sync_run_id=sync_run.id,
        knowledge_document_id=extracted_edge.knowledge_document_id,
        chapter_index=int(extracted_edge.chapter_index or 0),
        anchor=f"{extracted_edge.source_anchor}->{extracted_edge.target_anchor}",
        source_kind=extracted_edge.source_kind,
        source_file_ids_json=_json_dumps(_clean_int_list(extracted_edge.source_file_ids)),
        quote_text=_source_quote(extracted_edge.quote_text or extracted_edge.description),
        confidence=1.0,
    )
    session.add(source_ref)
    session.flush()
    return True


def _empty_extraction_diagnostics() -> dict[str, int]:
    return {
        "chapter_count": 0,
        "section_count": 0,
        "chapter_split_count": 0,
        "chapter_task_count": 0,
        "subsection_task_count": 0,
        "successful_section_count": 0,
        "failed_section_count": 0,
        "llm_section_count": 0,
        "markdown_short_circuit_section_count": 0,
        "llm_error_count": 0,
        "empty_llm_result_count": 0,
        "empty_repair_attempt_count": 0,
        "empty_repair_success_count": 0,
        "total_extracted_node_count": 0,
        "total_extracted_edge_count": 0,
        "backbone_unit_count": 0,
        "backbone_edge_count": 0,
    }


def _chapter_concurrency_limit() -> int:
    configured = _DOCS_SYNC_CHAPTER_CONCURRENCY_LIMIT
    if configured == _DEFAULT_DOCS_SYNC_CHAPTER_CONCURRENCY_LIMIT:
        configured = _DOCS_SYNC_SECTION_CONCURRENCY_LIMIT
    return max(1, min(_DOCS_SYNC_MAX_PARALLEL_EXTRACTIONS, int(configured)))


def _effective_concurrency_limit(task_count: int) -> int:
    return max(1, min(max(1, task_count), _chapter_concurrency_limit()))


def _chapter_max_retries() -> int:
    configured = _DOCS_SYNC_CHAPTER_MAX_RETRIES
    if configured == _DEFAULT_DOCS_SYNC_CHAPTER_MAX_RETRIES:
        configured = _DOCS_SYNC_SECTION_MAX_RETRIES
    return max(1, int(configured))


def _chapter_retry_delay_s() -> float:
    configured = _DOCS_SYNC_CHAPTER_RETRY_DELAY_S
    if configured == _DEFAULT_DOCS_SYNC_CHAPTER_RETRY_DELAY_S:
        configured = _DOCS_SYNC_SECTION_RETRY_DELAY_S
    return max(0.0, float(configured))


def graph_extraction_parallelism() -> dict[str, int | float]:
    """Return the effective internal fan-out settings for docs-sync extraction."""

    return {
        "chapter_concurrency_limit": _chapter_concurrency_limit(),
        "max_parallel_extractions": _DOCS_SYNC_MAX_PARALLEL_EXTRACTIONS,
        "chapter_max_retries": _chapter_max_retries(),
        "chapter_retry_delay_s": _chapter_retry_delay_s(),
        "split_min_child_sections": _DOCS_SYNC_SPLIT_MIN_CHILD_SECTIONS,
        "split_min_chapter_chars": _DOCS_SYNC_SPLIT_MIN_CHAPTER_CHARS,
        "section_llm_timeout_s": docs_section_llm_timeout_s(),
        "section_llm_max_content_chars": docs_section_llm_max_content_chars(),
    }


def _is_extractable_section_chunk(chunk: MarkdownSectionChunk, *, parent_title: str) -> bool:
    body = str(chunk.body_markdown or "").strip()
    if not body:
        return False
    if normalize_name(chunk.title) == normalize_name(parent_title) and len(body) < 400:
        return False
    return True


def _chapter_child_chunks(chapter: MarkdownSectionChunk) -> list[MarkdownSectionChunk]:
    chunks = extract_markdown_section_chunks(chapter.body_markdown)
    if len(chunks) <= 1:
        return []
    parent_level = min(chunk.heading_level for chunk in chunks)
    children = [
        chunk
        for chunk in chunks
        if chunk.heading_level > parent_level and _is_extractable_section_chunk(chunk, parent_title=chapter.title)
    ]
    return children


def _should_split_chapter(chapter: MarkdownSectionChunk, child_chunks: list[MarkdownSectionChunk]) -> bool:
    return (
        len(child_chunks) >= _DOCS_SYNC_SPLIT_MIN_CHILD_SECTIONS
        and len(chapter.body_markdown or "") >= _DOCS_SYNC_SPLIT_MIN_CHAPTER_CHARS
    )


def _build_extraction_tasks(
    chapters: list[MarkdownSectionChunk],
    chapter_contexts: dict[int, ChapterSourceContext],
) -> tuple[list[_ExtractionTask], dict[str, int]]:
    tasks: list[_ExtractionTask] = []
    metrics = {
        "chapter_split_count": 0,
        "chapter_task_count": 0,
        "subsection_task_count": 0,
    }
    for source_chapter_index, chapter in enumerate(chapters, start=1):
        chapter_context = _chapter_context_for_index(chapter_contexts, source_chapter_index)
        child_chunks = _chapter_child_chunks(chapter)
        if _should_split_chapter(chapter, child_chunks):
            metrics["chapter_split_count"] += 1
            for child_chunk in child_chunks:
                metrics["subsection_task_count"] += 1
                tasks.append(
                    _ExtractionTask(
                        task_index=len(tasks) + 1,
                        source_chapter_index=source_chapter_index,
                        chunk=child_chunk,
                        chapter_context=chapter_context,
                        source_kind="subsection",
                    )
                )
            continue

        metrics["chapter_task_count"] += 1
        tasks.append(
            _ExtractionTask(
                task_index=len(tasks) + 1,
                source_chapter_index=source_chapter_index,
                chunk=chapter,
                chapter_context=chapter_context,
                source_kind="chapter",
            )
        )
    return tasks, metrics


def _extract_markdown_graph_items(
    markdown: str,
    *,
    subject_context: str | None = None,
    structured_context: dict[str, object] | None = None,
) -> tuple[list[MarkdownKnowledgeUnit], list[MarkdownExtractedEdge], dict[str, int]]:
    chapters = extract_markdown_chapter_chunks(markdown)
    sections = extract_markdown_section_chunks(markdown)
    if not chapters:
        return [], [], _empty_extraction_diagnostics()
    structured_context = _structured_context_payload(structured_context)
    chapter_contexts = _chapter_context_lookup(structured_context)
    extraction_tasks, task_metrics = _build_extraction_tasks(chapters, chapter_contexts)

    async def _extract_all_chapters() -> list[SectionExtractionPayload]:
        semaphore = asyncio.Semaphore(_effective_concurrency_limit(len(extraction_tasks)))

        async def _extract_with_queue(task: _ExtractionTask) -> SectionExtractionPayload:
            async with semaphore:
                try:
                    return await _extract_chapter_with_retries(
                        task.task_index,
                        task.chunk,
                        subject_context=subject_context or "",
                        chapter_context=task.chapter_context,
                        source_chapter_index=task.source_chapter_index,
                        source_kind=task.source_kind,
                    )
                except Exception as exc:
                    logger.warning(
                        "knowledge_docs_sync_section_extraction_failed",
                        task_index=task.task_index,
                        chunk_title=task.chunk.title,
                        header_path=task.chunk.header_path,
                        source_chapter_index=task.source_chapter_index,
                        source_kind=task.source_kind,
                        error_type=type(exc).__name__,
                    )
                    return _empty_failed_section_payload(task, exc)

        return await asyncio.gather(*[_extract_with_queue(task) for task in extraction_tasks])

    results = _run_async(_extract_all_chapters()) or []
    units: list[MarkdownKnowledgeUnit] = []
    pending_edges: list[PendingMarkdownExtractedEdge] = []
    candidate_id_to_anchor: dict[str, str] = {}
    anchors_by_name: dict[str, list[str]] = {}
    anchors_by_normalized_name: dict[str, list[str]] = {}
    node_contexts_by_anchor: dict[str, dict[str, object]] = {}
    section_contexts: list[SectionExtractionContext] = []
    diagnostics_totals = _empty_extraction_diagnostics()
    diagnostics_totals["chapter_count"] = len(chapters)
    diagnostics_totals["section_count"] = len(extraction_tasks)
    diagnostics_totals.update(task_metrics)
    used_anchors: set[str] = set()

    for payload in results:
        payload = _make_payload_anchors_unique(payload, used_anchors)
        units.extend(payload.units)
        pending_edges.extend(payload.pending_edges)
        candidate_id_to_anchor.update(payload.candidate_id_to_anchor)
        node_contexts_by_anchor.update(payload.node_contexts_by_anchor)
        section_contexts.append(payload.section_context)
        for key in diagnostics_totals:
            diagnostics_totals[key] += int(payload.diagnostics.get(key, 0) or 0)
        for name, anchors in payload.anchors_by_name.items():
            bucket = anchors_by_name.setdefault(name, [])
            for anchor in anchors:
                if anchor not in bucket:
                    bucket.append(anchor)
        for normalized_name, anchors in payload.anchors_by_normalized_name.items():
            bucket = anchors_by_normalized_name.setdefault(normalized_name, [])
            for anchor in anchors:
                if anchor not in bucket:
                    bucket.append(anchor)

    backbone_units, backbone_edges = _build_backbone_graph_items(
        structured_context=structured_context,
        chapter_contexts=chapter_contexts,
        used_anchors=used_anchors,
        existing_normalized_names=set(anchors_by_normalized_name),
    )
    if backbone_units:
        units = [*backbone_units, *units]
        diagnostics_totals["backbone_unit_count"] = len(backbone_units)
        for unit in backbone_units:
            anchors_by_name.setdefault(unit.name, []).append(unit.anchor)
            normalized_name = normalize_name(unit.name)
            if normalized_name:
                anchors_by_normalized_name.setdefault(normalized_name, []).append(unit.anchor)
            node_contexts_by_anchor[unit.anchor] = {
                "name": unit.name,
                "knowledge_unit_type": unit.knowledge_unit_type,
                "taxonomy_hint": unit.name,
                "parent_entity_name": "",
                "section_index": int(unit.chapter_index or 0),
                "knowledge_document_id": unit.knowledge_document_id,
                "source_file_ids": list(unit.source_file_ids),
            }
    if backbone_edges:
        pending_edges.extend(backbone_edges)
        diagnostics_totals["backbone_edge_count"] = len(backbone_edges)

    pending_edges.extend(
        _build_structural_heading_edges(
            sections=sections,
            anchors_by_name=anchors_by_name,
            anchors_by_normalized_name=anchors_by_normalized_name,
        )
    )
    pending_edges.extend(
        _build_cross_section_semantic_edges(
            node_contexts_by_anchor=node_contexts_by_anchor,
            section_contexts=section_contexts,
            anchors_by_name=anchors_by_name,
            anchors_by_normalized_name=anchors_by_normalized_name,
        )
    )

    edges: list[MarkdownExtractedEdge] = []
    seen_edge_keys: set[tuple[str, str, str]] = set()
    for edge in pending_edges:
        source_anchor = _resolve_edge_anchor(
            candidate_id=edge.source_candidate_id,
            endpoint_name=edge.source_name,
            anchor_by_candidate_id=candidate_id_to_anchor,
            anchors_by_name=anchors_by_name,
            anchors_by_normalized_name=anchors_by_normalized_name,
        )
        target_anchor = _resolve_edge_anchor(
            candidate_id=edge.target_candidate_id,
            endpoint_name=edge.target_name,
            anchor_by_candidate_id=candidate_id_to_anchor,
            anchors_by_name=anchors_by_name,
            anchors_by_normalized_name=anchors_by_normalized_name,
        )
        if not source_anchor or not target_anchor or source_anchor == target_anchor:
            logger.info(
                "knowledge_graph_edge_skipped_unresolved_endpoint",
                edge_type=edge.edge_type,
                source_name=edge.source_name,
                target_name=edge.target_name,
                source_candidate_id=edge.source_candidate_id,
                target_candidate_id=edge.target_candidate_id,
                source_resolved=bool(source_anchor),
                target_resolved=bool(target_anchor),
            )
            continue
        key = (source_anchor, target_anchor, edge.edge_type)
        if key in seen_edge_keys:
            continue
        seen_edge_keys.add(key)
        edges.append(
            MarkdownExtractedEdge(
                source_anchor=source_anchor,
                target_anchor=target_anchor,
                edge_type=edge.edge_type,
                description=edge.description,
                source_kind=edge.source_kind,
                knowledge_document_id=edge.knowledge_document_id,
                chapter_index=edge.chapter_index,
                source_file_ids=list(edge.source_file_ids),
                quote_text=edge.quote_text,
            )
        )
    return units, edges, diagnostics_totals


def _empty_failed_section_payload(
    task: _ExtractionTask,
    exc: Exception,
) -> SectionExtractionPayload:
    del exc
    chapter_context = task.chapter_context
    resolved_chapter_index = chapter_context.chapter_index or task.source_chapter_index or task.task_index
    return SectionExtractionPayload(
        units=[],
        pending_edges=[],
        candidate_id_to_anchor={},
        anchors_by_name={},
        anchors_by_normalized_name={},
        node_contexts_by_anchor={},
        section_context=SectionExtractionContext(
            section_index=task.task_index,
            title=task.chunk.title,
            header_path=task.chunk.header_path,
            body_markdown=(task.chunk.body_markdown or "")[:8000],
            knowledge_document_id=chapter_context.knowledge_document_id,
            source_file_ids=list(chapter_context.source_file_ids),
        ),
        diagnostics={
            "section_count": 0,
            "successful_section_count": 0,
            "failed_section_count": 1,
            "llm_section_count": 1,
            "markdown_short_circuit_section_count": 0,
            "llm_error_count": 1,
            "empty_llm_result_count": 0,
            "empty_repair_attempt_count": 0,
            "empty_repair_success_count": 0,
            "total_extracted_node_count": 0,
            "total_extracted_edge_count": 0,
            "failed_chapter_index": resolved_chapter_index,
            "failed_task_index": task.task_index,
        },
    )


def _make_payload_anchors_unique(
    payload: SectionExtractionPayload,
    used_anchors: set[str],
) -> SectionExtractionPayload:
    remap: dict[str, str] = {}
    updated_units: list[MarkdownKnowledgeUnit] = []
    for unit in payload.units:
        old_anchor = unit.anchor
        if old_anchor and old_anchor not in used_anchors:
            used_anchors.add(old_anchor)
            new_anchor = old_anchor
        else:
            new_anchor = build_knowledge_unit_anchor(
                f"docgen ch{unit.chapter_index or payload.section_context.section_index} {unit.knowledge_unit_type} {unit.name}",
                used=used_anchors,
            )
        if old_anchor != new_anchor:
            remap[old_anchor] = new_anchor
            updated_units.append(replace(unit, anchor=new_anchor))
        else:
            updated_units.append(unit)

    if not remap:
        return payload

    def _remap_anchor(anchor: str) -> str:
        return remap.get(anchor, anchor)

    candidate_id_to_anchor = {
        candidate_id: _remap_anchor(anchor)
        for candidate_id, anchor in payload.candidate_id_to_anchor.items()
    }
    anchors_by_name = {
        name: [_remap_anchor(anchor) for anchor in anchors]
        for name, anchors in payload.anchors_by_name.items()
    }
    anchors_by_normalized_name = {
        name: [_remap_anchor(anchor) for anchor in anchors]
        for name, anchors in payload.anchors_by_normalized_name.items()
    }
    node_contexts_by_anchor = {
        _remap_anchor(anchor): context
        for anchor, context in payload.node_contexts_by_anchor.items()
    }
    section_context = payload.section_context
    if section_context.primary_anchor:
        section_context = replace(
            section_context,
            primary_anchor=_remap_anchor(section_context.primary_anchor),
        )

    return SectionExtractionPayload(
        units=updated_units,
        pending_edges=payload.pending_edges,
        candidate_id_to_anchor=candidate_id_to_anchor,
        anchors_by_name=anchors_by_name,
        anchors_by_normalized_name=anchors_by_normalized_name,
        node_contexts_by_anchor=node_contexts_by_anchor,
        section_context=section_context,
        diagnostics=payload.diagnostics,
    )


def _build_backbone_graph_items(
    *,
    structured_context: dict[str, object],
    chapter_contexts: dict[int, ChapterSourceContext],
    used_anchors: set[str],
    existing_normalized_names: set[str] | None = None,
) -> tuple[list[MarkdownKnowledgeUnit], list[PendingMarkdownExtractedEdge]]:
    backbone = _document_backbone_payload(structured_context)
    if not backbone:
        return [], []

    existing_normalized_names = set(existing_normalized_names or set())
    target_chapters_by_term: dict[str, list[int]] = {}
    units: list[MarkdownKnowledgeUnit] = []
    for item in _as_list(backbone.get("canonical_glossary")):
        payload = _as_mapping(item)
        term = str(payload.get("term") or "").strip()
        if not term:
            continue
        if is_low_quality_docs_unit_name(term, node_type="concept"):
            continue
        target_chapters = _clean_int_list(payload.get("target_chapters"))
        normalized_term = normalize_name(term)
        target_chapters_by_term[normalized_term] = target_chapters
        if normalized_term and normalized_term in existing_normalized_names:
            continue
        chapter_index = target_chapters[0] if target_chapters else 0
        chapter_context = chapter_contexts.get(chapter_index) or ChapterSourceContext(chapter_index=chapter_index)
        definition = str(payload.get("definition") or "").strip()
        anchor = build_knowledge_unit_anchor(
            f"docgen ch{chapter_index} concept {term}",
            used=used_anchors,
        )
        units.append(
            MarkdownKnowledgeUnit(
                anchor=anchor,
                name=term,
                knowledge_unit_type="concept",
                summary=definition or term,
                body_markdown=definition or term,
                knowledge_images=[],
                prerequisites=[],
                related=[],
                line_no=0,
                heading_level=1,
                source_kind="docgen_backbone",
                knowledge_document_id=chapter_context.knowledge_document_id,
                chapter_index=chapter_index,
                source_file_ids=list(chapter_context.source_file_ids),
                quote_text=definition or str(payload.get("source_hint") or ""),
            )
        )

    edges: list[PendingMarkdownExtractedEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for item in _as_list(backbone.get("concept_dependency_graph")):
        payload = _as_mapping(item)
        source_name = str(payload.get("from_concept") or "").strip()
        target_name = str(payload.get("to_concept") or "").strip()
        if not source_name or not target_name:
            continue
        if is_low_quality_docs_unit_name(source_name, node_type="concept") or is_low_quality_docs_unit_name(
            target_name,
            node_type="concept",
        ):
            continue
        raw_relation = str(payload.get("relation") or "").strip()
        edge_type = "prerequisite" if raw_relation == "chapter_order" else normalize_relation_type(raw_relation)
        key = (normalize_name(source_name), normalize_name(target_name), edge_type)
        if not key[0] or not key[1] or key[0] == key[1] or key in seen_edges:
            continue
        seen_edges.add(key)
        chapter_candidates = (
            target_chapters_by_term.get(normalize_name(target_name))
            or target_chapters_by_term.get(normalize_name(source_name))
            or []
        )
        chapter_index = chapter_candidates[0] if chapter_candidates else 0
        chapter_context = chapter_contexts.get(chapter_index) or ChapterSourceContext(chapter_index=chapter_index)
        reason = str(payload.get("reason") or "").strip()
        edges.append(
            PendingMarkdownExtractedEdge(
                source_candidate_id=None,
                target_candidate_id=None,
                source_name=source_name,
                target_name=target_name,
                edge_type=edge_type,
                description=reason or f"{source_name} 支撑 {target_name}。",
                source_kind="docgen_backbone",
                knowledge_document_id=chapter_context.knowledge_document_id,
                chapter_index=chapter_index,
                source_file_ids=list(chapter_context.source_file_ids),
                quote_text=reason,
            )
        )

    return units, edges


def _build_structural_heading_edges(
    *,
    sections,
    anchors_by_name: dict[str, list[str]],
    anchors_by_normalized_name: dict[str, list[str]],
) -> list[PendingMarkdownExtractedEdge]:
    pending_edges: list[PendingMarkdownExtractedEdge] = []
    seen: set[tuple[str, str, str]] = set()

    for section in sections:
        path_parts = [part.strip() for part in str(section.header_path or "").split(" > ") if part.strip()]
        if len(path_parts) < 2:
            continue

        parent_title = path_parts[-2]
        source_anchor = _resolve_edge_anchor(
            candidate_id=None,
            endpoint_name=section.title,
            anchor_by_candidate_id={},
            anchors_by_name=anchors_by_name,
            anchors_by_normalized_name=anchors_by_normalized_name,
        )
        parent_anchor = _resolve_edge_anchor(
            candidate_id=None,
            endpoint_name=parent_title,
            anchor_by_candidate_id={},
            anchors_by_name=anchors_by_name,
            anchors_by_normalized_name=anchors_by_normalized_name,
        )
        if not source_anchor or not parent_anchor or source_anchor == parent_anchor:
            continue

        key = (source_anchor, parent_anchor, "derivation")
        if key in seen:
            continue
        seen.add(key)
        pending_edges.append(
            PendingMarkdownExtractedEdge(
                source_candidate_id=None,
                target_candidate_id=None,
                source_name=section.title,
                target_name=parent_title,
                edge_type="derivation",
                description=f"{section.title} 属于主题 {parent_title}。",
                source_kind="structural_heading",
                quote_text=section.header_path,
            )
        )

    return pending_edges


def _infer_relation_from_section_text(*, body_markdown: str, primary_type: str) -> str | None:
    text = normalize_name(body_markdown or "")
    if not text:
        return None
    if any(token in text for token in ("前提", "基础", "先学", "先掌握", "依赖")):
        return "prerequisite"
    if any(token in text for token in ("由", "推出", "推得", "可得", "基于", "建立在")):
        return "derivation"
    if any(token in text for token in ("利用", "应用", "借助", "结合", "使用")):
        return "application"
    if any(token in text for token in ("区别", "对比", "比较", "不同于", "相反")):
        return "contrast"
    if any(token in text for token in ("类似", "相似", "同理")):
        return "similar"
    if normalize_knowledge_unit_type(primary_type) in {"example", "exercise"}:
        return "example_of"
    return None


def _build_cross_section_semantic_edges(
    *,
    node_contexts_by_anchor: dict[str, dict[str, object]],
    section_contexts: list[SectionExtractionContext],
    anchors_by_name: dict[str, list[str]],
    anchors_by_normalized_name: dict[str, list[str]],
) -> list[PendingMarkdownExtractedEdge]:
    pending_edges: list[PendingMarkdownExtractedEdge] = []
    seen: set[tuple[str, str, str]] = set()
    primary_contexts = [ctx for ctx in section_contexts if ctx.primary_anchor and ctx.primary_name]

    def _push_edge(
        source_name: str,
        target_name: str,
        edge_type: str,
        description: str,
        *,
        source_context: dict[str, object] | None = None,
    ) -> None:
        key = (normalize_name(source_name), normalize_name(target_name), edge_type)
        if not key[0] or not key[1] or key in seen or key[0] == key[1]:
            return
        seen.add(key)
        source_context = source_context or {}
        pending_edges.append(
            PendingMarkdownExtractedEdge(
                source_candidate_id=None,
                target_candidate_id=None,
                source_name=source_name,
                target_name=target_name,
                edge_type=edge_type,
                description=description,
                source_kind="cross_section_semantic",
                knowledge_document_id=(
                    _safe_int(source_context.get("knowledge_document_id")) or None
                ),
                chapter_index=_safe_int(source_context.get("section_index")),
                source_file_ids=_clean_int_list(source_context.get("source_file_ids")),
                quote_text=description,
            )
        )

    for source_anchor, context in node_contexts_by_anchor.items():
        source_name = str(context.get("name") or "").strip()
        source_type = str(context.get("knowledge_unit_type") or "concept").strip()
        source_section_index = int(context.get("section_index", -1) or -1)
        for hint_field in ("parent_entity_name", "taxonomy_hint"):
            hint_name = str(context.get(hint_field) or "").strip()
            if not hint_name or normalize_name(hint_name) == normalize_name(source_name):
                continue
            target_anchor = _resolve_edge_anchor(
                candidate_id=None,
                endpoint_name=hint_name,
                anchor_by_candidate_id={},
                anchors_by_name=anchors_by_name,
                anchors_by_normalized_name=anchors_by_normalized_name,
            )
            if not target_anchor or target_anchor == source_anchor:
                continue
            target_context = node_contexts_by_anchor.get(target_anchor, {})
            if int(target_context.get("section_index", -1) or -1) == source_section_index:
                continue
            _push_edge(
                source_name,
                str(target_context.get("name") or hint_name),
                default_relation_for_unit_type(source_type),
                f"{source_name} references {hint_name} across sections via {hint_field}.",
                source_context=context,
            )

    for context in primary_contexts:
        body_markdown = context.body_markdown or ""
        relation = _infer_relation_from_section_text(
            body_markdown=body_markdown,
            primary_type=context.primary_type,
        )
        if relation is None:
            continue
        body_text = normalize_name(body_markdown)
        for other in primary_contexts:
            if other.section_index == context.section_index or not other.primary_anchor or not other.primary_name:
                continue
            normalized_other_name = normalize_name(other.primary_name)
            if not normalized_other_name or normalized_other_name not in body_text:
                continue
            if relation == "example_of":
                _push_edge(
                    context.primary_name,
                    other.primary_name,
                    relation,
                    f"{context.primary_name} is presented as an example of {other.primary_name}.",
                    source_context={
                        "knowledge_document_id": context.knowledge_document_id,
                        "section_index": context.section_index,
                        "source_file_ids": context.source_file_ids,
                    },
                )
            elif relation in {"similar", "contrast"}:
                _push_edge(
                    context.primary_name,
                    other.primary_name,
                    relation,
                    f"{context.primary_name} is discussed together with {other.primary_name}.",
                    source_context={
                        "knowledge_document_id": context.knowledge_document_id,
                        "section_index": context.section_index,
                        "source_file_ids": context.source_file_ids,
                    },
                )
            else:
                _push_edge(
                    other.primary_name,
                    context.primary_name,
                    relation,
                    f"{other.primary_name} 支撑小节 {context.primary_name}。",
                    source_context={
                        "knowledge_document_id": context.knowledge_document_id,
                        "section_index": context.section_index,
                        "source_file_ids": context.source_file_ids,
                    },
                )

    return pending_edges


async def _extract_candidates_with_diagnostics_adapter(**kwargs) -> tuple[ChunkExtractionResult, CandidateExtractionDiagnostics]:
    if extract_candidates is not _DEFAULT_EXTRACT_CANDIDATES:
        result = await extract_candidates(**kwargs)
        return result, CandidateExtractionDiagnostics(
            llm_attempted=True,
            node_count=len(result.nodes),
            edge_count=len(result.edges),
        )
    return await extract_candidates_with_diagnostics(**kwargs)


async def _extract_chapter_with_retries(
    chapter_index: int,
    chapter,
    *,
    subject_context: str = "",
    chapter_context: ChapterSourceContext | None = None,
    source_chapter_index: int | None = None,
    source_kind: str = "chapter",
) -> SectionExtractionPayload:
    last_error: Exception | None = None
    max_retries = _chapter_max_retries()
    for attempt in range(1, max_retries + 1):
        try:
            return await _extract_chapter_graph_items(
                chapter_index,
                chapter,
                subject_context=subject_context,
                chapter_context=chapter_context,
                source_chapter_index=source_chapter_index,
                source_kind=source_kind,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            last_error = exc
            logger.warning(
                "knowledge_docs_sync_chapter_retry_scheduled",
                chapter_index=chapter_index,
                chunk_title=chapter.title,
                header_path=chapter.header_path,
                attempt=attempt,
                max_retries=max_retries,
                source_chapter_index=source_chapter_index,
                source_kind=source_kind,
                error_type=type(exc).__name__,
            )
            if attempt >= max_retries:
                break
            await asyncio.sleep(_chapter_retry_delay_s() * attempt)

    logger.error(
        "knowledge_docs_sync_chapter_llm_failed_after_retries",
        chapter_index=chapter_index,
        chunk_title=chapter.title,
        header_path=chapter.header_path,
        source_chapter_index=source_chapter_index,
        source_kind=source_kind,
        error_type=(type(last_error).__name__ if last_error is not None else "UnknownError"),
    )
    if last_error is not None:
        raise last_error
    raise RuntimeError("knowledge graph chapter extraction failed without an exception")


async def _extract_chapter_graph_items(
    chapter_index: int,
    chapter,
    *,
    subject_context: str = "",
    chapter_context: ChapterSourceContext | None = None,
    source_chapter_index: int | None = None,
    source_kind: str = "chapter",
) -> SectionExtractionPayload:
    chapter_context = chapter_context or ChapterSourceContext(chapter_index=chapter_index)
    resolved_chapter_index = chapter_context.chapter_index or source_chapter_index or chapter_index
    result, diagnostics = await _extract_candidates_with_diagnostics_adapter(
        chunk_content=chapter.body_markdown,
        chunk_title=chapter.title,
        header_path=chapter.header_path,
        doc_source_type="knowledge_doc_markdown",
        subject_context=subject_context,
        prefer_fast_path=False,
        allow_markdown_anchor_short_circuit=False,
    )
    result = filter_docs_candidate_result(result)
    diagnostics.node_count = len(result.nodes)
    diagnostics.edge_count = len(result.edges)

    used_anchors: set[str] = set()
    units: list[MarkdownKnowledgeUnit] = []
    anchor_by_candidate_id: dict[str, str] = {}
    anchors_by_name: dict[str, list[str]] = {}
    anchors_by_normalized_name: dict[str, list[str]] = {}
    node_contexts_by_anchor: dict[str, dict[str, object]] = {}
    body_markdown = chapter.body_markdown[:8000]
    knowledge_images = list(chapter.knowledge_images)
    primary_anchor: str | None = None
    primary_name = ""
    primary_type = ""
    normalized_section_title = normalize_name(chapter.title)

    for node in result.nodes:
        anchor_seed = node.anchor_id or node.candidate_id or f"{chapter.anchor}-{node.knowledge_unit_type}-{node.name}"
        anchor = build_knowledge_unit_anchor(anchor_seed, used=used_anchors)
        unit = MarkdownKnowledgeUnit(
            anchor=anchor,
            name=node.name,
            knowledge_unit_type=node.knowledge_unit_type,
            summary=node.local_summary or node.name,
            body_markdown=body_markdown,
            knowledge_images=knowledge_images,
            prerequisites=[],
            related=[],
            line_no=chapter.line_no,
            heading_level=chapter.heading_level,
            source_kind=f"llm_{source_kind}",
            knowledge_document_id=chapter_context.knowledge_document_id,
            chapter_index=resolved_chapter_index,
            source_file_ids=list(chapter_context.source_file_ids),
            quote_text=node.local_summary or chapter.summary or node.name,
        )
        units.append(unit)
        if node.candidate_id:
            anchor_by_candidate_id[node.candidate_id] = anchor
        anchors_by_name.setdefault(node.name, []).append(anchor)
        normalized_name = normalize_name(node.name)
        if normalized_name:
            anchors_by_normalized_name.setdefault(normalized_name, []).append(anchor)
        node_contexts_by_anchor[anchor] = {
            "name": node.name,
            "knowledge_unit_type": node.knowledge_unit_type,
            "taxonomy_hint": node.taxonomy_hint or "",
            "parent_entity_name": node.parent_entity_name or "",
            "section_index": chapter_index,
            "source_chapter_index": resolved_chapter_index,
            "knowledge_document_id": chapter_context.knowledge_document_id,
            "source_file_ids": list(chapter_context.source_file_ids),
        }
        if primary_anchor is None:
            primary_anchor = anchor
            primary_name = node.name
            primary_type = node.knowledge_unit_type
        if normalized_section_title and normalized_name == normalized_section_title:
            primary_anchor = anchor
            primary_name = node.name
            primary_type = node.knowledge_unit_type

    edges: list[PendingMarkdownExtractedEdge] = []
    for edge in result.edges:
        edges.append(
            PendingMarkdownExtractedEdge(
                source_candidate_id=edge.source_candidate_id,
                target_candidate_id=edge.target_candidate_id,
                source_name=edge.source_name,
                target_name=edge.target_name,
                edge_type=edge.edge_type,
                description=edge.description,
                source_kind="llm_relation",
                knowledge_document_id=chapter_context.knowledge_document_id,
                chapter_index=resolved_chapter_index,
                source_file_ids=list(chapter_context.source_file_ids),
                quote_text=edge.description,
            )
        )

    return SectionExtractionPayload(
        units=units,
        pending_edges=edges,
        candidate_id_to_anchor=anchor_by_candidate_id,
        anchors_by_name=anchors_by_name,
        anchors_by_normalized_name=anchors_by_normalized_name,
        node_contexts_by_anchor=node_contexts_by_anchor,
        section_context=SectionExtractionContext(
            section_index=chapter_index,
            title=chapter.title,
            header_path=chapter.header_path,
            body_markdown=body_markdown,
            primary_anchor=primary_anchor,
            primary_name=primary_name,
            primary_type=primary_type,
            knowledge_document_id=chapter_context.knowledge_document_id,
            source_file_ids=list(chapter_context.source_file_ids),
        ),
        diagnostics={
            "section_count": 0,
            "successful_section_count": 1,
            "failed_section_count": 0,
            "llm_section_count": 1 if diagnostics.llm_attempted else 0,
            "markdown_short_circuit_section_count": 1 if diagnostics.markdown_anchor_short_circuit_used else 0,
            "llm_error_count": diagnostics.llm_error_count,
            "empty_llm_result_count": diagnostics.empty_llm_result_count,
            "empty_repair_attempt_count": diagnostics.empty_repair_attempt_count,
            "empty_repair_success_count": diagnostics.empty_repair_success_count,
            "total_extracted_node_count": diagnostics.node_count,
            "total_extracted_edge_count": diagnostics.edge_count,
        },
    )


def _resolve_edge_anchor(
    *,
    candidate_id: str | None,
    endpoint_name: str,
    anchor_by_candidate_id: dict[str, str],
    anchors_by_name: dict[str, list[str]],
    anchors_by_normalized_name: dict[str, list[str]],
) -> str | None:
    if candidate_id:
        anchor = anchor_by_candidate_id.get(candidate_id)
        if anchor:
            return anchor

    exact_matches = anchors_by_name.get(endpoint_name, [])
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        return None

    normalized_name = normalize_name(endpoint_name)
    if not normalized_name:
        return None

    normalized_matches = anchors_by_normalized_name.get(normalized_name, [])
    if len(normalized_matches) == 1:
        return normalized_matches[0]

    fuzzy_matches = [
        matches[0]
        for key, matches in anchors_by_normalized_name.items()
        if len(matches) == 1 and (normalized_name in key or key in normalized_name)
    ]
    if len(fuzzy_matches) == 1:
        return fuzzy_matches[0]
    return None


def _upsert_unit(
    session: Session,
    *,
    subject: str,
    item: MarkdownKnowledgeUnit,
    build_revision_no: int,
    enable_rag_dedup: bool = False,
) -> tuple[KnowledgeUnit, bool]:
    knowledge_unit_type = normalize_knowledge_unit_type(item.knowledge_unit_type)
    normalized_name = normalize_name(item.name)
    unit = _find_unit_by_anchor(session, subject=subject, anchor=item.anchor)
    if unit is None:
        unit = _find_unit_by_exact_name(
            session,
            subject=subject,
            item=item,
            knowledge_unit_type=knowledge_unit_type,
        )
    if unit is None and enable_rag_dedup:
        unit = _find_unit_with_rag(
            session,
            subject=subject,
            item=item,
            knowledge_unit_type=knowledge_unit_type,
        )
    name_conflict_unit = knowledge_unit_repo.find_knowledge_unit_by_normalized_name(
        session,
        subject,
        normalized_name,
        knowledge_unit_type,
    )
    if name_conflict_unit is not None and (unit is None or name_conflict_unit.id != unit.id):
        unit = name_conflict_unit
    if unit is None:
        unit = knowledge_unit_repo.find_knowledge_unit_by_normalized_name(
            session,
            subject,
            normalized_name,
            knowledge_unit_type,
        )
    created = unit is None
    if unit is None:
        unit = KnowledgeUnit(
            subject=subject,
            knowledge_unit_type=knowledge_unit_type,
            canonical_name=item.name,
            normalized_name=normalized_name,
            status="active",
        )
    unit.knowledge_unit_type = knowledge_unit_type
    unit.canonical_name = item.name
    unit.normalized_name = normalized_name
    unit.summary = item.summary or item.name
    unit.body_markdown = item.body_markdown or item.summary or item.name
    unit.body = unit.body_markdown
    unit.type_source = "manual"
    unit.type_confidence = 1.0
    unit.status = "active"
    unit.build_revision_no = build_revision_no
    unit.updated_at = utcnow()
    unit.aliases_json = _add_anchor_alias(unit.aliases_json, item.anchor)
    if created:
        unit = knowledge_unit_repo.create_knowledge_unit(session, unit, auto_commit=False)
    else:
        session.add(unit)
    session.flush()
    return unit, created


def _upsert_edge(
    session: Session,
    *,
    subject: str,
    source_node_id: int,
    target_node_id: int,
    edge_type: str,
    description: str,
    build_revision_no: int,
) -> tuple[KnowledgeEdge, bool]:
    normalized_type = normalize_relation_type(edge_type)
    existing = knowledge_relation_repo.find_edge(
        session,
        source_node_id,
        target_node_id,
        normalized_type,
    )
    created = existing is None
    edge = existing or KnowledgeEdge(
        subject=subject,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_type=normalized_type,
    )
    edge.description = f"{_SYNC_EDGE_MARKER}: {description}"
    edge.status = "active"
    edge.weight = 1.0
    edge.confidence = max(edge.confidence, 0.95)
    edge.build_revision_no = build_revision_no
    edge.updated_at = utcnow()
    if created:
        edge = knowledge_relation_repo.create_knowledge_edge(session, edge, auto_commit=False)
    else:
        session.add(edge)
    session.flush()
    return edge, created


def _find_unit_by_anchor(session: Session, *, subject: str, anchor: str) -> KnowledgeUnit | None:
    candidates = session.exec(
        select(KnowledgeUnit).where(
            KnowledgeUnit.subject == subject,
            KnowledgeUnit.status.in_(["active", "pending", "deprecated"]),
        )
    ).all()
    for unit in candidates:
        for alias in _load_aliases(unit.aliases_json):
            if alias.get("source") == _ANCHOR_ALIAS_SOURCE and alias.get("normalized_alias") == anchor:
                return unit
    return None


def _find_unit_by_exact_name(
    session: Session,
    *,
    subject: str,
    item: MarkdownKnowledgeUnit,
    knowledge_unit_type: str,
) -> KnowledgeUnit | None:
    normalized_name = normalize_name(item.name)
    if not normalized_name:
        return None
    return knowledge_unit_repo.find_knowledge_unit_by_normalized_name(
        session,
        subject,
        normalized_name,
        knowledge_unit_type,
    )


def _find_unit_with_rag(
    session: Session,
    *,
    subject: str,
    item: MarkdownKnowledgeUnit,
    knowledge_unit_type: str,
) -> KnowledgeUnit | None:
    query = "\n".join(part.strip() for part in [item.name, item.summary] if part.strip()).strip()
    if not query:
        return None

    rag_hits = _run_async(
        search_knowledge(
            query,
            subject,
            top_k=_RAG_DEDUP_TOP_K,
            enable_rerank=False,
        )
    )
    if not rag_hits:
        return None

    candidates = session.exec(
        select(KnowledgeUnit).where(
            KnowledgeUnit.subject == subject,
            KnowledgeUnit.knowledge_unit_type == knowledge_unit_type,
            KnowledgeUnit.status.in_(["active", "pending"]),
        )
    ).all()
    if not candidates:
        return None

    candidate_text = _build_dedup_text(item.name, item.summary, item.body_markdown)
    existing_texts = [
        _build_dedup_text(unit.canonical_name, unit.summary, unit.body_markdown or unit.body)
        for unit in candidates
    ]
    embeddings = _run_async(aembed_texts([candidate_text, *existing_texts], soft_fail=True))
    if len(embeddings) < 2:
        return None

    candidate_embedding = embeddings[0]
    best_similarity = 0.0
    best_unit: KnowledgeUnit | None = None
    for unit, embedding in zip(candidates, embeddings[1:], strict=False):
        similarity = _cosine_similarity(candidate_embedding, embedding)
        if similarity > best_similarity:
            best_similarity = similarity
            best_unit = unit

    if best_unit is None or best_similarity < _RAG_DEDUP_SIMILARITY_THRESHOLD:
        return None
    return best_unit


def _build_dedup_text(name: str, summary: str, body_markdown: str) -> str:
    body_excerpt = (body_markdown or "").strip()
    if len(body_excerpt) > 1200:
        body_excerpt = body_excerpt[:1200]
    return "\n".join(part.strip() for part in [name, summary, body_excerpt] if part.strip())


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _run_async(coro):
    loop = _get_async_bridge_loop()
    context = contextvars.copy_context()

    async def _run_with_context():
        task = asyncio.create_task(coro, context=context)
        return await task

    future = asyncio.run_coroutine_threadsafe(_run_with_context(), loop)
    return future.result()


def _get_async_bridge_loop() -> asyncio.AbstractEventLoop:
    global _ASYNC_BRIDGE_LOOP, _ASYNC_BRIDGE_THREAD

    loop = _ASYNC_BRIDGE_LOOP
    if loop is not None and loop.is_running():
        return loop

    with _ASYNC_BRIDGE_LOCK:
        loop = _ASYNC_BRIDGE_LOOP
        if loop is not None and loop.is_running():
            return loop

        _ASYNC_BRIDGE_READY.clear()

        def _runner() -> None:
            global _ASYNC_BRIDGE_LOOP

            loop = asyncio.new_event_loop()
            _ASYNC_BRIDGE_LOOP = loop
            asyncio.set_event_loop(loop)
            _ASYNC_BRIDGE_READY.set()
            loop.run_forever()

        _ASYNC_BRIDGE_THREAD = threading.Thread(
            target=_runner,
            name="knowledge-graph-async-bridge",
            daemon=True,
        )
        _ASYNC_BRIDGE_THREAD.start()

    _ASYNC_BRIDGE_READY.wait()
    if _ASYNC_BRIDGE_LOOP is None:  # pragma: no cover - defensive guard
        raise RuntimeError("knowledge_graph_async_bridge_unavailable")
    return _ASYNC_BRIDGE_LOOP


def _add_anchor_alias(raw_aliases: str, anchor: str) -> str:
    aliases = _load_aliases(raw_aliases)
    if not any(alias.get("source") == _ANCHOR_ALIAS_SOURCE and alias.get("normalized_alias") == anchor for alias in aliases):
        aliases.append(
            {
                "alias": anchor,
                "normalized_alias": anchor,
                "language": "anchor",
                "source": _ANCHOR_ALIAS_SOURCE,
                "confidence": 1.0,
                "is_primary": False,
                "status": "active",
            }
        )
    return json.dumps(aliases, ensure_ascii=False)


def _load_aliases(raw_aliases: str) -> list[dict[str, object]]:
    try:
        payload = json.loads(raw_aliases or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _deprecate_removed_anchor_units(
    session: Session,
    *,
    subject: str,
    active_anchors: set[str],
    build_revision_no: int,
) -> list[int]:
    deprecated: list[int] = []
    units = session.exec(
        select(KnowledgeUnit).where(
            KnowledgeUnit.subject == subject,
            KnowledgeUnit.status == "active",
        )
    ).all()
    for unit in units:
        anchors = [
            str(alias.get("normalized_alias", ""))
            for alias in _load_aliases(unit.aliases_json)
            if alias.get("source") == _ANCHOR_ALIAS_SOURCE
        ]
        if not anchors:
            continue
        if any(anchor in active_anchors for anchor in anchors):
            continue
        unit.status = "deprecated"
        unit.build_revision_no = build_revision_no
        unit.updated_at = utcnow()
        session.add(unit)
        if unit.id is not None:
            deprecated.append(unit.id)
    return deprecated


def _deprecate_removed_sync_edges(
    session: Session,
    *,
    subject: str,
    seen_edge_keys: set[tuple[int, int, str]],
    build_revision_no: int,
) -> list[int]:
    deprecated: list[int] = []
    edges = session.exec(
        select(KnowledgeEdge).where(
            KnowledgeEdge.subject == subject,
            KnowledgeEdge.status == "active",
            KnowledgeEdge.description.startswith(f"{_SYNC_EDGE_MARKER}:"),
        )
    ).all()
    for edge in edges:
        key = (edge.source_node_id, edge.target_node_id, edge.edge_type)
        if key in seen_edge_keys:
            continue
        edge.status = "deprecated"
        edge.build_revision_no = build_revision_no
        edge.updated_at = utcnow()
        session.add(edge)
        if edge.id is not None:
            deprecated.append(edge.id)
    return deprecated


__all__ = [
    "KnowledgeSyncExtractionPayload",
    "KnowledgeSyncReport",
    "KnowledgeSyncRunContext",
    "extract_knowledge_graph_items",
    "graph_extraction_parallelism",
    "initialize_knowledge_graph_sync_run",
    "mark_knowledge_graph_sync_run_failed",
    "persist_knowledge_graph_items",
    "sync_markdown_knowledge_graph",
]
