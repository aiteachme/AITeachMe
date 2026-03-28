"""Digest build and knowledge-doc generation service helpers."""

from __future__ import annotations

import uuid
from datetime import datetime
import structlog
from sqlmodel import Session

from app.infra.exceptions import (
    NoReadyFilesForDocGenError,
    RawFileNotFoundError,
    SubjectBuildLockConflictError,
)
from app.infra.database import managed_session
from app.models import IngestStatus, TaskStatus
from app.models.raw_file import RawFile
from app.repositories.files_repo import (
    list_all_raw_files_by_subject,
    list_raw_files_by_ids,
    list_raw_files_by_uids,
)
from app.schemas.knowledge import DocGenBuildData, DocGenGetResponse
from app.services.knowledge.docgen_store import (
    KnowledgeBuildLock,
    acquire_knowledge_build_lock,
    clear_docgen_staging,
    read_knowledge_manifest,
    release_knowledge_build_lock,
)
from app.services.presenters import require_id, require_uid
from app.services.upload_support import build_merged_knowledge_base_path
from app.utils.job_helpers import cleanup_pending_by_subject
from app.utils.time import utcnow
from app.workflows.digest.unified import run_unified_digest_build

logger = structlog.get_logger()


def _markdown_ready(raw_file: RawFile) -> bool:
    return (
        raw_file.status == TaskStatus.COMPLETED.value
        and raw_file.ingest_status in (
            IngestStatus.FAST_PARSED.value,       # Phase 1 即可构建，不阻塞
            IngestStatus.ENHANCING.value,          # Phase 2 进行中也可构建
            IngestStatus.READY_FOR_DIGEST.value,
            IngestStatus.ENHANCE_FAILED.value,     # Phase 2 失败，Phase 1 降级可用
        )
        and bool(raw_file.parsed_markdown.strip())
    )


def _clean_prompt(prompt: str | None) -> str | None:
    cleaned = (prompt or "").strip()
    return cleaned or None


def _resolve_requested_raw_files(
    session: Session,
    *,
    subject: str,
    file_uids: list[str] | None,
) -> list[RawFile]:
    if not file_uids:
        return []

    requested_items = list_raw_files_by_uids(session, subject, file_uids)
    found_uids = {require_uid(item.uid, "RawFile.uid") for item in requested_items}
    missing_uids = [file_uid for file_uid in file_uids if file_uid not in found_uids]
    if missing_uids:
        raise RawFileNotFoundError(missing_uids[0])

    order = {file_uid: index for index, file_uid in enumerate(file_uids)}
    return sorted(requested_items, key=lambda item: order[require_uid(item.uid, "RawFile.uid")])


def _select_ready_docgen_files(
    session: Session,
    *,
    subject: str,
    file_uids: list[str] | None,
) -> tuple[list[RawFile], int]:
    all_files = list_all_raw_files_by_subject(session, subject)
    ready_files = [raw_file for raw_file in all_files if raw_file.id is not None and _markdown_ready(raw_file)]
    ready_file_count = len(ready_files)

    if file_uids:
        requested_items = _resolve_requested_raw_files(
            session,
            subject=subject,
            file_uids=file_uids,
        )
        ready_id_set = {require_id(item.id, "RawFile.id") for item in ready_files}
        accepted = [
            item
            for item in requested_items
            if item.id is not None and require_id(item.id, "RawFile.id") in ready_id_set
        ]
    else:
        accepted = ready_files

    if not accepted:
        raise NoReadyFilesForDocGenError(subject)

    return accepted, ready_file_count


def _resolve_file_uids(raw_files: list[RawFile]) -> list[str]:
    return [require_uid(item.uid, "RawFile.uid") for item in raw_files]


def _resolve_file_ids(raw_files: list[RawFile]) -> list[int]:
    return [require_id(item.id, "RawFile.id") for item in raw_files]


def _resolve_file_uids_from_ids(session: Session, *, subject: str, file_ids: list[int]) -> list[str]:
    if not file_ids:
        return []

    raw_files = list_raw_files_by_ids(session, subject, file_ids)
    uid_by_id = {
        require_id(item.id, "RawFile.id"): require_uid(item.uid, "RawFile.uid")
        for item in raw_files
        if item.id is not None
    }
    return [uid_by_id[file_id] for file_id in file_ids if file_id in uid_by_id]


def _new_graph_run_id() -> int:
    return (uuid.uuid4().int % 2_000_000_000) + 1


def _clear_docgen_staging_safely(subject: str) -> None:
    try:
        clear_docgen_staging(subject)
    except Exception:
        logger.exception("knowledge_build_cleanup_failed", subject=subject)


def _cleanup_pending_digest_outputs(subject: str) -> None:
    """Drop stale pending graph/curriculum rows before a new unified build."""

    try:
        with managed_session() as session:
            cleanup_pending_by_subject(session, subject=subject, job_type="graph")
            cleanup_pending_by_subject(session, subject=subject, job_type="curriculum")
    except Exception:
        logger.exception("knowledge_pending_cleanup_failed", subject=subject)


