"""Incremental knowledge-doc to knowledge-graph synchronization."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from time import perf_counter

from sqlmodel import Session, select

from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_unit import KnowledgeUnit
from app.models.knowledge_taxonomy import normalize_knowledge_unit_type, normalize_relation_type
from app.repositories import knowledge_relation_repo, knowledge_unit_repo
from app.shared.infra.embedding import aembed_texts
from app.shared.infra.search.api import search_knowledge
from app.utils.knowledge_helpers import normalize_name
from app.utils.time import utcnow
from app.workflows.digest.common.markdown_knowledge_anchors import (
    MarkdownKnowledgeUnit,
    extract_markdown_knowledge_units,
)

_ANCHOR_ALIAS_SOURCE = "markdown_anchor"
_SYNC_EDGE_MARKER = "markdown_anchor_sync"
_RAG_DEDUP_TOP_K = 6
_RAG_DEDUP_SIMILARITY_THRESHOLD = 0.82


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


def sync_markdown_knowledge_graph(
    session: Session,
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None = None,
) -> KnowledgeSyncReport:
    """Synchronize knowledge units and knowledge images from Markdown into the graph."""

    started_at = perf_counter()
    revision_no = build_revision_no or _next_revision_no(session, subject)
    units = extract_markdown_knowledge_units(markdown)
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
    for item in units:
        target = unit_by_anchor.get(item.anchor)
        if target is None or target.id is None:
            continue
        structural_parent = _find_structural_parent_item(units, item)
        if structural_parent is not None:
            parent_unit = unit_by_anchor.get(structural_parent.anchor)
            if parent_unit is not None and parent_unit.id is not None:
                structural_edge = _build_structural_edge(
                    item=item,
                    item_unit=target,
                    parent_item=structural_parent,
                    parent_unit=parent_unit,
                )
                if structural_edge is not None:
                    edge, created = _upsert_edge(
                        session,
                        subject=subject,
                        source_node_id=structural_edge["source_node_id"],
                        target_node_id=structural_edge["target_node_id"],
                        edge_type=str(structural_edge["edge_type"]),
                        description=str(structural_edge["description"]),
                        build_revision_no=revision_no,
                    )
                    if edge.id is not None:
                        seen_edge_keys.add((edge.source_node_id, edge.target_node_id, edge.edge_type))
                        (report.created_edge_ids if created else report.updated_edge_ids).append(edge.id)
        for prerequisite_name in item.prerequisites:
            source = _ensure_related_concept(
                session,
                subject=subject,
                name=prerequisite_name,
                build_revision_no=revision_no,
            )
            if source.id is None:
                continue
            edge, created = _upsert_edge(
                session,
                subject=subject,
                source_node_id=source.id,
                target_node_id=target.id,
                edge_type="prerequisite",
                description=f"{source.canonical_name} is a prerequisite for {target.canonical_name}.",
                build_revision_no=revision_no,
            )
            if edge.id is not None:
                seen_edge_keys.add((edge.source_node_id, edge.target_node_id, edge.edge_type))
                (report.created_edge_ids if created else report.updated_edge_ids).append(edge.id)
        for related_name in item.related:
            related = _ensure_related_concept(
                session,
                subject=subject,
                name=related_name,
                build_revision_no=revision_no,
            )
            if related.id is None:
                continue
            edge, created = _upsert_edge(
                session,
                subject=subject,
                source_node_id=target.id,
                target_node_id=related.id,
                edge_type="similar",
                description=f"{target.canonical_name} is related to {related.canonical_name}.",
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


def _ensure_related_concept(
    session: Session,
    *,
    subject: str,
    name: str,
    build_revision_no: int,
) -> KnowledgeUnit:
    normalized_name = normalize_name(name)
    existing = knowledge_unit_repo.find_knowledge_unit_by_normalized_name(
        session,
        subject,
        normalized_name,
        "concept",
    )
    if existing is not None:
        existing.status = "active"
        existing.build_revision_no = build_revision_no
        existing.updated_at = utcnow()
        session.add(existing)
        session.flush()
        return existing
    return knowledge_unit_repo.create_knowledge_unit(
        session,
        KnowledgeUnit(
            subject=subject,
            knowledge_unit_type="concept",
            canonical_name=name,
            normalized_name=normalized_name,
            summary=f"Markdown referenced concept: {name}.",
            type_source="manual",
            type_confidence=0.9,
            status="active",
            build_revision_no=build_revision_no,
        ),
        auto_commit=False,
    )


def _find_structural_parent_item(
    units: list[MarkdownKnowledgeUnit],
    item: MarkdownKnowledgeUnit,
) -> MarkdownKnowledgeUnit | None:
    parent: MarkdownKnowledgeUnit | None = None
    for candidate in units:
        if candidate.line_no >= item.line_no:
            break
        if candidate.heading_level >= item.heading_level:
            continue
        parent = candidate
    return parent


def _build_structural_edge(
    *,
    item: MarkdownKnowledgeUnit,
    item_unit: KnowledgeUnit,
    parent_item: MarkdownKnowledgeUnit,
    parent_unit: KnowledgeUnit,
) -> dict[str, object] | None:
    if item_unit.id is None or parent_unit.id is None or item_unit.id == parent_unit.id:
        return None

    item_type = normalize_knowledge_unit_type(item.knowledge_unit_type)
    parent_type = normalize_knowledge_unit_type(parent_item.knowledge_unit_type)

    if item_type in {"example", "exercise"} and parent_type in {"concept", "method", "theorem", "formula"}:
        return {
            "source_node_id": item_unit.id,
            "target_node_id": parent_unit.id,
            "edge_type": "example_of",
            "description": f"{item_unit.canonical_name} exemplifies {parent_unit.canonical_name}.",
        }

    return {
        "source_node_id": item_unit.id,
        "target_node_id": parent_unit.id,
        "edge_type": "derivation",
        "description": f"{item_unit.canonical_name} is a subtopic of {parent_unit.canonical_name}.",
    }


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
    embeddings = _run_async(aembed_texts([candidate_text, *existing_texts]))
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
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: list[object] = []
    error: list[BaseException] = []

    def _runner() -> None:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            result.append(loop.run_until_complete(coro))
        except BaseException as exc:  # pragma: no cover - defensive bridge
            error.append(exc)
        finally:
            asyncio.set_event_loop(None)
            loop.close()

    import threading

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result[0] if result else None


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
