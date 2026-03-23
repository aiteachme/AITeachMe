"""Digest build and docgen services."""

from __future__ import annotations

import json
import shutil
import traceback
import uuid
from datetime import datetime
from pathlib import Path

import structlog
from sqlmodel import Session

from app.core.database import managed_session
from app.core.exceptions import NoReadyFilesForDocGenError, RawFileNotFoundError
from app.models.raw_file import RawFile
from app.repositories.files_repo import list_all_raw_files_by_subject, list_raw_files_by_ids
from app.repositories.knowledge import docgen_repo
from app.schemas.knowledge import DigestBuildData, DocGenBuildData, DocGenGetResponse, DocGenJobResponse
from app.services.upload_support import (
    build_docgen_intermediate_dir,
    build_knowledge_docs_dir,
    build_merged_knowledge_base_path,
)
from app.workflows.digest import run_curriculum_derive_workflow, run_graph_digest_workflow

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


def _build_docgen_job_response(job) -> DocGenJobResponse:
    return DocGenJobResponse.model_validate(job)


def _collect_published_doc_source_ids(session: Session, subject: str) -> list[int]:
    source_file_ids: set[int] = set()
    for doc in docgen_repo.get_docs_by_subject(session, subject, status="published"):
        source_file_ids.update(_parse_json_int_list(doc.source_file_ids))
    return sorted(source_file_ids)


def _select_ready_docgen_file_ids(
    session: Session,
    *,
    subject: str,
    file_ids: list[int] | None,
) -> tuple[list[int], int]:
    all_files = list_all_raw_files_by_subject(session, subject)
    ready_file_ids = [raw_file.id for raw_file in all_files if raw_file.id is not None and _markdown_ready(raw_file)]
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


def _reset_docgen_outputs(session: Session, *, subject: str) -> None:
    docgen_repo.delete_docs_by_subject(session, subject)
    for directory in (build_knowledge_docs_dir(subject), build_docgen_intermediate_dir(subject)):
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)


def _new_graph_run_id() -> int:
    return (uuid.uuid4().int % 2_000_000_000) + 1


def trigger_digest_build(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
    idempotency_key: str | None = None,
) -> DigestBuildData:
    """Trigger digest graph build without persisting graph job rows."""

    del session, idempotency_key
    logger.info("digest_build_requested", subject=subject, file_ids=file_ids)
    return DigestBuildData(message="增量构建已触发")


async def run_graph_digest_background(*, subject: str, file_ids: list[int]) -> None:
    """Run graph digest workflow in background with an ephemeral run id."""

    run_id = _new_graph_run_id()
    digest_logger = logger.bind(subject=subject, run_id=run_id, file_ids=file_ids)
    try:
        digest_logger.info("graph_digest_background_started")
        result = await run_graph_digest_workflow(subject=subject, job_id=run_id, file_ids=file_ids)
        if result.failed:
            digest_logger.error(
                "graph_digest_background_failed",
                error=result.error.detail,
            )
            return
        digest_logger.info("graph_digest_background_completed")
    except Exception:
        digest_logger.exception("graph_digest_background_error")


async def run_curriculum_derive_background(
    *, subject: str, graph_job_id: int, curriculum_job_id: int
) -> None:
    """Run curriculum derive workflow."""

    with managed_session():
        try:
            result = await run_curriculum_derive_workflow(
                subject=subject,
                graph_job_id=graph_job_id,
                curriculum_job_id=curriculum_job_id,
            )
            if result.failed:
                logger.error(
                    "curriculum_derive_background_failed",
                    curriculum_job_id=curriculum_job_id,
                    error=result.error.detail,
                )
        except Exception:
            logger.exception(
                "curriculum_derive_background_error",
                curriculum_job_id=curriculum_job_id,
            )
            logger.error(
                "curriculum_derive_background_error_traceback",
                curriculum_job_id=curriculum_job_id,
                error=traceback.format_exc()[-500:],
            )


