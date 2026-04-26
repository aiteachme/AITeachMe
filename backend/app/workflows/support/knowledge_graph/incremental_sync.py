"""Incremental knowledge-doc to knowledge-graph synchronization."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from time import perf_counter
import threading

import structlog
from sqlmodel import Session, select

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
    extract_markdown_chapter_chunks,
    extract_markdown_section_chunks,
    validate_knowledge_unit_anchors,
)
from app.workflows.digest.kg_file_ingest.lib.extractor import (
    CandidateExtractionDiagnostics,
    CandidateNode,
    ChunkExtractionResult,
    extract_candidates,
    extract_candidates_with_diagnostics,
)

_ANCHOR_ALIAS_SOURCE = "markdown_anchor"
_SYNC_EDGE_MARKER = "markdown_anchor_sync"
_RAG_DEDUP_TOP_K = 6
_RAG_DEDUP_SIMILARITY_THRESHOLD = 0.82
_DEFAULT_DOCS_SYNC_CHAPTER_CONCURRENCY_LIMIT = 6
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


@dataclass(slots=True)
class KnowledgeSyncReport:
    """Summary of one incremental sync pass."""

    subject: str
    build_revision_no: int
    synced_unit_keys: list[str] = field(default_factory=list)
    knowledge_image_count: int = 0
    created_unit_ids: list[int] = field(default_factory=list)
    updated_unit_ids: list[int] = field(default_factory=list)
    deprecated_unit_ids: list[int] = field(default_factory=list)
    created_edge_ids: list[int] = field(default_factory=list)
    updated_edge_ids: list[int] = field(default_factory=list)
    deprecated_edge_ids: list[int] = field(default_factory=list)
    section_count: int = 0
    chapter_count: int = 0
    llm_section_count: int = 0
    fallback_section_count: int = 0
    question_fallback_section_count: int = 0
    topic_fallback_section_count: int = 0
    markdown_short_circuit_section_count: int = 0
    total_extracted_node_count: int = 0
    total_extracted_edge_count: int = 0
    elapsed_ms: int = 0

    @property
    def unit_change_count(self) -> int:
        return len(self.created_unit_ids) + len(self.updated_unit_ids) + len(self.deprecated_unit_ids)

    @property
    def edge_change_count(self) -> int:
        return len(self.created_edge_ids) + len(self.updated_edge_ids) + len(self.deprecated_edge_ids)


@dataclass(slots=True)
class MarkdownExtractedEdge:
    """Chunk-level extracted edge resolved to markdown-sync anchors."""

    source_anchor: str
    target_anchor: str
    edge_type: str
    description: str


@dataclass(slots=True)
class PendingMarkdownExtractedEdge:
    """Chunk-level extracted edge before endpoint anchors are resolved."""

    source_candidate_id: str | None
    target_candidate_id: str | None
    source_name: str
    target_name: str
    edge_type: str
    description: str


@dataclass(slots=True)
class SectionExtractionContext:
    """Context retained after one section extraction for cross-section merging."""

    section_index: int
    title: str
    header_path: str
    body_markdown: str
    primary_anchor: str | None = None
    primary_name: str = ""
    primary_type: str = ""


@dataclass(slots=True)
class SectionExtractionPayload:
    """Normalized result for one extracted markdown section."""

    units: list[MarkdownKnowledgeUnit]
    pending_edges: list[PendingMarkdownExtractedEdge]
    candidate_id_to_anchor: dict[str, str]
    anchors_by_name: dict[str, list[str]]
    anchors_by_normalized_name: dict[str, list[str]]
    node_contexts_by_anchor: dict[str, dict[str, object]]
    section_context: SectionExtractionContext
    diagnostics: dict[str, int]


def sync_markdown_knowledge_graph(
    session: Session,
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None = None,
    enable_rag_dedup: bool = False,
    subject_context: str | None = None,
) -> KnowledgeSyncReport:
    """Synchronize knowledge units and knowledge images from Markdown into the graph."""

    started_at = perf_counter()
    validation = validate_knowledge_unit_anchors(markdown)
    if not validation.ok:
        raise ValueError(
            "invalid Markdown KnowledgeUnit anchors: "
            f"duplicates={validation.duplicate_anchors}, invalid={validation.invalid_anchors}"
        )

    revision_no = build_revision_no or _next_revision_no(session, subject)
    units, extracted_edges, diagnostics_totals = _extract_markdown_graph_items(
        markdown,
        subject_context=subject_context,
    )
    report = KnowledgeSyncReport(
        subject=subject,
        build_revision_no=revision_no,
        synced_unit_keys=[item.anchor for item in units],
        section_count=int(diagnostics_totals.get("section_count", 0) or 0),
        chapter_count=int(diagnostics_totals.get("chapter_count", 0) or 0),
        llm_section_count=int(diagnostics_totals.get("llm_section_count", 0) or 0),
        fallback_section_count=int(diagnostics_totals.get("fallback_section_count", 0) or 0),
        question_fallback_section_count=int(diagnostics_totals.get("question_fallback_section_count", 0) or 0),
        topic_fallback_section_count=int(diagnostics_totals.get("topic_fallback_section_count", 0) or 0),
        markdown_short_circuit_section_count=int(diagnostics_totals.get("markdown_short_circuit_section_count", 0) or 0),
        total_extracted_node_count=int(diagnostics_totals.get("total_extracted_node_count", 0) or 0),
        total_extracted_edge_count=int(diagnostics_totals.get("total_extracted_edge_count", 0) or 0),
    )
    unit_by_anchor: dict[str, KnowledgeUnit] = {}
    report.knowledge_image_count = sum(len(item.knowledge_images) for item in units)

    for item in units:
        unit, created = _upsert_unit(
            session,
            subject=subject,
            item=item,
            build_revision_no=revision_no,
            enable_rag_dedup=enable_rag_dedup,
        )
        if unit.id is None:
            continue
        unit_by_anchor[item.anchor] = unit
        if created:
            report.created_unit_ids.append(unit.id)
        else:
            report.updated_unit_ids.append(unit.id)

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
            build_revision_no=revision_no,
        )
        if edge.id is not None:
            seen_edge_keys.add((edge.source_node_id, edge.target_node_id, edge.edge_type))
            (report.created_edge_ids if created else report.updated_edge_ids).append(edge.id)

    report.deprecated_unit_ids.extend(
        _deprecate_removed_anchor_units(
            session,
            subject=subject,
            active_anchors=set(report.synced_unit_keys),
            build_revision_no=revision_no,
        )
    )
    report.deprecated_edge_ids.extend(
        _deprecate_removed_sync_edges(
            session,
            subject=subject,
            seen_edge_keys=seen_edge_keys,
            build_revision_no=revision_no,
        )
    )
    session.commit()
    report.elapsed_ms = int((perf_counter() - started_at) * 1000)
    logger.info(
        "knowledge_docs_sync_complete",
        subject=subject,
        build_revision_no=revision_no,
        chapter_count=report.chapter_count,
        section_count=report.section_count,
        llm_section_count=report.llm_section_count,
        fallback_section_count=report.fallback_section_count,
        question_fallback_section_count=report.question_fallback_section_count,
        topic_fallback_section_count=report.topic_fallback_section_count,
        unit_change_count=report.unit_change_count,
        edge_change_count=report.edge_change_count,
        elapsed_ms=report.elapsed_ms,
    )
    return report


def _next_revision_no(session: Session, subject: str) -> int:
    units = session.exec(select(KnowledgeUnit).where(KnowledgeUnit.subject == subject)).all()
    edges = session.exec(select(KnowledgeEdge).where(KnowledgeEdge.subject == subject)).all()
    current = max(
        [0]
        + [int(item.build_revision_no or 0) for item in units]
        + [int(item.build_revision_no or 0) for item in edges]
    )
    return current + 1


def _empty_extraction_diagnostics() -> dict[str, int]:
    return {
        "chapter_count": 0,
        "section_count": 0,
        "llm_section_count": 0,
        "fallback_section_count": 0,
        "question_fallback_section_count": 0,
        "topic_fallback_section_count": 0,
        "markdown_short_circuit_section_count": 0,
        "total_extracted_node_count": 0,
        "total_extracted_edge_count": 0,
    }


def _chapter_concurrency_limit() -> int:
    configured = _DOCS_SYNC_CHAPTER_CONCURRENCY_LIMIT
    if configured == _DEFAULT_DOCS_SYNC_CHAPTER_CONCURRENCY_LIMIT:
        configured = _DOCS_SYNC_SECTION_CONCURRENCY_LIMIT
    return max(1, int(configured))


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


def _extract_markdown_graph_items(
    markdown: str,
    *,
    subject_context: str | None = None,
) -> tuple[list[MarkdownKnowledgeUnit], list[MarkdownExtractedEdge], dict[str, int]]:
    chapters = extract_markdown_chapter_chunks(markdown)
    sections = extract_markdown_section_chunks(markdown)
    if not chapters:
        return [], [], _empty_extraction_diagnostics()

    async def _extract_all_chapters() -> list[SectionExtractionPayload]:
        semaphore = asyncio.Semaphore(_chapter_concurrency_limit())

        async def _extract_with_queue(chapter_index: int, chapter) -> SectionExtractionPayload:
            async with semaphore:
                return await _extract_chapter_with_retries(
                    chapter_index,
                    chapter,
                    subject_context=subject_context or "",
                )

        return await asyncio.gather(
            *[_extract_with_queue(chapter_index, chapter) for chapter_index, chapter in enumerate(chapters)]
        )

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
    diagnostics_totals["section_count"] = len(chapters)

    for payload in results:
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
            )
        )
    return units, edges, diagnostics_totals


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
            )
        )

    return pending_edges


def _hint_edge_type_for_unit(unit_type: str) -> str:
    normalized = normalize_knowledge_unit_type(unit_type)
    if normalized in {"example", "exercise"}:
        return "example_of"
    if normalized in {"remark"}:
        return "application"
    return "derivation"


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

    def _push_edge(source_name: str, target_name: str, edge_type: str, description: str) -> None:
        key = (normalize_name(source_name), normalize_name(target_name), edge_type)
        if not key[0] or not key[1] or key in seen or key[0] == key[1]:
            return
        seen.add(key)
        pending_edges.append(
            PendingMarkdownExtractedEdge(
                source_candidate_id=None,
                target_candidate_id=None,
                source_name=source_name,
                target_name=target_name,
                edge_type=edge_type,
                description=description,
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
                _hint_edge_type_for_unit(source_type),
                f"{source_name} references {hint_name} across sections via {hint_field}.",
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
                )
            elif relation in {"similar", "contrast"}:
                _push_edge(
                    context.primary_name,
                    other.primary_name,
                    relation,
                    f"{context.primary_name} is discussed together with {other.primary_name}.",
                )
            else:
                _push_edge(
                    other.primary_name,
                    context.primary_name,
                    relation,
                    f"{other.primary_name} supports section {context.primary_name}.",
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


def _merge_missing_chapter_heading_nodes(result: ChunkExtractionResult, chapter) -> ChunkExtractionResult:
    section_chunks = extract_markdown_section_chunks(chapter.body_markdown)
    had_extracted_nodes = bool(result.nodes)
    seen_names = {normalize_name(node.name) for node in result.nodes if normalize_name(node.name)}

    for section in section_chunks:
        if had_extracted_nodes and int(section.heading_level or 1) <= 1:
            continue
        normalized_title = normalize_name(section.title)
        if not normalized_title or normalized_title in seen_names:
            continue
        path_parts = [part.strip() for part in str(section.header_path or "").split(" > ") if part.strip()]
        parent_title = path_parts[-2] if len(path_parts) >= 2 else ""
        seen_names.add(normalized_title)
        result.nodes.append(
            CandidateNode(
                candidate_id=section.anchor,
                anchor_id=section.anchor,
                name=section.title,
                knowledge_unit_type="concept",
                type_source="rule",
                type_confidence=0.8,
                local_summary=section.summary or section.title,
                taxonomy_hint=parent_title or chapter.title,
                parent_entity_name=parent_title or None,
            )
        )

    return result


async def _extract_chapter_with_retries(
    chapter_index: int,
    chapter,
    *,
    subject_context: str = "",
) -> SectionExtractionPayload:
    last_error: Exception | None = None
    max_retries = _chapter_max_retries()
    for attempt in range(1, max_retries + 1):
        try:
            return await _extract_chapter_graph_items(
                chapter_index,
                chapter,
                subject_context=subject_context,
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
                error_type=type(exc).__name__,
            )
            if attempt >= max_retries:
                break
            await asyncio.sleep(_chapter_retry_delay_s() * attempt)

    logger.warning(
        "knowledge_docs_sync_chapter_fallback_after_retries",
        chapter_index=chapter_index,
        chunk_title=chapter.title,
        header_path=chapter.header_path,
        error_type=(type(last_error).__name__ if last_error is not None else "UnknownError"),
    )
    return _build_chapter_fallback_payload(chapter_index, chapter)


def _build_chapter_fallback_payload(chapter_index: int, chapter) -> SectionExtractionPayload:
    body_markdown = chapter.body_markdown[:8000]
    primary_anchor = str(chapter.anchor or build_knowledge_unit_anchor(chapter.title))
    primary_unit = MarkdownKnowledgeUnit(
        anchor=primary_anchor,
        name=chapter.title,
        knowledge_unit_type="concept",
        summary=chapter.summary or chapter.title,
        body_markdown=body_markdown,
        knowledge_images=list(chapter.knowledge_images),
        prerequisites=[],
        related=[],
        line_no=chapter.line_no,
        heading_level=chapter.heading_level,
    )
    normalized_name = normalize_name(chapter.title)
    return SectionExtractionPayload(
        units=[primary_unit],
        pending_edges=[],
        candidate_id_to_anchor={},
        anchors_by_name={chapter.title: [primary_anchor]},
        anchors_by_normalized_name=({normalized_name: [primary_anchor]} if normalized_name else {}),
        node_contexts_by_anchor={
            primary_anchor: {
                "name": chapter.title,
                "knowledge_unit_type": "concept",
                "taxonomy_hint": chapter.title,
                "parent_entity_name": "",
                "section_index": chapter_index,
            }
        },
        section_context=SectionExtractionContext(
            section_index=chapter_index,
            title=chapter.title,
            header_path=chapter.header_path,
            body_markdown=body_markdown,
            primary_anchor=primary_anchor,
            primary_name=chapter.title,
            primary_type="concept",
        ),
        diagnostics={
            "section_count": 0,
            "llm_section_count": 0,
            "fallback_section_count": 1,
            "question_fallback_section_count": 0,
            "topic_fallback_section_count": 1,
            "markdown_short_circuit_section_count": 0,
            "total_extracted_node_count": 1,
            "total_extracted_edge_count": 0,
        },
    )


async def _extract_chapter_graph_items(
    chapter_index: int,
    chapter,
    *,
    subject_context: str = "",
) -> SectionExtractionPayload:
    result, diagnostics = await _extract_candidates_with_diagnostics_adapter(
        chunk_content=chapter.body_markdown,
        chunk_title=chapter.title,
        header_path=chapter.header_path,
        doc_source_type="knowledge_doc_markdown",
        subject_context=subject_context,
        prefer_fast_path=False,
        allow_markdown_anchor_short_circuit=False,
    )
    result = _merge_missing_chapter_heading_nodes(result, chapter)
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
        ),
        diagnostics={
            "section_count": 0,
            "llm_section_count": 1 if diagnostics.llm_attempted else 0,
            "fallback_section_count": 1 if (diagnostics.used_question_fallback or diagnostics.used_topic_fallback) else 0,
            "question_fallback_section_count": 1 if diagnostics.used_question_fallback else 0,
            "topic_fallback_section_count": 1 if diagnostics.used_topic_fallback else 0,
            "markdown_short_circuit_section_count": 1 if diagnostics.markdown_anchor_short_circuit_used else 0,
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
    future = asyncio.run_coroutine_threadsafe(coro, loop)
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


__all__ = ["KnowledgeSyncReport", "sync_markdown_knowledge_graph"]
