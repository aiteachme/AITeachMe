"""Knowledge graph build use-cases.

These methods are migration-safe wrappers over existing digest build services.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session

from app.models.subject import Subject
from app.schemas.knowledge import DocGenBuildData, DocGenGetResponse


class KnowledgeGraphBuildService:
    """Build-oriented operations for the knowledge graph domain."""

    def __init__(self, session: Session) -> None:
        self._session = session

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
        from app.workflows.digest.application.knowledge_docs.digest_service import trigger_docgen_build

        return trigger_docgen_build(
            self._session,
            subject=subject,
            user_id=user_id,
            file_uids=file_uids,
            prompt=prompt,
            embedding_resolution=embedding_resolution,
            confirmed_plan_id=confirmed_plan_id,
            build_type=build_type,
        )

    def get_build_result(self, *, subject: str) -> DocGenGetResponse:
        from app.workflows.digest.application.knowledge_docs.digest_service import get_docgen_result

        return get_docgen_result(self._session, subject=subject)

    async def run_graph_build_background(
        self,
        *,
        subject: str,
        file_ids: list[int],
        prompt: str | None,
        requested_at: datetime,
    ) -> None:
        from app.workflows.digest.application.knowledge_graph.digest_service import run_graph_build_background

        await run_graph_build_background(
            subject=subject,
            file_ids=file_ids,
            prompt=prompt,
            requested_at=requested_at,
        )

    async def run_graph_digest_background(
        self,
        *,
        subject: str,
        file_ids: list[int],
    ) -> None:
        from app.workflows.digest.application.knowledge_graph.digest_service import run_graph_digest_background

        await run_graph_digest_background(subject=subject, file_ids=file_ids)


__all__ = ["KnowledgeGraphBuildService"]
