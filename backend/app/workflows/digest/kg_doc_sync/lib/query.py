"""Knowledge graph query use-cases."""

from __future__ import annotations

import json
from collections import defaultdict, deque

from sqlmodel import Session, func, select

from app.models.knowledge_doc import KnowledgeDocument
from app.models.knowledge_relation import KnowledgeEdge
from app.models.knowledge_graph_sync import KnowledgeGraphSourceRef, KnowledgeGraphSyncRun
from app.models.knowledge_taxonomy import (
    LEGACY_KNOWLEDGE_UNIT_TYPE_MAP,
    knowledge_unit_type_label,
    normalize_generated_knowledge_unit_type,
    normalize_knowledge_unit_type,
    relation_type_label,
)
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

_SUPPRESSED_GRAPH_NODE_TYPES = {"resource"}
_SUPPRESSED_GRAPH_DB_NODE_TYPES = _SUPPRESSED_GRAPH_NODE_TYPES | {
    legacy_type
    for legacy_type, normalized_type in LEGACY_KNOWLEDGE_UNIT_TYPE_MAP.items()
    if normalized_type in _SUPPRESSED_GRAPH_NODE_TYPES
}


def _display_knowledge_unit_type(knowledge_unit: KnowledgeUnit | None) -> str:
    if knowledge_unit is None:
        return "unknown"
    return normalize_generated_knowledge_unit_type(
        knowledge_unit.knowledge_unit_type,
        name=knowledge_unit.canonical_name,
        summary=knowledge_unit.summary or knowledge_unit.body or knowledge_unit.body_markdown,
    )


def _to_unit_response(knowledge_unit: KnowledgeUnit) -> KnowledgeUnitResponse:
    display_type = _display_knowledge_unit_type(knowledge_unit)
    return KnowledgeUnitResponse(
        id=knowledge_unit.id,  # type: ignore[arg-type]
        course_id=knowledge_unit.course_id,
        knowledge_unit_type=display_type,
        knowledge_unit_type_label=knowledge_unit_type_label(display_type),
        canonical_name=knowledge_unit.canonical_name,
        status=knowledge_unit.status,
        confidence=knowledge_unit.confidence,
        type_confidence=knowledge_unit.type_confidence,
        type_source=knowledge_unit.type_source,
        created_at=knowledge_unit.created_at,
        updated_at=knowledge_unit.updated_at,
    )


def _require_unit(session: Session, course_id: str, knowledge_unit_id: int) -> KnowledgeUnit:
    unit = session.get(KnowledgeUnit, knowledge_unit_id)
    if unit is None or unit.course_id != course_id:
        raise KnowledgeUnitNotFoundError(knowledge_unit_id)
    return unit


def _is_visible_graph_unit(unit: KnowledgeUnit) -> bool:
    return (
        unit.status == "active"
        and normalize_knowledge_unit_type(unit.knowledge_unit_type) not in _SUPPRESSED_GRAPH_NODE_TYPES
    )


def _visible_graph_unit_filters(course_id: str):
    normalized_type_expr = func.lower(func.coalesce(KnowledgeUnit.knowledge_unit_type, ""))
    return [
        KnowledgeUnit.course_id == course_id,
        KnowledgeUnit.status == "active",
        normalized_type_expr.not_in(_SUPPRESSED_GRAPH_DB_NODE_TYPES),
    ]


def _list_visible_graph_units(session: Session, *, course_id: str) -> list[KnowledgeUnit]:
    return [
        unit
        for unit in session.exec(
            select(KnowledgeUnit)
            .where(*_visible_graph_unit_filters(course_id))
            .order_by(KnowledgeUnit.id)
        ).all()
        if unit.id is not None and _is_visible_graph_unit(unit)
    ]


def get_visible_graph_counts(
    session: Session,
    *,
    course_id: str,
) -> tuple[int, int]:
    """Return graph counts using the same visibility rules as graph queries."""

    visible_unit_filters = _visible_graph_unit_filters(course_id)
    node_count = int(session.exec(select(func.count(KnowledgeUnit.id)).where(*visible_unit_filters)).one() or 0)

    visible_ids_subquery = select(KnowledgeUnit.id).where(*visible_unit_filters).subquery()
    visible_ids = select(visible_ids_subquery.c.id)
    edge_count = int(
        session.exec(
            select(func.count(KnowledgeEdge.id)).where(
                KnowledgeEdge.course_id == course_id,
                KnowledgeEdge.status == "active",
                KnowledgeEdge.source_node_id.in_(visible_ids),
                KnowledgeEdge.target_node_id.in_(visible_ids),
            )
        ).one()
        or 0
    )
    return node_count, edge_count


