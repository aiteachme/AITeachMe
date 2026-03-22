"""Digest build and docs generation service helpers."""

from __future__ import annotations

import asyncio
import json
import traceback
import uuid
from datetime import datetime
from pathlib import Path

import structlog
from sqlmodel import Session, select

from app.core.database import managed_session
from app.core.exceptions import (
    DigestJobNotFoundError,
    NoReadyFilesForDocGenError,
    RawFileNotFoundError,
    SubjectBuildLockConflictError,
)
from app.models.curriculum import CurriculumDeriveJob, CurriculumSnapshot
from app.models.knowledge_graph import GraphDigestJob
from app.models.raw_file import RawFile
from app.repositories import curriculum_repo, kg_repo
from app.repositories.files_repo import list_all_raw_files_by_subject, list_raw_files_by_ids
from app.schemas.knowledge import (
    CurriculumJobResponse,
    DigestBuildData,
    DigestStatusResponse,
    DocGenBuildData,
    DocGenGetResponse,
    GraphDigestJobResponse,
)
from app.services.knowledge.docgen_store import (
    KnowledgeBuildLock,
    acquire_knowledge_build_lock,
    clear_docgen_staging,
    read_knowledge_manifest,
    release_knowledge_build_lock,
)
from app.services.upload_support import build_merged_knowledge_base_path
from app.utils.time import utcnow
from app.workflows.digest import (
    run_curriculum_derive_workflow,
    run_docgen_workflow,
    run_graph_digest_workflow,
)

logger = structlog.get_logger()


def _parse_json_int_list(payload: str | None) -> list[int]:
    if not payload:
        return []

    try:
        raw = json.loads(payload)
    except json.JSONDecodeError:
        return []

    if not isinstance(raw, list):
        return []

    return [int(item) for item in raw if isinstance(item, (int, str)) and str(item).isdigit()]


def _markdown_ready(raw_file: RawFile) -> bool:
    return bool(raw_file.markdown_path and Path(raw_file.markdown_path).exists())


def _clean_prompt(prompt: str | None) -> str | None:
    cleaned = (prompt or "").strip()
    return cleaned or None


def _select_ready_docgen_file_ids(
    session: Session,
    *,
    subject: str,
    file_ids: list[int] | None,
) -> tuple[list[int], int]:
    all_files = list_all_raw_files_by_subject(session, subject)
    ready_file_ids = [
        raw_file.id
        for raw_file in all_files
        if raw_file.id is not None and _markdown_ready(raw_file)
    ]
    ready_file_count = len(ready_file_ids)

    if file_ids is None:
        accepted = ready_file_ids
    else:
        requested_items = list_raw_files_by_ids(session, subject, file_ids)
        found_ids = {item.id for item in requested_items if item.id is not None}
        missing_ids = [file_id for file_id in file_ids if file_id not in found_ids]
        if missing_ids:
            raise RawFileNotFoundError(missing_ids[0])

        ready_set = set(ready_file_ids)
        accepted = [file_id for file_id in file_ids if file_id in ready_set]

    if not accepted:
        raise NoReadyFilesForDocGenError(subject)

    return accepted, ready_file_count


def _compute_idempotency_key(subject: str, file_ids: list[int]) -> str:
    del file_ids
    return f"{subject}:{uuid.uuid4().hex}"


def trigger_digest_build(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
    idempotency_key: str | None = None,
) -> DigestBuildData:
    """Create or reuse a graph digest build job."""

    key = idempotency_key or _compute_idempotency_key(subject, file_ids)
    digest_logger = logger.bind(subject=subject, file_ids=file_ids, idempotency_key=key)
    digest_logger.info("digest_build_requested")

    existing = kg_repo.find_job_by_idempotency_key(session, key)
    if existing is not None:
        digest_logger.info(
            "digest_build_existing_job_reused",
            existing_job_id=existing.id,
            existing_status=existing.status,
        )
        return DigestBuildData(job_id=existing.id, is_existing=True)  # type: ignore[arg-type]

    running = session.exec(
        select(GraphDigestJob).where(
            GraphDigestJob.subject == subject,
            GraphDigestJob.status == "processing",
        )
    ).first()
    if running is not None:
        digest_logger.warning(
            "digest_build_conflict",
            running_job_id=running.id,
            running_status=running.status,
        )
        raise SubjectBuildLockConflictError(subject)

    job = kg_repo.create_digest_job(
        session,
        GraphDigestJob(
            subject=subject,
            idempotency_key=key,
            status="pending",
            input_file_ids_json=json.dumps(sorted(file_ids)),
        ),
    )
    digest_logger.info("digest_build_job_created", job_id=job.id)
    return DigestBuildData(job_id=job.id, is_existing=False)  # type: ignore[arg-type]


