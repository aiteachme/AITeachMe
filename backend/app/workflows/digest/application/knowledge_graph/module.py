"""Knowledge graph façade module.

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
    KnowledgeNodeDetailResponse,
    KnowledgeNodeResponse,
)
from app.workflows.digest.application.knowledge_graph.build import KnowledgeGraphBuildService
from app.workflows.digest.application.knowledge_graph.query import KnowledgeGraphQueryService


class KnowledgeGraphModule:
    """Domain façade for KG query/build operations."""

    def __init__(self, *, session: Session) -> None:
        self._query = KnowledgeGraphQueryService(session)
        self._build = KnowledgeGraphBuildService(session)

    @property
    def query(self) -> KnowledgeGraphQueryService:
        return self._query

    @property
    def build(self) -> KnowledgeGraphBuildService:
        return self._build

    def list_nodes(
        self,
        *,
        subject: str,
        node_type: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> PaginatedData[KnowledgeNodeResponse]:
        return self._query.get_graph_nodes(
            subject=subject,
            node_type=node_type,
            page=page,
            size=size,
        )

    def get_node_detail(
        self,
        *,
        subject: str,
        node_id: int,
    ) -> KnowledgeNodeDetailResponse:
        return self._query.get_graph_node_detail(subject=subject, node_id=node_id)

    def get_full_graph(self, *, subject: str) -> FullGraphResponse:
        return self._query.get_full_graph(subject=subject)

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
        build_type: str = "graph",
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


__all__ = ["KnowledgeGraphModule"]