def _filter_edges_to_visible_units(edges: list[KnowledgeEdge], visible_unit_ids: set[int]) -> list[KnowledgeEdge]:
    if not visible_unit_ids:
        return []
    return [
        edge
        for edge in edges
        if int(edge.source_node_id or 0) in visible_unit_ids and int(edge.target_node_id or 0) in visible_unit_ids
    ]


def _to_relation_response(session: Session, edge) -> KnowledgeRelationResponse:
    source = session.get(KnowledgeUnit, edge.source_node_id)
    target = session.get(KnowledgeUnit, edge.target_node_id)
    source_type = _display_knowledge_unit_type(source)
    target_type = _display_knowledge_unit_type(target)
    return KnowledgeRelationResponse(
        id=edge.id,  # type: ignore[arg-type]
        course_id=edge.course_id,
        source_node_id=edge.source_node_id,
        source_node_name=source.canonical_name if source else f"node#{edge.source_node_id}",
        source_node_type=source_type,
        source_node_type_label=knowledge_unit_type_label(source_type),
        target_node_id=edge.target_node_id,
        target_node_name=target.canonical_name if target else f"node#{edge.target_node_id}",
        target_node_type=target_type,
        target_node_type_label=knowledge_unit_type_label(target_type),
        edge_type=edge.edge_type,
        edge_type_label=relation_type_label(edge.edge_type),
        description=edge.description,
        weight=edge.weight,
        confidence=edge.confidence,
    )


def _load_units_by_ids(
    session: Session,
    *,
    course_id: str,
    unit_ids: set[int],
) -> dict[int, KnowledgeUnit]:
    if not unit_ids:
        return {}
    return {
        int(unit.id): unit
        for unit in session.exec(
            select(KnowledgeUnit).where(
                KnowledgeUnit.course_id == course_id,
                KnowledgeUnit.id.in_(unit_ids),
            )
        ).all()
        if unit.id is not None
    }