async def run_graph_digest_background(*, subject: str, job_id: int) -> None:
    """Run the graph digest workflow in the background."""

    with managed_session() as session:
        try:
            job = session.get(GraphDigestJob, job_id)
            if job is None:
                logger.error("graph_digest_job_not_found", job_id=job_id)
                return

            file_ids: list[int] = json.loads(job.input_file_ids_json or "[]")
            digest_logger = logger.bind(subject=subject, job_id=job_id, file_ids=file_ids)
            digest_logger.info(
                "graph_digest_background_started",
                job_status=job.status,
                progress=job.progress,
            )
            result = await run_graph_digest_workflow(
                subject=subject,
                job_id=job_id,
                file_ids=file_ids,
            )
            if result.failed:
                kg_repo.update_digest_job(
                    session,
                    job_id,
                    status="failed",
                    error_message=result.error.detail[-500:],
                )

            final_job = session.get(GraphDigestJob, job_id)
            digest_logger.info(
                "graph_digest_background_completed",
                final_status=final_job.status if final_job is not None else None,
                final_progress=final_job.progress if final_job is not None else None,
                final_step=final_job.current_step if final_job is not None else None,
                input_chunk_count=final_job.input_chunk_count if final_job is not None else None,
            )
        except asyncio.CancelledError:
            logger.warning("graph_digest_background_cancelled", subject=subject, job_id=job_id)
            try:
                kg_repo.update_digest_job(
                    session,
                    job_id,
                    status="failed",
                    error_message="Background task cancelled.",
                )
            except Exception:
                logger.exception("failed_to_mark_graph_job_cancelled", job_id=job_id)
            raise
        except Exception:
            logger.exception("graph_digest_background_error", subject=subject, job_id=job_id)
            try:
                kg_repo.update_digest_job(
                    session,
                    job_id,
                    status="failed",
                    error_message=traceback.format_exc()[-500:],
                )
            except Exception:
                logger.exception("failed_to_mark_job_failed", job_id=job_id)


async def run_curriculum_derive_background(
    *,
    subject: str,
    graph_job_id: int,
    curriculum_job_id: int,
) -> None:
    """Run the curriculum derive workflow in the background."""

    with managed_session() as session:
        try:
            graph_job = session.get(GraphDigestJob, graph_job_id)
            if graph_job is None:
                logger.error("graph_job_not_found_for_curriculum", graph_job_id=graph_job_id)
                return

            result = await run_curriculum_derive_workflow(
                subject=subject,
                graph_job_id=graph_job_id,
                curriculum_job_id=curriculum_job_id,
            )
            if result.failed:
                curriculum_repo.update_curriculum_job(
                    session,
                    curriculum_job_id,
                    status="failed",
                    error_message=result.error.detail[-500:],
                )
        except asyncio.CancelledError:
            logger.warning(
                "curriculum_derive_background_cancelled",
                curriculum_job_id=curriculum_job_id,
            )
            try:
                curriculum_repo.update_curriculum_job(
                    session,
                    curriculum_job_id,
                    status="failed",
                    error_message="Background task cancelled.",
                )
            except Exception:
                logger.exception("failed_to_mark_curriculum_job_cancelled")
            raise
        except Exception:
            logger.exception(
                "curriculum_derive_background_error",
                curriculum_job_id=curriculum_job_id,
            )
            try:
                curriculum_repo.update_curriculum_job(
                    session,
                    curriculum_job_id,
                    status="failed",
                    error_message=traceback.format_exc()[-500:],
                )
            except Exception:
                logger.exception("failed_to_mark_curriculum_job_failed")


