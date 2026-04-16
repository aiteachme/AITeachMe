"""Knowledge graph query use-cases."""

from __future__ import annotations

from collections import deque

import structlog
from sqlmodel import Session

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
    KnowledgeSubgraphResponse,
    KnowledgeUnitDetailResponse,
    KnowledgeUnitResponse,
    NodeRevisionItem,
)

logger = structlog.get_logger()


class KnowledgeGraphQueryService:
    """Query-oriented operations over one subject's knowledge graph."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def _to_unit_response(self, knowledge_unit: KnowledgeUnit) -> KnowledgeUnitResponse:
        return KnowledgeUnitResponse(
            id=knowledge_unit.id,  # type: ignore[arg-type]
            subject=knowledge_unit.subject,
            node_type=knowledge_unit.node_type,
            canonical_name=knowledge_unit.canonical_name,
            status=knowledge_unit.status,
            confidence=knowledge_unit.confidence,
            type_confidence=knowledge_unit.type_confidence,
            type_source=knowledge_unit.type_source,
            created_at=knowledge_unit.created_at,
            updated_at=knowledge_unit.updated_at,
        )

    def _require_unit(self, subject: str, knowledge_unit_id: int) -> KnowledgeUnit:
        unit = self._session.get(KnowledgeUnit, knowledge_unit_id)
        if unit is None or unit.subject != subject:
            raise KnowledgeUnitNotFoundError(knowledge_unit_id)
        return unit

    def _to_relation_response(self, edge) -> KnowledgeRelationResponse:
        source = self._session.get(KnowledgeUnit, edge.source_node_id)
        target = self._session.get(KnowledgeUnit, edge.target_node_id)
        return KnowledgeRelationResponse(
            id=edge.id,  # type: ignore[arg-type]
            subject=edge.subject,
            source_node_id=edge.source_node_id,
            source_node_name=source.canonical_name if source else f"node#{edge.source_node_id}",
            source_node_type=source.node_type if source else "unknown",
            target_node_id=edge.target_node_id,
            target_node_name=target.canonical_name if target else f"node#{edge.target_node_id}",
            target_node_type=target.node_type if target else "unknown",
            edge_type=edge.edge_type,
            description=edge.description,
            weight=edge.weight,
            confidence=edge.confidence,
        )

    def list_knowledge_units(
        self,
        *,
        subject: str,
        knowledge_unit_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> PaginatedData[KnowledgeUnitResponse]:
        offset = (page - 1) * size
        knowledge_units, total = knowledge_unit_repo.list_knowledge_units_by_subject(
            self._session,
            subject,
            knowledge_unit_type=knowledge_unit_type,
            limit=size,
            offset=offset,
        )
        items = [self._to_unit_response(knowledge_unit) for knowledge_unit in knowledge_units]
        return build_paginated_data(items=items, page=page, size=size, total=total)

    def get_graph_nodes(
        self,
        *,
        subject: str,
        node_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> PaginatedData[KnowledgeUnitResponse]:
        """Backward-compatible wrapper for list_knowledge_units."""
        return self.list_knowledge_units(
            subject=subject,
            knowledge_unit_type=node_type,
            page=page,
            size=size,
        )

    def get_knowledge_unit_detail(
        self,
        *,
        subject: str,
        knowledge_unit_id: int,
    ) -> KnowledgeUnitDetailResponse:
        result = knowledge_unit_repo.get_knowledge_unit_with_current_revision(self._session, knowledge_unit_id)
        if result is None:
            raise KnowledgeUnitNotFoundError(knowledge_unit_id)

        node, revision = result
        if node.subject != subject:
            raise KnowledgeUnitNotFoundError(knowledge_unit_id)

        current_rev = NodeRevisionItem(
            title=revision.title,
            summary=revision.summary,
            body=revision.body,
        )

        aliases_raw = knowledge_unit_repo.list_aliases_by_knowledge_unit(self._session, knowledge_unit_id)
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

        evidence_raw = knowledge_relation_repo.list_evidence_by_entity(self._session, "node", knowledge_unit_id)
        evidence = [
            EvidenceSummary(
                id=item.id,  # type: ignore[arg-type]
                document_id=item.document_id,
                chunk_id=item.chunk_id,
                quote_text=item.quote_text,
                evidence_role=item.evidence_role,
                field_scope=item.field_scope,
                confidence=item.confidence,
            )
            for item in evidence_raw
        ]

        edges_raw = knowledge_relation_repo.list_edges_by_knowledge_unit(self._session, knowledge_unit_id)
        incident_edges: list[IncidentEdgeItem] = []
        for edge in edges_raw:
            if edge.source_node_id == knowledge_unit_id:
                other_id = edge.target_node_id
                direction = "outgoing"
            else:
                other_id = edge.source_node_id
                direction = "incoming"

            other_node = self._session.get(KnowledgeUnit, other_id)
            other_name = other_node.canonical_name if other_node else f"node#{other_id}"
            other_type = other_node.node_type if other_node else "unknown"
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
            subject=node.subject,
            node_type=node.node_type,
            canonical_name=node.canonical_name,
            normalized_name=node.normalized_name,
            status=node.status,
            confidence=node.confidence,
            type_confidence=node.type_confidence,
            type_source=node.type_source,
            current_revision=current_rev,
            aliases=aliases,
            evidence=evidence,
            incident_edges=incident_edges,
            created_at=node.created_at,
            updated_at=node.updated_at,
        )

    def get_graph_node_detail(
        self,
        *,
        subject: str,
        node_id: int,
    ) -> KnowledgeUnitDetailResponse:
        """Backward-compatible wrapper for get_knowledge_unit_detail."""
        return self.get_knowledge_unit_detail(subject=subject, knowledge_unit_id=node_id)

    def get_full_graph(
        self,
        *,
        subject: str,
    ) -> FullGraphResponse:
        nodes_raw, _ = knowledge_unit_repo.list_knowledge_units_by_subject(
            self._session,
            subject,
            limit=5000,
            offset=0,
        )
        edges_raw = knowledge_relation_repo.list_all_edges_by_subject(self._session, subject)

        nodes = [self._to_unit_response(node) for node in nodes_raw]
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

    def list_knowledge_unit_relations(
        self,
        *,
        subject: str,
        knowledge_unit_id: int,
        direction: str = "both",
        edge_type: str | None = None,
    ) -> list[KnowledgeRelationResponse]:
        self._require_unit(subject, knowledge_unit_id)
        edges = knowledge_relation_repo.list_edges_by_knowledge_unit(self._session, knowledge_unit_id)
        filtered = []
        for edge in edges:
            if edge.subject != subject:
                continue
            if edge_type and edge.edge_type != edge_type:
                continue
            if direction == "incoming" and edge.target_node_id != knowledge_unit_id:
                continue
            if direction == "outgoing" and edge.source_node_id != knowledge_unit_id:
                continue
            filtered.append(self._to_relation_response(edge))
        return filtered

    def find_knowledge_path(
        self,
        *,
        subject: str,
        source_knowledge_unit_id: int,
        target_knowledge_unit_id: int,
        edge_type: str | None = None,
        max_depth: int = 4,
    ) -> KnowledgePathResponse:
        self._require_unit(subject, source_knowledge_unit_id)
        self._require_unit(subject, target_knowledge_unit_id)
        if source_knowledge_unit_id == target_knowledge_unit_id:
            unit = self._require_unit(subject, source_knowledge_unit_id)
            return KnowledgePathResponse(found=True, nodes=[self._to_unit_response(unit)], edges=[])

        edges = [
            edge
            for edge in knowledge_relation_repo.list_all_edges_by_subject(self._session, subject)
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
            self._to_unit_response(unit)
            for unit_id in node_ids
            if (unit := self._session.get(KnowledgeUnit, unit_id)) is not None
        ]
        return KnowledgePathResponse(
            found=True,
            nodes=nodes,
            edges=[self._to_relation_response(edge) for edge in path_edges],
        )

    def get_focus_subgraph(
        self,
        *,
        subject: str,
        center_knowledge_unit_id: int | None = None,
        topic: str | None = None,
        edge_type: str | None = None,
        hops: int = 1,
        limit: int = 80,
    ) -> KnowledgeSubgraphResponse:
        all_edges = knowledge_relation_repo.list_all_edges_by_subject(self._session, subject)
        if edge_type:
            all_edges = [edge for edge in all_edges if edge.edge_type == edge_type]

        center_ids: set[int] = set()
        if center_knowledge_unit_id is not None:
            self._require_unit(subject, center_knowledge_unit_id)
            center_ids.add(center_knowledge_unit_id)
        if topic:
            topic_text = topic.casefold()
            units, _ = knowledge_unit_repo.list_knowledge_units_by_subject(
                self._session,
                subject,
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
                    or topic_text in unit.node_type.casefold()
                )
            )
        if not center_ids:
            units, _ = knowledge_unit_repo.list_knowledge_units_by_subject(
                self._session,
                subject,
                status="active",
                limit=limit,
                offset=0,
            )
            nodes = [self._to_unit_response(unit) for unit in units]
            node_ids = {unit.id for unit in units if unit.id is not None}
            return KnowledgeSubgraphResponse(
                nodes=nodes,
                edges=[
                    self._to_relation_response(edge)
                    for edge in all_edges
                    if edge.source_node_id in node_ids and edge.target_node_id in node_ids
                ][:limit],
                center_knowledge_unit_id=None,
            )

        selected_ids = set(center_ids)
        frontier = set(center_ids)
        for _ in range(max(0, hops)):
            next_frontier: set[int] = set()
            for edge in all_edges:
                if edge.source_node_id in frontier:
                    next_frontier.add(edge.target_node_id)
                if edge.target_node_id in frontier:
                    next_frontier.add(edge.source_node_id)
            next_frontier -= selected_ids
            selected_ids.update(next_frontier)
            frontier = next_frontier
            if len(selected_ids) >= limit or not frontier:
                break
        selected_ids = set(list(selected_ids)[:limit])

        nodes = [
            self._to_unit_response(unit)
            for unit_id in selected_ids
            if (unit := self._session.get(KnowledgeUnit, unit_id)) is not None
        ]
        sub_edges = [
            edge
            for edge in all_edges
            if edge.source_node_id in selected_ids and edge.target_node_id in selected_ids
        ][:limit]
        return KnowledgeSubgraphResponse(
            nodes=nodes,
            edges=[self._to_relation_response(edge) for edge in sub_edges],
            center_knowledge_unit_id=center_knowledge_unit_id,
        )

    def explain_relation_path(
        self,
        *,
        subject: str,
        source_knowledge_unit_id: int,
        target_knowledge_unit_id: int,
        edge_type: str | None = None,
        max_depth: int = 3,
    ) -> KnowledgeRelationExplanationResponse:
        path = self.find_knowledge_path(
            subject=subject,
            source_knowledge_unit_id=source_knowledge_unit_id,
            target_knowledge_unit_id=target_knowledge_unit_id,
            edge_type=edge_type,
            max_depth=max_depth,
        )
        evidence_items: list[KnowledgeRelationEvidenceItem] = []
        for edge in path.edges:
            evidence_raw = knowledge_relation_repo.list_evidence_by_entity(self._session, "edge", edge.id)
            evidence = [
                EvidenceSummary(
                    id=item.id,  # type: ignore[arg-type]
                    document_id=item.document_id,
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
        self,
        *,
        subject: str,
        chunk_id: int,
    ) -> ChunkContextResponse:
        chunk = knowledge_repo.get_chunk_by_id(self._session, chunk_id)
        if chunk is None:
            raise KnowledgeChunkNotFoundError(chunk_id)

        document = knowledge_repo.get_document_by_id(self._session, chunk.document_id)
        if document is None or document.subject != subject:
            raise KnowledgeChunkNotFoundError(chunk_id)

        return ChunkContextResponse(
            chunk_id=chunk.id,  # type: ignore[arg-type]
            document_id=document.id,  # type: ignore[arg-type]
            document_title=document.filename,
            chunk_title=chunk.title,
            chunk_header_path=chunk.header_path,
            chunk_content=chunk.content,
        )


def get_graph_nodes(
    session: Session,
    *,
    subject: str,
    node_type: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PaginatedData[KnowledgeUnitResponse]:
    return KnowledgeGraphQueryService(session).get_graph_nodes(
        subject=subject,
        node_type=node_type,
        page=page,
        size=size,
    )


def get_knowledge_units(
    session: Session,
    *,
    subject: str,
    knowledge_unit_type: str | None = None,
    page: int = 1,
    size: int = 20,
) -> PaginatedData[KnowledgeUnitResponse]:
    return KnowledgeGraphQueryService(session).list_knowledge_units(
        subject=subject,
        knowledge_unit_type=knowledge_unit_type,
        page=page,
        size=size,
    )


def get_graph_node_detail(
    session: Session,
    *,
    subject: str,
    node_id: int,
) -> KnowledgeUnitDetailResponse:
    return KnowledgeGraphQueryService(session).get_graph_node_detail(
        subject=subject,
        node_id=node_id,
    )


def get_knowledge_unit_detail(
    session: Session,
    *,
    subject: str,
    knowledge_unit_id: int,
) -> KnowledgeUnitDetailResponse:
    return KnowledgeGraphQueryService(session).get_knowledge_unit_detail(
        subject=subject,
        knowledge_unit_id=knowledge_unit_id,
    )


def get_full_graph(
    session: Session,
    *,
    subject: str,
) -> FullGraphResponse:
    return KnowledgeGraphQueryService(session).get_full_graph(subject=subject)


def get_chunk_context(
    session: Session,
    *,
    subject: str,
    chunk_id: int,
) -> ChunkContextResponse:
    return KnowledgeGraphQueryService(session).get_chunk_context(
        subject=subject,
        chunk_id=chunk_id,
    )


def get_knowledge_unit_relations(
    session: Session,
    *,
    subject: str,
    knowledge_unit_id: int,
    direction: str = "both",
    edge_type: str | None = None,
) -> list[KnowledgeRelationResponse]:
    return KnowledgeGraphQueryService(session).list_knowledge_unit_relations(
        subject=subject,
        knowledge_unit_id=knowledge_unit_id,
        direction=direction,
        edge_type=edge_type,
    )


def find_knowledge_path(
    session: Session,
    *,
    subject: str,
    source_knowledge_unit_id: int,
    target_knowledge_unit_id: int,
    edge_type: str | None = None,
    max_depth: int = 4,
) -> KnowledgePathResponse:
    return KnowledgeGraphQueryService(session).find_knowledge_path(
        subject=subject,
        source_knowledge_unit_id=source_knowledge_unit_id,
        target_knowledge_unit_id=target_knowledge_unit_id,
        edge_type=edge_type,
        max_depth=max_depth,
    )


def get_focus_subgraph(
    session: Session,
    *,
    subject: str,
    center_knowledge_unit_id: int | None = None,
    topic: str | None = None,
    edge_type: str | None = None,
    hops: int = 1,
    limit: int = 80,
) -> KnowledgeSubgraphResponse:
    return KnowledgeGraphQueryService(session).get_focus_subgraph(
        subject=subject,
        center_knowledge_unit_id=center_knowledge_unit_id,
        topic=topic,
        edge_type=edge_type,
        hops=hops,
        limit=limit,
    )


def explain_relation_path(
    session: Session,
    *,
    subject: str,
    source_knowledge_unit_id: int,
    target_knowledge_unit_id: int,
    edge_type: str | None = None,
    max_depth: int = 3,
) -> KnowledgeRelationExplanationResponse:
    return KnowledgeGraphQueryService(session).explain_relation_path(
        subject=subject,
        source_knowledge_unit_id=source_knowledge_unit_id,
        target_knowledge_unit_id=target_knowledge_unit_id,
        edge_type=edge_type,
        max_depth=max_depth,
    )


__all__ = [
    "KnowledgeGraphQueryService",
    "get_chunk_context",
    "get_full_graph",
    "get_graph_node_detail",
    "get_graph_nodes",
    "get_focus_subgraph",
    "get_knowledge_unit_detail",
    "get_knowledge_unit_relations",
    "get_knowledge_units",
    "find_knowledge_path",
    "explain_relation_path",
]

