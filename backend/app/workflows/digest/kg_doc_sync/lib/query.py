"""Knowledge graph query use-cases."""

from __future__ import annotations

import json
from collections import defaultdict, deque

from sqlmodel import Session, select

from app.models.knowledge_doc import KnowledgeDocument
from app.models.knowledge_graph_sync import KnowledgeGraphSourceRef, KnowledgeGraphSyncRun
from app.shared.infra.exceptions import (
    KnowledgeChunkNotFoundError,
    KnowledgeUnitNotFoundError,
)
from app.models.knowledge_unit import KnowledgeUnit
from app.repositories import knowledge_relation_repo, knowledge_repo, knowledge_unit_repo
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.knowledge import (
    AliasItem,
    ChunkContextResponse,
    EvidenceSummary,
    FullGraphResponse,
    GraphEdgeResponse,
    IncidentEdgeItem,
    KnowledgePathResponse,
    KnowledgeRelationEvidenceItem,
    KnowledgeRelationExplanationResponse,
    KnowledgeRelationResponse,
    KnowledgeGraphSourceRefResponse,
    KnowledgeSubgraphResponse,
    KnowledgeUnitDetailResponse,
    KnowledgeUnitResponse,
    NodeRevisionItem,
)


def _to_unit_response(knowledge_unit: KnowledgeUnit) -> KnowledgeUnitResponse:
    return KnowledgeUnitResponse(
        id=knowledge_unit.id,  # type: ignore[arg-type]
        subject_id=knowledge_unit.subject_id,
        knowledge_unit_type=knowledge_unit.knowledge_unit_type,
        canonical_name=knowledge_unit.canonical_name,
        status=knowledge_unit.status,
        confidence=knowledge_unit.confidence,
        type_confidence=knowledge_unit.type_confidence,
        type_source=knowledge_unit.type_source,
        created_at=knowledge_unit.created_at,
        updated_at=knowledge_unit.updated_at,
    )


def _require_unit(session: Session, subject_id: str, knowledge_unit_id: int) -> KnowledgeUnit:
    unit = session.get(KnowledgeUnit, knowledge_unit_id)
    if unit is None or unit.subject_id != subject_id:
        raise KnowledgeUnitNotFoundError(knowledge_unit_id)
    return unit


def _to_relation_response(session: Session, edge) -> KnowledgeRelationResponse:
    source = session.get(KnowledgeUnit, edge.source_node_id)
    target = session.get(KnowledgeUnit, edge.target_node_id)
    return KnowledgeRelationResponse(
        id=edge.id,  # type: ignore[arg-type]
        subject_id=edge.subject_id,
        source_node_id=edge.source_node_id,
        source_node_name=source.canonical_name if source else f"node#{edge.source_node_id}",
        source_node_type=source.knowledge_unit_type if source else "unknown",
        target_node_id=edge.target_node_id,
        target_node_name=target.canonical_name if target else f"node#{edge.target_node_id}",
        target_node_type=target.knowledge_unit_type if target else "unknown",
        edge_type=edge.edge_type,
        description=edge.description,
        weight=edge.weight,
        confidence=edge.confidence,
    )


def _json_string_list(raw: str | None) -> list[str]:
    try:
        payload = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in payload:
        parsed = str(item or "").strip()
        if not parsed or parsed in seen:
            continue
        seen.add(parsed)
        cleaned.append(parsed)
    return cleaned


def _list_source_refs_by_entity(
    session: Session,
    *,
    subject_id: str,
    entity_type: str,
    entity_id: int,
    limit: int = 12,
) -> list[KnowledgeGraphSourceRefResponse]:
    refs = list(
        session.exec(
            select(KnowledgeGraphSourceRef)
            .where(
                KnowledgeGraphSourceRef.subject_id == subject_id,
                KnowledgeGraphSourceRef.entity_type == entity_type,
                KnowledgeGraphSourceRef.entity_id == entity_id,
            )
            .order_by(KnowledgeGraphSourceRef.id.desc())
            .limit(limit)
        ).all()
    )
    responses: list[KnowledgeGraphSourceRefResponse] = []
    for ref in refs:
        sync_run = session.get(KnowledgeGraphSyncRun, ref.sync_run_id) if ref.sync_run_id is not None else None
        doc = (
            session.get(KnowledgeDocument, ref.knowledge_document_id)
            if ref.knowledge_document_id is not None
            else None
        )
        responses.append(
            KnowledgeGraphSourceRefResponse(
                id=ref.id or 0,
                entity_type=ref.entity_type,
                entity_id=ref.entity_id,
                sync_run_id=ref.sync_run_id,
                knowledge_document_id=ref.knowledge_document_id,
                chapter_index=ref.chapter_index,
                chapter_title=(doc.title if doc is not None else None),
                doc_version_no=(int(sync_run.doc_version_no or 0) if sync_run is not None else 0),
                graph_revision_no=(int(sync_run.graph_revision_no or 0) if sync_run is not None else 0),
                source_kind=ref.source_kind,
                anchor=ref.anchor,
                source_file_ids=_json_string_list(ref.source_file_ids_json),
                quote_text=ref.quote_text,
                confidence=ref.confidence,
                created_at=ref.created_at,
            )
        )
    return responses