def _build_graph_job_response(job: GraphDigestJob) -> GraphDigestJobResponse:
    return GraphDigestJobResponse(
        id=job.id,  # type: ignore[arg-type]
        subject=job.subject,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        input_chunk_count=job.input_chunk_count,
        nodes_added=job.nodes_added,
        nodes_updated=job.nodes_updated,
        nodes_merged=job.nodes_merged,
        edges_added=job.edges_added,
        edges_updated=job.edges_updated,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _build_curriculum_job_response(job: CurriculumDeriveJob) -> CurriculumJobResponse:
    return CurriculumJobResponse(
        id=job.id,  # type: ignore[arg-type]
        subject=job.subject,
        graph_job_id=job.graph_job_id,
        status=job.status,
        progress=job.progress,
        current_step=job.current_step,
        units_added=job.units_added,
        units_updated=job.units_updated,
        theme_tree_version_id=job.theme_tree_version_id,
        prereq_dag_version_id=job.prereq_dag_version_id,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def get_digest_status(
    session: Session,
    *,
    subject: str,
    job_id: int,
) -> DigestStatusResponse:
    """Return the graph digest status plus linked curriculum status."""

    job = session.get(GraphDigestJob, job_id)
    if job is None or job.subject != subject:
        raise DigestJobNotFoundError(job_id)

    graph_resp = _build_graph_job_response(job)

    curriculum_resp: CurriculumJobResponse | None = None
    if job.curriculum_job_id is not None:
        curriculum_job = session.get(CurriculumDeriveJob, job.curriculum_job_id)
        if curriculum_job is not None:
            curriculum_resp = _build_curriculum_job_response(curriculum_job)

    snapshot = session.exec(
        select(CurriculumSnapshot).where(
            CurriculumSnapshot.subject == subject,
            CurriculumSnapshot.status == "published",
        )
    ).first()
    snapshot_id = snapshot.id if snapshot is not None else None

    logger.info(
        "digest_status_loaded",
        subject=subject,
        job_id=job_id,
        graph_status=job.status,
        graph_progress=job.progress,
        graph_step=job.current_step,
        input_chunk_count=job.input_chunk_count,
        curriculum_job_id=job.curriculum_job_id,
        curriculum_status=curriculum_resp.status if curriculum_resp is not None else None,
        snapshot_id=snapshot_id,
    )

    return DigestStatusResponse(
        graph_job=graph_resp,
        curriculum_job=curriculum_resp,
        current_curriculum_snapshot_id=snapshot_id,
    )


def trigger_docgen_build(
    session: Session,
    *,
    subject: str,
    file_ids: list[int] | None,
    prompt: str | None,
) -> DocGenBuildData:
    """Accept a knowledge docs build request without creating a job row."""

    accepted_file_ids, ready_file_count = _select_ready_docgen_file_ids(
        session,
        subject=subject,
        file_ids=file_ids,
    )
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
    )

    return DocGenBuildData(
        accepted_file_ids=accepted_file_ids,
        ready_file_count=ready_file_count,
        prompt=cleaned_prompt,
        requested_at=requested_at,
    )


async def run_docgen_background(
    *,
    subject: str,
    file_ids: list[int],
    prompt: str | None,
    requested_at: datetime,
) -> None:
    """Run the knowledge docs workflow behind a subject-level build lock."""

    failed_detail: str | None = None
    logged_failure = False
    logger.info(
        "knowledge_build_started",
        subject=subject,
        requested_at=requested_at.isoformat(),
    )

    try:
        result = await run_docgen_workflow(
            subject=subject,
            file_ids=file_ids,
            user_prompt=prompt,
            requested_at=requested_at,
        )
        if result.failed:
            failed_detail = result.error.detail
    except asyncio.CancelledError:
        failed_detail = "Background task cancelled."
        raise
    except Exception:
        failed_detail = traceback.format_exc()[-1000:]
        logger.exception("knowledge_build_failed", subject=subject, requested_at=requested_at.isoformat())
        logged_failure = True
    finally:
        if failed_detail is not None:
            clear_docgen_staging(subject)
            if not logged_failure:
                logger.error(
                    "knowledge_build_failed",
                    subject=subject,
                    requested_at=requested_at.isoformat(),
                    error_message=failed_detail[-500:],
                )
        release_knowledge_build_lock(subject)


def get_docgen_result(session: Session, *, subject: str) -> DocGenGetResponse:
    """Read the published merged docs and manifest only."""

    del session

    merged_path = build_merged_knowledge_base_path(subject)
    manifest = read_knowledge_manifest(subject)
    markdown = merged_path.read_text(encoding="utf-8") if merged_path.exists() else ""

    updated_at: datetime | None = None
    if manifest is not None:
        updated_at = manifest.updated_at
    elif merged_path.exists():
        updated_at = datetime.fromtimestamp(merged_path.stat().st_mtime)

    return DocGenGetResponse(
        exists=bool(merged_path.exists() and markdown.strip()),
        markdown=markdown,
        updated_at=updated_at,
        source_file_ids=manifest.source_file_ids if manifest is not None else [],
        prompt=manifest.prompt if manifest is not None else None,
    )
