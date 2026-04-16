"""Knowledge graph fa莽ade module.

This is the stable object-oriented entrypoint for knowledge graph operations.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session

from app.models.subject import Subject
from app.schemas.common import PaginatedData
from app.schemas.knowledge import (
    ChunkContextResponse,
    DocGenBuildData,
    DocGenGetResponse,
    FullGraphResponse,
    KnowledgePathResponse,
    KnowledgeRelationExplanationResponse,
    KnowledgeRelationResponse,
    KnowledgeSubgraphResponse,
    KnowledgeUnitDetailResponse,
    KnowledgeUnitResponse,
)
from app.workflows.digest.application.knowledge_graph.build import KnowledgeGraphBuildService
from app.workflows.digest.application.knowledge_graph.query import KnowledgeGraphQueryService


class KnowledgeGraphModule:
    """Unified domain fa莽ade for knowledge graph query/build operations."""

    def __init__(self, *, session: Session) -> None:
        self._query = KnowledgeGraphQueryService(session)
        self._build = KnowledgeGraphBuildService(session)

    @property
    def query(self) -> KnowledgeGraphQueryService:
        return self._query

    @property
    def build(self) -> KnowledgeGraphBuildService:
        return self._build

    def list_knowledge_units(
        self,
        *,
        subject: str,
        knowledge_unit_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> PaginatedData[KnowledgeUnitResponse]:
        return self._query.list_knowledge_units(
            subject=subject,
            knowledge_unit_type=knowledge_unit_type,
            page=page,
            size=size,
        )

    def get_knowledge_unit_detail(
        self,
        *,
        subject: str,
        knowledge_unit_id: int,
    ) -> KnowledgeUnitDetailResponse:
        return self._query.get_knowledge_unit_detail(
            subject=subject,
            knowledge_unit_id=knowledge_unit_id,
        )

    def get_full_graph(self, *, subject: str) -> FullGraphResponse:
        return self._query.get_full_graph(subject=subject)

    def list_knowledge_unit_relations(
        self,
        *,
        subject: str,
        knowledge_unit_id: int,
        direction: str = "both",
        edge_type: str | None = None,
    ) -> list[KnowledgeRelationResponse]:
        return self._query.list_knowledge_unit_relations(
            subject=subject,
            knowledge_unit_id=knowledge_unit_id,
            direction=direction,
            edge_type=edge_type,
        )

    def find_knowledge_path(
        self,
        *,
        subject: str,
        source_knowledge_unit_id: int,
        target_knowledge_unit_id: int,
        edge_type: str | None = None,
        max_depth: int = 4,
    ) -> KnowledgePathResponse:
        return self._query.find_knowledge_path(
            subject=subject,
            source_knowledge_unit_id=source_knowledge_unit_id,
            target_knowledge_unit_id=target_knowledge_unit_id,
            edge_type=edge_type,
            max_depth=max_depth,
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
        return self._query.get_focus_subgraph(
            subject=subject,
            center_knowledge_unit_id=center_knowledge_unit_id,
            topic=topic,
            edge_type=edge_type,
            hops=hops,
            limit=limit,
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
        return self._query.explain_relation_path(
            subject=subject,
            source_knowledge_unit_id=source_knowledge_unit_id,
            target_knowledge_unit_id=target_knowledge_unit_id,
            edge_type=edge_type,
            max_depth=max_depth,
        )

    def get_chunk_context(
        self,
        *,
        subject: str,
        chunk_id: int,
    ) -> ChunkContextResponse:
        return self._query.get_chunk_context(subject=subject, chunk_id=chunk_id)

    def trigger_build(
        self,
        *,
        subject: Subject,
        user_id: str,
        file_uids: list[str] | None,
        prompt: str | None,
        embedding_resolution: str | None,
        confirmed_plan_id: str | None,
        build_type: str = "all",
    ) -> tuple[DocGenBuildData, list[int]]:
        return self._build.trigger_build(
            subject=subject,
            user_id=user_id,
            file_uids=file_uids,
            prompt=prompt,
            embedding_resolution=embedding_resolution,
            confirmed_plan_id=confirmed_plan_id,
            build_type=build_type,
        )

    def get_build_result(self, *, subject: str) -> DocGenGetResponse:
        return self._build.get_build_result(subject=subject)

    async def run_graph_build_background(
        self,
        *,
        subject: str,
        file_ids: list[int],
        prompt: str | None,
        requested_at: datetime,
    ) -> None:
        await self._build.run_graph_build_background(
            subject=subject,
            file_ids=file_ids,
            prompt=prompt,
            requested_at=requested_at,
        )

    async def run_unified_build_background(
        self,
        *,
        subject: str,
        file_ids: list[int],
        prompt: str | None,
        requested_at: datetime,
        planner_session_id: str | None = None,
        confirmed_plan_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        await self._build.run_unified_build_background(
            subject=subject,
            file_ids=file_ids,
            prompt=prompt,
            requested_at=requested_at,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            user_id=user_id,
        )


__all__ = ["KnowledgeGraphModule"]