def _to_relation_response_with_units(
    edge: KnowledgeEdge,
    unit_by_id: dict[int, KnowledgeUnit],
) -> KnowledgeRelationResponse:
    source = unit_by_id.get(int(edge.source_node_id or 0))
    target = unit_by_id.get(int(edge.target_node_id or 0))
    source_type = _display_knowledge_unit_type(source)
    target_type = _display_knowledge_unit_type(target)
    return KnowledgeRelationResponse(
        id=edge.id,  # type: ignore[arg-type]
        course_id=edge.course_id,
        source_node_id=edge.source_node_id,
        source_node_name=source.canonical_name if source else f"node#{edge.source_node_id}",
        source_node_type=source_type,
        source_node_type_label=knowledge_unit_type_label(source_type),
        target_node_id=edge.target_node_id,
        target_node_name=target.canonical_name if target else f"node#{edge.target_node_id}",
        target_node_type=target_type,
        target_node_type_label=knowledge_unit_type_label(target_type),
        edge_type=edge.edge_type,
        edge_type_label=relation_type_label(edge.edge_type),
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
    course_id: str,
    entity_type: str,
    entity_id: int,
    limit: int = 12,
) -> list[KnowledgeGraphSourceRefResponse]:
    refs = list(
        session.exec(
            select(KnowledgeGraphSourceRef)
            .where(
                KnowledgeGraphSourceRef.course_id == course_id,
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
    course_id: str,
    knowledge_unit_type: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PaginatedData[KnowledgeUnitResponse]:
    offset = (page - 1) * size
    normalized_type = normalize_knowledge_unit_type(knowledge_unit_type) if knowledge_unit_type else None
    if normalized_type in _SUPPRESSED_GRAPH_NODE_TYPES:
        return build_paginated_data(items=[], page=page, size=size, total=0)

    filters = [*_visible_graph_unit_filters(course_id)]
    all_units = list(
        session.exec(
            select(KnowledgeUnit)
            .where(*filters)
            .order_by(KnowledgeUnit.id)
        ).all()
    )
    if normalized_type is not None:
        all_units = [unit for unit in all_units if _display_knowledge_unit_type(unit) == normalized_type]
    total = len(all_units)
    knowledge_units = all_units[offset: offset + size]
    items = [_to_unit_response(knowledge_unit) for knowledge_unit in knowledge_units]
    return build_paginated_data(items=items, page=page, size=size, total=total)


def get_knowledge_unit_detail(
    session: Session,
    *,
    course_id: str,
    knowledge_unit_id: int,
) -> KnowledgeUnitDetailResponse:
    result = knowledge_unit_repo.get_knowledge_unit_with_current_revision(session, knowledge_unit_id)
    if result is None:
        raise KnowledgeUnitNotFoundError(knowledge_unit_id)

    node, revision = result
    if node.course_id != course_id or not _is_visible_graph_unit(node):
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
        if edge.course_id != course_id:
            continue
        if edge.source_node_id == knowledge_unit_id:
            other_id = edge.target_node_id
            direction = "outgoing"
        else:
            other_id = edge.source_node_id
            direction = "incoming"

        other_node = session.get(KnowledgeUnit, other_id)
        if other_node is None or not _is_visible_graph_unit(other_node):
            continue
        other_name = other_node.canonical_name
        other_type = _display_knowledge_unit_type(other_node)
        incident_edges.append(
            IncidentEdgeItem(
                id=edge.id,  # type: ignore[arg-type]
                edge_type=edge.edge_type,
                edge_type_label=relation_type_label(edge.edge_type),
                direction=direction,
                other_node_id=other_id,
                other_node_name=other_name,
                other_node_type=other_type,
                other_node_type_label=knowledge_unit_type_label(other_type),
                confidence=edge.confidence,
            )
        )

    display_type = _display_knowledge_unit_type(node)
    return KnowledgeUnitDetailResponse(
        id=node.id,  # type: ignore[arg-type]
        course_id=node.course_id,
        knowledge_unit_type=display_type,
        knowledge_unit_type_label=knowledge_unit_type_label(display_type),
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
            course_id=course_id,
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
    course_id: str,
) -> FullGraphResponse:
    nodes_raw = _list_visible_graph_units(session, course_id=course_id)
    visible_node_ids = {int(node.id) for node in nodes_raw if node.id is not None}
    edges_raw = _filter_edges_to_visible_units(
        knowledge_relation_repo.list_all_edges_by_course(session, course_id),
        visible_node_ids,
    )

    nodes = [_to_unit_response(node) for node in nodes_raw]
    edges = [
        GraphEdgeResponse(
            id=edge.id,  # type: ignore[arg-type]
            source_node_id=edge.source_node_id,
            target_node_id=edge.target_node_id,
            edge_type=edge.edge_type,
            edge_type_label=relation_type_label(edge.edge_type),
            weight=edge.weight,
            confidence=edge.confidence,
        )
        for edge in edges_raw
    ]
    return FullGraphResponse(nodes=nodes, edges=edges)


def get_knowledge_unit_relations(
    session: Session,
    *,
    course_id: str,
    knowledge_unit_id: int,
    direction: str = "both",
    edge_type: str | None = None,
) -> list[KnowledgeRelationResponse]:
    unit = _require_unit(session, course_id, knowledge_unit_id)
    if not _is_visible_graph_unit(unit):
        raise KnowledgeUnitNotFoundError(knowledge_unit_id)
    edges = knowledge_relation_repo.list_edges_by_knowledge_unit(session, knowledge_unit_id)
    filtered = []
    for edge in edges:
        if edge.course_id != course_id:
            continue
        if edge_type and edge.edge_type != edge_type:
            continue
        if direction == "incoming" and edge.target_node_id != knowledge_unit_id:
            continue
        if direction == "outgoing" and edge.source_node_id != knowledge_unit_id:
            continue
        source = session.get(KnowledgeUnit, edge.source_node_id)
        target = session.get(KnowledgeUnit, edge.target_node_id)
        if source is None or target is None or not _is_visible_graph_unit(source) or not _is_visible_graph_unit(target):
            continue
        filtered.append(_to_relation_response_with_units(edge, {int(source.id or 0): source, int(target.id or 0): target}))
    return filtered


def find_knowledge_path(
    session: Session,
    *,
    course_id: str,
    source_knowledge_unit_id: int,
    target_knowledge_unit_id: int,
    edge_type: str | None = None,
    max_depth: int = 4,
) -> KnowledgePathResponse:
    source_unit = _require_unit(session, course_id, source_knowledge_unit_id)
    target_unit = _require_unit(session, course_id, target_knowledge_unit_id)
    if not _is_visible_graph_unit(source_unit) or not _is_visible_graph_unit(target_unit):
        return KnowledgePathResponse(found=False)
    if source_knowledge_unit_id == target_knowledge_unit_id:
        return KnowledgePathResponse(found=True, nodes=[_to_unit_response(source_unit)], edges=[])

    visible_node_ids = {int(unit.id) for unit in _list_visible_graph_units(session, course_id=course_id)}
    edges = [
        edge
        for edge in _filter_edges_to_visible_units(
            knowledge_relation_repo.list_all_edges_by_course(session, course_id),
            visible_node_ids,
        )
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
    course_id: str,
    center_knowledge_unit_id: int | None = None,
    topic: str | None = None,
    edge_type: str | None = None,
    hops: int = 1,
    limit: int = 80,
) -> KnowledgeSubgraphResponse:
    node_limit = max(1, limit)
    edge_limit = max(node_limit * 3, node_limit)
    visible_units = _list_visible_graph_units(session, course_id=course_id)
    visible_unit_by_id = {int(unit.id): unit for unit in visible_units if unit.id is not None}
    visible_unit_ids = set(visible_unit_by_id)
    center_ids: set[int] = set()
    if center_knowledge_unit_id is not None:
        center_unit = _require_unit(session, course_id, center_knowledge_unit_id)
        if not _is_visible_graph_unit(center_unit):
            return KnowledgeSubgraphResponse(nodes=[], edges=[], center_knowledge_unit_id=center_knowledge_unit_id)
        center_ids.add(center_knowledge_unit_id)
    all_edges = _filter_edges_to_visible_units(
        knowledge_relation_repo.list_all_edges_by_course(session, course_id),
        visible_unit_ids,
    )
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

    if topic:
        topic_text = topic.casefold()
        center_ids.update(
            int(unit.id)
            for unit in visible_units
            if unit.id is not None
            and (
                topic_text in unit.canonical_name.casefold()
                or topic_text in unit.summary.casefold()
                or topic_text in _display_knowledge_unit_type(unit).casefold()
            )
        )

    if not center_ids:
        ordered_units = sorted(
            visible_units,
            key=lambda unit: (-degree.get(int(unit.id or 0), 0), int(unit.id or 0)),
        )
        selected_order: list[int] = []
        selected_ids: set[int] = set()

        def _append_selected(unit_id: int) -> None:
            if unit_id <= 0 or unit_id in selected_ids or len(selected_order) >= node_limit:
                return
            selected_ids.add(unit_id)
            selected_order.append(unit_id)

        for unit in ordered_units:
            unit_id = int(unit.id or 0)
            if unit_id <= 0 or len(selected_order) >= node_limit:
                continue
            _append_selected(unit_id)
            for neighbor_id in sorted(adjacency.get(unit_id, set()), key=lambda item: (-degree.get(item, 0), item)):
                _append_selected(neighbor_id)
                if len(selected_order) >= node_limit:
                    break
            if len(selected_order) >= node_limit:
                break
        if not selected_ids:
            selected_order = [int(unit.id) for unit in visible_units[:node_limit] if unit.id is not None]
            selected_ids = set(selected_order)
        node_ids = set(selected_order[:node_limit])
        unit_by_id = _load_units_by_ids(session, course_id=course_id, unit_ids=node_ids)
        ordered_node_ids = [unit_id for unit_id in selected_order if unit_id in unit_by_id]
        if not ordered_node_ids:
            ordered_node_ids = sorted(unit_by_id)
        sub_edges = [
            edge
            for edge in all_edges
            if edge.source_node_id in node_ids and edge.target_node_id in node_ids
        ][:edge_limit]
        return KnowledgeSubgraphResponse(
            nodes=[_to_unit_response(unit_by_id[unit_id]) for unit_id in ordered_node_ids],
            edges=[_to_relation_response_with_units(edge, unit_by_id) for edge in sub_edges],
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
        if len(selected_ids) >= node_limit or not frontier:
            break
    selected_ids = set(sorted(selected_ids, key=lambda item: (-degree.get(item, 0), item))[:node_limit])

    sub_edges = [
        edge
        for edge in all_edges
        if edge.source_node_id in selected_ids and edge.target_node_id in selected_ids
    ][:edge_limit]
    unit_by_id = _load_units_by_ids(session, course_id=course_id, unit_ids=selected_ids)
    return KnowledgeSubgraphResponse(
        nodes=[_to_unit_response(unit_by_id[unit_id]) for unit_id in sorted(unit_by_id)],
        edges=[_to_relation_response_with_units(edge, unit_by_id) for edge in sub_edges],
        center_knowledge_unit_id=center_knowledge_unit_id,
    )


def explain_relation_path(
    session: Session,
    *,
    course_id: str,
    source_knowledge_unit_id: int,
    target_knowledge_unit_id: int,
    edge_type: str | None = None,
    max_depth: int = 3,
) -> KnowledgeRelationExplanationResponse:
    path = find_knowledge_path(
        session,
        course_id=course_id,
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
                edge_type_label=relation_type_label(edge.edge_type),
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
    course_id: str,
    chunk_id: int,
) -> ChunkContextResponse:
    chunk = knowledge_repo.get_chunk_by_id(session, chunk_id)
    if chunk is None:
        raise KnowledgeChunkNotFoundError(chunk_id)

    document = knowledge_repo.get_document_by_id(session, chunk.file_id)
    if document is None or chunk.course_id != course_id:
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
    "get_visible_graph_counts",
]
