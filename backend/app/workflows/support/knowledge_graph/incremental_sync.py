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
from app.models.knowledge_taxonomy import normalize_knowledge_unit_type, normalize_relation_type
from app.repositories import knowledge_relation_repo, knowledge_unit_repo
from app.shared.infra.embedding import aembed_texts
from app.shared.infra.search.api import search_knowledge
from app.utils.knowledge_helpers import normalize_name
from app.utils.time import utcnow
from app.workflows.digest.common.markdown_knowledge_anchors import build_knowledge_unit_anchor
from app.workflows.digest.common.markdown_knowledge_anchors import (
    MarkdownKnowledgeUnit,
    extract_markdown_section_chunks,
    validate_knowledge_unit_anchors,
)
from app.workflows.digest.kg_file_ingest.lib.extractor import extract_candidates

_ANCHOR_ALIAS_SOURCE = "markdown_anchor"
_SYNC_EDGE_MARKER = "markdown_anchor_sync"
_RAG_DEDUP_TOP_K = 6
_RAG_DEDUP_SIMILARITY_THRESHOLD = 0.82
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


def sync_markdown_knowledge_graph(
    session: Session,
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None = None,
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
    units, extracted_edges = _extract_markdown_graph_items(markdown)
    report = KnowledgeSyncReport(
        subject=subject,
        build_revision_no=revision_no,
        synced_unit_keys=[item.anchor for item in units],
    )
    unit_by_anchor: dict[str, KnowledgeUnit] = {}
    report.knowledge_image_count = sum(len(item.knowledge_images) for item in units)

    for item in units:
        unit, created = _upsert_unit(session, subject=subject, item=item, build_revision_no=revision_no)
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


def _extract_markdown_graph_items(markdown: str) -> tuple[list[MarkdownKnowledgeUnit], list[MarkdownExtractedEdge]]:
    sections = extract_markdown_section_chunks(markdown)
    if not sections:
        return [], []

    async def _extract_all_sections() -> list[
        tuple[
            list[MarkdownKnowledgeUnit],
            list[PendingMarkdownExtractedEdge],
            dict[str, str],
            dict[str, list[str]],
            dict[str, list[str]],
        ]
    ]:
        return await asyncio.gather(*[_extract_section_graph_items(section) for section in sections])

    results = _run_async(_extract_all_sections()) or []
    units: list[MarkdownKnowledgeUnit] = []
    pending_edges: list[PendingMarkdownExtractedEdge] = []
    candidate_id_to_anchor: dict[str, str] = {}
    anchors_by_name: dict[str, list[str]] = {}
    anchors_by_normalized_name: dict[str, list[str]] = {}
    units_by_section_index: list[list[MarkdownKnowledgeUnit]] = []

    for (
        section_units,
        section_pending_edges,
        section_candidate_id_to_anchor,
        section_anchors_by_name,
        section_anchors_by_normalized_name,
    ) in results:
        units.extend(section_units)
        units_by_section_index.append(section_units)
        pending_edges.extend(section_pending_edges)
        candidate_id_to_anchor.update(section_candidate_id_to_anchor)
        for name, anchors in section_anchors_by_name.items():
            bucket = anchors_by_name.setdefault(name, [])
            for anchor in anchors:
                if anchor not in bucket:
                    bucket.append(anchor)
        for normalized_name, anchors in section_anchors_by_normalized_name.items():
            bucket = anchors_by_normalized_name.setdefault(normalized_name, [])
            for anchor in anchors:
                if anchor not in bucket:
                    bucket.append(anchor)

    pending_edges.extend(
        _build_structural_section_edges(
            sections=sections,
            units_by_section_index=units_by_section_index,
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
    return units, edges


def _build_structural_section_edges(
    *,
    sections,
    units_by_section_index: list[list[MarkdownKnowledgeUnit]],
    anchors_by_name: dict[str, list[str]],
    anchors_by_normalized_name: dict[str, list[str]],
) -> list[PendingMarkdownExtractedEdge]:
    pending_edges: list[PendingMarkdownExtractedEdge] = []
    seen: set[tuple[str, str, str]] = set()

    for section, section_units in zip(sections, units_by_section_index, strict=False):
        path_parts = [part.strip() for part in str(section.header_path or "").split(" > ") if part.strip()]
        if len(path_parts) < 2 or not section_units:
            continue

        parent_title = path_parts[-2]
        parent_anchor = _resolve_edge_anchor(
            candidate_id=None,
            endpoint_name=parent_title,
            anchor_by_candidate_id={},
            anchors_by_name=anchors_by_name,
            anchors_by_normalized_name=anchors_by_normalized_name,
        )
        if not parent_anchor:
            continue

        section_title_normalized = normalize_name(section.title)
        primary_units = [
            unit
            for unit in section_units
            if section_title_normalized and normalize_name(unit.name) == section_title_normalized
        ]
        scoped_units = primary_units or section_units
        for unit in scoped_units:
            if unit.anchor == parent_anchor:
                continue
            key = (unit.anchor, parent_anchor, "derivation")
            if key in seen:
                continue
            seen.add(key)
            pending_edges.append(
                PendingMarkdownExtractedEdge(
                    source_candidate_id=None,
                    target_candidate_id=None,
                    source_name=unit.name,
                    target_name=parent_title,
                    edge_type="derivation",
                    description=f"{unit.name} 属于主题 {parent_title}。",
                )
            )

    return pending_edges


async def _extract_section_graph_items(section) -> tuple[
    list[MarkdownKnowledgeUnit],
    list[PendingMarkdownExtractedEdge],
    dict[str, str],
    dict[str, list[str]],
    dict[str, list[str]],
]:
    result = await extract_candidates(
        chunk_content=section.body_markdown,
        chunk_title=section.title,
        header_path=section.header_path,
        doc_source_type="knowledge_doc_markdown",
        prefer_fast_path=False,
    )

    used_anchors: set[str] = set()
    units: list[MarkdownKnowledgeUnit] = []
    anchor_by_candidate_id: dict[str, str] = {}
    anchors_by_name: dict[str, list[str]] = {}
    anchors_by_normalized_name: dict[str, list[str]] = {}
    body_markdown = section.body_markdown[:8000]
    knowledge_images = list(section.knowledge_images)

    for node in result.nodes:
        anchor_seed = node.anchor_id or node.candidate_id or f"{section.anchor}-{node.knowledge_unit_type}-{node.name}"
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
            line_no=section.line_no,
            heading_level=section.heading_level,
        )
        units.append(unit)
        if node.candidate_id:
            anchor_by_candidate_id[node.candidate_id] = anchor
        anchors_by_name.setdefault(node.name, []).append(anchor)
        normalized_name = normalize_name(node.name)
        if normalized_name:
            anchors_by_normalized_name.setdefault(normalized_name, []).append(anchor)

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

    return units, edges, anchor_by_candidate_id, anchors_by_name, anchors_by_normalized_name


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
) -> tuple[KnowledgeUnit, bool]:
    knowledge_unit_type = normalize_knowledge_unit_type(item.knowledge_unit_type)
    normalized_name = normalize_name(item.name)
    unit = _find_unit_by_anchor(session, subject=subject, anchor=item.anchor)
    if unit is None:
        unit = _find_unit_with_rag(
            session,
            subject=subject,
            item=item,
            knowledge_unit_type=knowledge_unit_type,
        )
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
