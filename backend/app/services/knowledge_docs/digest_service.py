"""Docs domain adapter for digest services.

This module preserves patchability for tests by syncing selected symbols into
the legacy implementation module before delegation.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session

from app.models.subject import Subject
from app.schemas.knowledge import DocGenBuildData, DocGenGetResponse
import app.services.knowledge.digest_service as _legacy
from app.services.subject_embedding_service import (
    inspect_subject_build_precheck,
    resolve_subject_build_vector_status,
)
from app.utils.docgen_store import (
    acquire_knowledge_build_lock,
    clear_docgen_staging,
    update_knowledge_build_status,
)
from app.repositories.knowledge.knowledge_repo import clear_chunk_vector_metadata


def _sync_patchable_symbols() -> None:
    _legacy.inspect_subject_build_precheck = inspect_subject_build_precheck
    _legacy.resolve_subject_build_vector_status = resolve_subject_build_vector_status
    _legacy.acquire_knowledge_build_lock = acquire_knowledge_build_lock
    _legacy.clear_docgen_staging = clear_docgen_staging
    _legacy.update_knowledge_build_status = update_knowledge_build_status
    _legacy.clear_chunk_vector_metadata = clear_chunk_vector_metadata


def trigger_docgen_build(
    session: Session,
    *,
    subject: Subject,
    user_id: str,
    file_uids: list[str] | None,
    prompt: str | None,
    embedding_resolution: str | None,
    confirmed_plan_id: str | None,
    build_type: str = "all",
) -> tuple[DocGenBuildData, list[int]]:
    _sync_patchable_symbols()
    return _legacy.trigger_docgen_build(
        session,
        subject=subject,
        user_id=user_id,
        file_uids=file_uids,
        prompt=prompt,
        embedding_resolution=embedding_resolution,
        confirmed_plan_id=confirmed_plan_id,
        build_type=build_type,
    )


def get_docgen_result(session: Session, *, subject: str) -> DocGenGetResponse:
    return _legacy.get_docgen_result(session, subject=subject)


async def run_docgen_background(
    *,
    subject: str,
    file_ids: list[int],
    prompt: str | None,
    requested_at: datetime,
    planner_session_id: str | None = None,
    confirmed_plan_id: str | None = None,
    user_id: str | None = None,
) -> None:
    await _legacy.run_docgen_background(
        subject=subject,
        file_ids=file_ids,
        prompt=prompt,
        requested_at=requested_at,
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        user_id=user_id,
    )


async def run_unified_build_background(
    *,
    subject: str,
    file_ids: list[int],
    prompt: str | None,
    requested_at: datetime,
    planner_session_id: str | None = None,
    confirmed_plan_id: str | None = None,
    user_id: str | None = None,
) -> None:
    await _legacy.run_unified_build_background(
        subject=subject,
        file_ids=file_ids,
        prompt=prompt,
        requested_at=requested_at,
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        user_id=user_id,
    )


async def run_graph_digest_background(
    *,
    subject: str,
    file_ids: list[int],
) -> None:
    await _legacy.run_graph_digest_background(subject=subject, file_ids=file_ids)


async def run_graph_build_background(
    *,
    subject: str,
    file_ids: list[int],
    prompt: str | None,
    requested_at: datetime,
) -> None:
    await _legacy.run_graph_build_background(
        subject=subject,
        file_ids=file_ids,
        prompt=prompt,
        requested_at=requested_at,
    )


__all__ = [
    "acquire_knowledge_build_lock",
    "clear_chunk_vector_metadata",
    "clear_docgen_staging",
    "get_docgen_result",
    "inspect_subject_build_precheck",
    "resolve_subject_build_vector_status",
    "run_docgen_background",
    "run_graph_build_background",
    "run_graph_digest_background",
    "run_unified_build_background",
    "trigger_docgen_build",
    "update_knowledge_build_status",
]