def trigger_docgen_build(
    session: Session,
    *,
    subject: str,
    file_ids: list[int] | None,
    prompt: str | None,
) -> DocGenBuildData:
    """Create a docgen job and return accepted source info."""

    from app.models.knowledge_doc import DocGenJob

    accepted_file_ids, ready_file_count = _select_ready_docgen_file_ids(
        session,
        subject=subject,
        file_ids=file_ids,
    )
    _reset_docgen_outputs(session, subject=subject)
    job = docgen_repo.create_docgen_job(
        session,
        DocGenJob(
            subject=subject,
            status="pending",
            input_file_ids_json=json.dumps(sorted(accepted_file_ids)),
            user_prompt=(prompt or "").strip() or None,
        ),
    )
    logger.info(
        "docgen_build_triggered",
        subject=subject,
        job_id=job.id,
        accepted_file_ids=accepted_file_ids,
        ready_file_count=ready_file_count,
        has_prompt=bool(prompt and prompt.strip()),
    )
    return DocGenBuildData(
        job_id=job.id,  # type: ignore[arg-type]
        accepted_file_ids=accepted_file_ids,
        prompt=(prompt or "").strip() or None,
        ready_file_count=ready_file_count,
    )


async def run_docgen_background(*, subject: str, job_id: int) -> None:
    """Run docgen workflow in background."""

    from app.models.knowledge_doc import DocGenJob
    from app.workflows.digest import run_docgen_workflow

    with managed_session() as session:
        try:
            job = session.get(DocGenJob, job_id)
            if job is None:
                logger.error("docgen_job_not_found", job_id=job_id)
                return

            file_ids: list[int] = json.loads(job.input_file_ids_json or "[]")
            docgen_logger = logger.bind(subject=subject, job_id=job_id, file_ids=file_ids)
            docgen_logger.info("docgen_background_started")

            docgen_repo.update_docgen_job(session, job_id, status="processing")

            result = await run_docgen_workflow(
                subject=subject,
                job_id=job_id,
                file_ids=file_ids,
                user_prompt=job.user_prompt,
            )
            if result.failed:
                docgen_repo.update_docgen_job(
                    session,
                    job_id,
                    status="failed",
                    error_message=result.error.detail[-500:],
                )
            docgen_logger.info("docgen_background_completed", success=result.ok)

        except Exception:
            logger.exception("docgen_background_error", subject=subject, job_id=job_id)
            try:
                docgen_repo.update_docgen_job(
                    session,
                    job_id,
                    status="failed",
                    error_message=traceback.format_exc()[-500:],
                )
            except Exception:
                logger.exception("failed_to_mark_docgen_job_failed", job_id=job_id)


def get_docgen_result(session: Session, *, subject: str) -> DocGenGetResponse:
    """Read merged markdown result and the latest docgen status."""

    merged_path = build_merged_knowledge_base_path(subject)
    latest_job = docgen_repo.get_latest_docgen_job_by_subject(session, subject)
    job_response = _build_docgen_job_response(latest_job) if latest_job is not None else None
    prompt = latest_job.user_prompt if latest_job is not None else None
    source_file_ids = (
        _collect_published_doc_source_ids(session, subject)
        if merged_path.exists()
        else _parse_json_int_list(latest_job.input_file_ids_json if latest_job is not None else None)
    )

    if merged_path.exists():
        return DocGenGetResponse(
            exists=True,
            markdown=merged_path.read_text(encoding="utf-8"),
            merged_path=str(merged_path),
            updated_at=datetime.fromtimestamp(merged_path.stat().st_mtime),
            job=job_response,
            source_file_ids=source_file_ids,
            prompt=prompt,
        )

    return DocGenGetResponse(
        exists=False,
        markdown="",
        merged_path=str(merged_path),
        updated_at=None,
        job=job_response,
        source_file_ids=source_file_ids,
        prompt=prompt,
    )