def get_knowledge_units(
    session: Session,
    *,
    subject_id: str,
    knowledge_unit_type: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PaginatedData[KnowledgeUnitResponse]:
    offset = (page - 1) * size
    knowledge_units, total = knowledge_unit_repo.list_knowledge_units_by_subject(
        session,
        subject_id,
        knowledge_unit_type=knowledge_unit_type,
        limit=size,
        offset=offset,
    )
    items = [_to_unit_response(knowledge_unit) for knowledge_unit in knowledge_units]
    return build_paginated_data(items=items, page=page, size=size, total=total)


def get_knowledge_unit_detail(
    session: Session,
    *,
    subject_id: str,
    knowledge_unit_id: int,
) -> KnowledgeUnitDetailResponse:
    result = knowledge_unit_repo.get_knowledge_unit_with_current_revision(session, knowledge_unit_id)
    if result is None:
        raise KnowledgeUnitNotFoundError(knowledge_unit_id)

    node, revision = result
    if node.subject_id != subject_id:
        raise KnowledgeUnitNotFoundError(knowledge_unit_id)

    current_rev = NodeRevisionItem(
        title=revision.title,
        summary=revision.summary,
        body=revision.body,
    )

    aliases_raw = knowledge_unit_repo.list_aliases_by_knowledge_unit(session, knowledge_unit_id)
    aliases = [
        AliasItem(
            id=alias.id,  # type: ignore[arg-type]
            alias=alias.alias,
            language=alias.language,
            source=alias.source,
            confidence=alias.confidence,
            is_primary=alias.is_primary,
        )
        for alias in aliases_raw
    ]

    evidence_raw = knowledge_relation_repo.list_evidence_by_entity(session, "node", knowledge_unit_id)
    evidence = [
        EvidenceSummary(
            id=item.id,  # type: ignore[arg-type]
            file_id=item.file_id,
            chunk_id=item.chunk_id,
            quote_text=item.quote_text,
            evidence_role=item.evidence_role,
            field_scope=item.field_scope,
            confidence=item.confidence,
        )
        for item in evidence_raw
    ]

    edges_raw = knowledge_relation_repo.list_edges_by_knowledge_unit(session, knowledge_unit_id)
    incident_edges: list[IncidentEdgeItem] = []
    for edge in edges_raw:
        if edge.source_node_id == knowledge_unit_id:
            other_id = edge.target_node_id
            direction = "outgoing"
        else:
            other_id = edge.source_node_id
            direction = "incoming"

        other_node = session.get(KnowledgeUnit, other_id)
        other_name = other_node.canonical_name if other_node else f"node#{other_id}"
        other_type = other_node.knowledge_unit_type if other_node else "unknown"
        incident_edges.append(
            IncidentEdgeItem(
                id=edge.id,  # type: ignore[arg-type]
                edge_type=edge.edge_type,
                direction=direction,
                other_node_id=other_id,
                other_node_name=other_name,
                other_node_type=other_type,
                confidence=edge.confidence,
            )
        )

    return KnowledgeUnitDetailResponse(
        id=node.id,  # type: ignore[arg-type]
        subject_id=node.subject_id,
        knowledge_unit_type=node.knowledge_unit_type,
        canonical_name=node.canonical_name,
        normalized_name=node.normalized_name,
        status=node.status,
        confidence=node.confidence,
        type_confidence=node.type_confidence,
        type_source=node.type_source,
        current_revision=current_rev,
        aliases=aliases,
        evidence=evidence,
        source_refs=_list_source_refs_by_entity(
            session,
            subject_id=subject_id,
            entity_type="unit",
            entity_id=knowledge_unit_id,
        ),
        incident_edges=incident_edges,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


def get_full_graph(
    session: Session,
    *,
    subject_id: str,
) -> FullGraphResponse:
    nodes_raw, _ = knowledge_unit_repo.list_knowledge_units_by_subject(
        session,
        subject_id,
        limit=5000,
        offset=0,
    )
    edges_raw = knowledge_relation_repo.list_all_edges_by_subject(session, subject_id)

    nodes = [_to_unit_response(node) for node in nodes_raw]
    edges = [
        GraphEdgeResponse(
            id=edge.id,  # type: ignore[arg-type]
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            edge_type=edge.edge_type,
            weight=edge.weight,
            confidence=edge.confidence,
        )
        for edge in edges_raw
    ]
    return FullGraphResponse(nodes=nodes, edges=edges)


def get_knowledge_unit_relations(
    session: Session,
    *,
    subject_id: str,
    knowledge_unit_id: int,
    direction: str = "both",
    edge_type: str | None = None,
) -> list[KnowledgeRelationResponse]:
    _require_unit(session, subject_id, knowledge_unit_id)
    edges = knowledge_relation_repo.list_edges_by_knowledge_unit(session, knowledge_unit_id)
    filtered = []
    for edge in edges:
        if edge.subject_id != subject_id:
            continue
        if edge_type and edge.edge_type != edge_type:
            continue
        if direction == "incoming" and edge.target_node_id != knowledge_unit_id:
            continue
        if direction == "outgoing" and edge.source_node_id != knowledge_unit_id:
            continue
        filtered.append(_to_relation_response(session, edge))
    return filtered


def find_knowledge_path(
    session: Session,
    *,
    subject_id: str,
    source_knowledge_unit_id: int,
    target_knowledge_unit_id: int,
    edge_type: str | None = None,
    max_depth: int = 4,
) -> KnowledgePathResponse:
    _require_unit(session, subject_id, source_knowledge_unit_id)
    _require_unit(session, subject_id, target_knowledge_unit_id)
    if source_knowledge_unit_id == target_knowledge_unit_id:
        unit = _require_unit(session, subject_id, source_knowledge_unit_id)
        return KnowledgePathResponse(found=True, nodes=[_to_unit_response(unit)], edges=[])

    edges = [
        edge
        for edge in knowledge_relation_repo.list_all_edges_by_subject(session, subject_id)
        if edge_type is None or edge.edge_type == edge_type
    ]
    adjacency: dict[int, list[object]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source_node_id, []).append(edge)

    queue = deque([(source_knowledge_unit_id, [])])
    visited = {source_knowledge_unit_id}
    path_edges: list[object] | None = None
    while queue:
        node_id, current_edges = queue.popleft()
        if len(current_edges) >= max_depth:
            continue
        for edge in adjacency.get(node_id, []):
            next_id = edge.target_node_id
            next_edges = [*current_edges, edge]
            if next_id == target_knowledge_unit_id:
                path_edges = next_edges
                queue.clear()
                break
            if next_id not in visited:
                visited.add(next_id)
                queue.append((next_id, next_edges))

    if path_edges is None:
        return KnowledgePathResponse(found=False)

    node_ids = [source_knowledge_unit_id, *[edge.target_node_id for edge in path_edges]]
    nodes = [
        _to_unit_response(unit)
        for unit_id in node_ids
        if (unit := session.get(KnowledgeUnit, unit_id)) is not None
    ]
    return KnowledgePathResponse(
        found=True,
        nodes=nodes,
        edges=[_to_relation_response(session, edge) for edge in path_edges],
    )


def get_focus_subgraph(
    session: Session,
    *,
    subject_id: str,
    center_knowledge_unit_id: int | None = None,
    topic: str | None = None,
    edge_type: str | None = None,
    hops: int = 1,
    limit: int = 80,
) -> KnowledgeSubgraphResponse:
    all_edges = knowledge_relation_repo.list_all_edges_by_subject(session, subject_id)
    if edge_type:
        all_edges = [edge for edge in all_edges if edge.edge_type == edge_type]
    degree: dict[int, int] = defaultdict(int)
    adjacency: dict[int, set[int]] = defaultdict(set)
    for edge in all_edges:
        source_id = int(edge.source_node_id or 0)
        target_id = int(edge.target_node_id or 0)
        if source_id <= 0 or target_id <= 0:
            continue
        degree[source_id] += 1
        degree[target_id] += 1
        adjacency[source_id].add(target_id)
        adjacency[target_id].add(source_id)

    center_ids: set[int] = set()
    if center_knowledge_unit_id is not None:
        _require_unit(session, subject_id, center_knowledge_unit_id)
        center_ids.add(center_knowledge_unit_id)
    if topic:
        topic_text = topic.casefold()
        units, _ = knowledge_unit_repo.list_knowledge_units_by_subject(
            session,
            subject_id,
            status="active",
            limit=limit,
            offset=0,
        )
        center_ids.update(
            unit.id
            for unit in units
            if unit.id is not None
            and (
                topic_text in unit.canonical_name.casefold()
                or topic_text in unit.summary.casefold()
                or topic_text in unit.knowledge_unit_type.casefold()
            )
        )
    if not center_ids:
        units, _ = knowledge_unit_repo.list_knowledge_units_by_subject(
            session,
            subject_id,
            status="active",
            limit=max(limit * 3, limit),
            offset=0,
        )
        ordered_units = sorted(
            units,
            key=lambda unit: (-degree.get(int(unit.id or 0), 0), int(unit.id or 0)),
        )
        selected_ids: set[int] = set()
        for unit in ordered_units:
            unit_id = int(unit.id or 0)
            if unit_id <= 0:
                continue
            selected_ids.add(unit_id)
            for neighbor_id in sorted(adjacency.get(unit_id, set()), key=lambda item: (-degree.get(item, 0), item)):
                selected_ids.add(neighbor_id)
                if len(selected_ids) >= limit:
                    break
            if len(selected_ids) >= limit:
                break
        if not selected_ids:
            selected_ids = {int(unit.id) for unit in units[:limit] if unit.id is not None}
        node_ids = set(sorted(selected_ids)[:limit])
        nodes = [
            _to_unit_response(unit)
            for unit_id in node_ids
            if (unit := session.get(KnowledgeUnit, unit_id)) is not None
        ]
        return KnowledgeSubgraphResponse(
            nodes=nodes,
            edges=[
                _to_relation_response(session, edge)
                for edge in all_edges
                if edge.source_node_id in node_ids and edge.target_node_id in node_ids
            ][:limit],
            center_knowledge_unit_id=None,
        )

    selected_ids = set(center_ids)
    frontier = set(center_ids)
    for _ in range(max(0, hops)):
        next_frontier: set[int] = set()
        for node_id in frontier:
            next_frontier.update(adjacency.get(node_id, set()))
        next_frontier -= selected_ids
        selected_ids.update(next_frontier)
        frontier = next_frontier
        if len(selected_ids) >= limit or not frontier:
            break
    selected_ids = set(sorted(selected_ids, key=lambda item: (-degree.get(item, 0), item))[:limit])

    nodes = [
        _to_unit_response(unit)
        for unit_id in selected_ids
        if (unit := session.get(KnowledgeUnit, unit_id)) is not None
    ]
    sub_edges = [
        edge
        for edge in all_edges
        if edge.source_node_id in selected_ids and edge.target_node_id in selected_ids
    ][:limit]
    return KnowledgeSubgraphResponse(
        nodes=nodes,
        edges=[_to_relation_response(session, edge) for edge in sub_edges],
        center_knowledge_unit_id=center_knowledge_unit_id,
    )


def explain_relation_path(
    session: Session,
    *,
    subject_id: str,
    source_knowledge_unit_id: int,
    target_knowledge_unit_id: int,
    edge_type: str | None = None,
    max_depth: int = 3,
) -> KnowledgeRelationExplanationResponse:
    path = find_knowledge_path(
        session,
        subject_id=subject_id,
        source_knowledge_unit_id=source_knowledge_unit_id,
        target_knowledge_unit_id=target_knowledge_unit_id,
        edge_type=edge_type,
        max_depth=max_depth,
    )
    evidence_items: list[KnowledgeRelationEvidenceItem] = []
    for edge in path.edges:
        evidence_raw = knowledge_relation_repo.list_evidence_by_entity(session, "edge", edge.id)
        evidence = [
            EvidenceSummary(
                id=item.id,  # type: ignore[arg-type]
                file_id=item.file_id,
                chunk_id=item.chunk_id,
                quote_text=item.quote_text,
                evidence_role=item.evidence_role,
                field_scope=item.field_scope,
                confidence=item.confidence,
            )
            for item in evidence_raw
        ]
        evidence_items.append(
            KnowledgeRelationEvidenceItem(
                edge_id=edge.id,
                edge_type=edge.edge_type,
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                description=edge.description,
                evidence=evidence,
            )
        )
    return KnowledgeRelationExplanationResponse(path=path, evidence=evidence_items)


def get_chunk_context(
    session: Session,
    *,
    subject_id: str,
    chunk_id: int,
) -> ChunkContextResponse:
    chunk = knowledge_repo.get_chunk_by_id(session, chunk_id)
    if chunk is None:
        raise KnowledgeChunkNotFoundError(chunk_id)

    document = knowledge_repo.get_document_by_id(session, chunk.file_id)
    if document is None or chunk.subject_id != subject_id:
        raise KnowledgeChunkNotFoundError(chunk_id)

    return ChunkContextResponse(
        chunk_id=chunk.id,  # type: ignore[arg-type]
        file_id=document.id,
        document_title=document.filename,
        chunk_title=chunk.title,
        chunk_header_path=chunk.header_path,
        chunk_content=chunk.content,
    )


__all__ = [
    "explain_relation_path",
    "find_knowledge_path",
    "get_chunk_context",
    "get_focus_subgraph",
    "get_full_graph",
    "get_knowledge_unit_detail",
    "get_knowledge_unit_relations",
    "get_knowledge_units",
]