def trigger_docgen_build(
    session: Session,
    *,
    subject: str,
    file_uids: list[str] | None,
    prompt: str | None,
) -> tuple[DocGenBuildData, list[int]]:
    """Acquire the build lock and return accepted source info for doc generation."""

    accepted_files, ready_file_count = _select_ready_docgen_files(
        session,
        subject=subject,
        file_uids=file_uids,
    )
    accepted_file_ids = _resolve_file_ids(accepted_files)
    accepted_file_uids = _resolve_file_uids(accepted_files)
    requested_at = utcnow()
    cleaned_prompt = _clean_prompt(prompt)

    lock = KnowledgeBuildLock(
        requested_at=requested_at,
        source_file_ids=accepted_file_ids,
        prompt=cleaned_prompt,
    )
    if not acquire_knowledge_build_lock(subject, lock):
        raise SubjectBuildLockConflictError(subject)

    clear_docgen_staging(subject)
    logger.info(
        "knowledge_build_requested",
        subject=subject,
        requested_at=requested_at.isoformat(),
        file_count=len(accepted_file_ids),
    )

    return (
        DocGenBuildData(
            accepted_file_uids=accepted_file_uids,
            ready_file_count=ready_file_count,
            prompt=cleaned_prompt,
            requested_at=requested_at,
        ),
        accepted_file_ids,
    )


async def run_graph_digest_background(*, subject: str, file_ids: list[int]) -> None:
    """Run graph digest workflow in background with an ephemeral run id."""

    from app.workflows.digest import run_graph_digest_workflow

    run_id = _new_graph_run_id()
    digest_logger = logger.bind(subject=subject, run_id=run_id)
    try:
        digest_logger.info("graph_digest_background_started")
        result = await run_graph_digest_workflow(subject=subject, job_id=run_id, file_ids=file_ids)
        if result.failed:
            digest_logger.error("graph_digest_background_failed", error=result.error.detail)
            return
        digest_logger.info("graph_digest_background_completed")
    except Exception:
        digest_logger.exception("graph_digest_background_error")


async def run_docgen_background(
    *,
    subject: str,
    file_ids: list[int],
    prompt: str | None,
    requested_at: datetime,
) -> None:
    """Run docgen workflow in background without any job row persistence."""

    from app.workflows.digest import run_docgen_workflow

    build_logger = logger.bind(subject=subject, requested_at=requested_at.isoformat())
    build_logger.info("knowledge_build_started")

    try:
        result = await run_docgen_workflow(
            subject=subject,
            file_ids=file_ids,
            user_prompt=prompt,
            requested_at=requested_at,
        )
        if result.failed:
            _clear_docgen_staging_safely(subject)
            build_logger.error("knowledge_build_failed", error=result.error.detail)
            return
    except Exception:
        _clear_docgen_staging_safely(subject)
        build_logger.exception("knowledge_build_failed")
        return
    finally:
        release_knowledge_build_lock(subject)


async def run_unified_build_background(
    *,
    subject: str,
    file_ids: list[int],
    prompt: str | None,
    requested_at: datetime,
) -> None:
    """Run the unified digest build in background without introducing a new API."""

    build_logger = logger.bind(subject=subject, requested_at=requested_at.isoformat())
    build_logger.info("knowledge_unified_build_started", file_count=len(file_ids))

    try:
        _clear_docgen_staging_safely(subject)
        _cleanup_pending_digest_outputs(subject)
        result = await run_unified_digest_build(
            subject=subject,
            file_ids=file_ids,
            user_prompt=prompt,
            requested_at=requested_at,
        )
        if not result.success:
            _clear_docgen_staging_safely(subject)
            build_logger.error("knowledge_unified_build_failed", error=result.error)
            return

        build_logger.info(
            "knowledge_unified_build_completed",
            doc_count=result.doc_count,
            chunk_count=result.chunk_count,
            new_node_count=result.new_node_count,
            new_edge_count=result.new_edge_count,
            elapsed_ms=result.elapsed_ms,
        )
    except Exception:
        _clear_docgen_staging_safely(subject)
        build_logger.exception("knowledge_unified_build_failed")
        return
    finally:
        release_knowledge_build_lock(subject)


def get_docgen_result(session: Session, *, subject: str) -> DocGenGetResponse:
    """Read the published merged markdown and manifest metadata."""

    merged_path = build_merged_knowledge_base_path(subject)
    manifest = read_knowledge_manifest(subject)
    markdown = merged_path.read_text(encoding="utf-8") if merged_path.exists() else ""

    updated_at: datetime | None = None
    source_file_uids: list[str] = []

    if manifest is not None:
        updated_at = manifest.updated_at
        source_file_uids = _resolve_file_uids_from_ids(
            session,
            subject=subject,
            file_ids=manifest.source_file_ids,
        )
    elif merged_path.exists():
        updated_at = datetime.fromtimestamp(merged_path.stat().st_mtime)

    return DocGenGetResponse(
        exists=bool(merged_path.exists() and markdown.strip()),
        markdown=markdown,
        updated_at=updated_at,
        source_file_uids=source_file_uids,
        prompt=manifest.prompt if manifest is not None else None,
    )


__all__ = [
    "get_docgen_result",
    "run_docgen_background",
    "run_graph_digest_background",
    "run_unified_build_background",
    "trigger_docgen_build",
]
