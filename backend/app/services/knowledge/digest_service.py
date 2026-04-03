"""Digest build and knowledge-doc generation service helpers."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import structlog
from sqlmodel import Session

from app.shared.infra.exceptions import (
    NoReadyFilesForDocGenError,
    RawFileNotFoundError,
    SubjectBuildLockConflictError,
)
from app.shared.infra.database import managed_session
from app.models import IngestStatus, TaskStatus
from app.models.raw_file import RawFile
from app.models.subject import Subject
from app.repositories.files_repo import (
    list_all_raw_files_by_subject,
    list_raw_files_by_ids,
    list_raw_files_by_uids,
)
from app.schemas.knowledge import (
    BuildPreviewNodeResponse,
    DocGenBuildData,
    DocGenGetResponse,
    KnowledgeBuildMetricsResponse,
    KnowledgeBuildPreviewResponse,
    KnowledgeBuildStatusResponse,
)
from app.repositories import knowledge_repo
from app.services.subject_embedding_service import (
    get_subject_vector_status_by_slug,
    inspect_subject_build_precheck,
    resolve_subject_build_vector_status,
)
from app.utils.docgen_store import (
    KnowledgeBuildLock,
    acquire_knowledge_build_lock,
    clear_docgen_staging,
    read_knowledge_build_lock,
    read_knowledge_build_status,
    read_knowledge_manifest,
    release_knowledge_build_lock,
    update_knowledge_build_status,
)
from app.utils.job_helpers import cleanup_pending_by_subject
from app.utils.path_helpers import (
    build_merged_knowledge_base_build_path,
    build_merged_knowledge_base_path,
)
from app.utils.presenters import require_id, require_uid
from app.utils.time import utcnow
from app.workflows.digest.observability import build_token_summary
from app.workflows.digest.unified import run_unified_digest_build

logger = structlog.get_logger()
_UNSET = object()
_GENERIC_BUILD_FAILURE_MESSAGE = "知识构建失败，请稍后重试。"


def _markdown_ready(raw_file: RawFile) -> bool:
    return (
        raw_file.status == TaskStatus.COMPLETED.value
        and raw_file.ingest_status
        in (
            IngestStatus.FAST_PARSED.value,
            IngestStatus.ENHANCING.value,
            IngestStatus.READY_FOR_DIGEST.value,
            IngestStatus.ENHANCE_FAILED.value,
        )
        and bool(raw_file.parsed_markdown.strip())
    )


def _clean_prompt(prompt: str | None) -> str | None:
    cleaned = (prompt or "").strip()
    return cleaned or None


def _sanitize_build_error_message(error_message: str | None) -> str | None:
    normalized = (error_message or "").strip()
    if not normalized:
        return None
    if normalized == "build_cancelled":
        return "本轮知识构建已取消。"
    if normalized == "build_crashed":
        return _GENERIC_BUILD_FAILURE_MESSAGE
    if normalized == "no_ready_digest_inputs":
        return "当前没有可用于知识构建的已解析文件。"
    if (
        "Dimension mismatch" in normalized
        or "sqlite3.OperationalError" in normalized
        or "chunk_embeddings" in normalized
        and "embedding" in normalized
    ):
        return "当前学科向量配置与运行时 embedding 不一致，请重新发起构建并选择处理方式。"
    if "[SQL:" in normalized or "parameters:" in normalized or "Traceback" in normalized:
        return _GENERIC_BUILD_FAILURE_MESSAGE
    if len(normalized) > 240:
        return _GENERIC_BUILD_FAILURE_MESSAGE
    return normalized


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
    return sorted(
        requested_items,
        key=lambda item: order[require_uid(item.uid, "RawFile.uid")],
    )


def _select_ready_docgen_files(
    session: Session,
    *,
    subject: str,
    file_uids: list[str] | None,
) -> tuple[list[RawFile], int]:
    all_files = list_all_raw_files_by_subject(session, subject)
    ready_files = [
        raw_file
        for raw_file in all_files
        if raw_file.id is not None and _markdown_ready(raw_file)
    ]
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


def _resolve_file_uids_from_ids(
    session: Session,
    *,
    subject: str,
    file_ids: list[int],
) -> list[str]:
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


def _write_build_status(
    subject: str,
    *,
    requested_at: datetime,
    status: str,
    stage: str,
    build_session_id: str | None = None,
    error_message: str | None = None,
    draft_available: bool | None = None,
    draft_updated_at: datetime | None = None,
    staged_chapter_count: int | None = None,
    published_doc_count: int | None = None,
    source_file_ids: list[int] | None = None,
    prompt: str | None | object = _UNSET,
) -> None:
    update_kwargs: dict[str, object] = {
        "requested_at": requested_at,
        "status": status,
        "stage": stage,
        "error_message": _sanitize_build_error_message(error_message),
    }
    if build_session_id is not None:
        update_kwargs["build_session_id"] = build_session_id
    if draft_available is not None:
        update_kwargs["draft_available"] = draft_available
    if draft_updated_at is not None:
        update_kwargs["draft_updated_at"] = draft_updated_at
    if staged_chapter_count is not None:
        update_kwargs["staged_chapter_count"] = staged_chapter_count
    if published_doc_count is not None:
        update_kwargs["published_doc_count"] = published_doc_count
    if source_file_ids is not None:
        update_kwargs["source_file_ids"] = source_file_ids
    if prompt is not _UNSET:
        update_kwargs["prompt"] = prompt
    update_knowledge_build_status(subject, **update_kwargs)


def _extract_markdown_excerpt(markdown: str, *, max_lines: int = 6, max_chars: int = 420) -> str:
    excerpt_lines: list[str] = []
    current_chars = 0
    for raw_line in markdown.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped == "---":
            continue
        excerpt_lines.append(stripped)
        current_chars += len(stripped)
        if len(excerpt_lines) >= max_lines or current_chars >= max_chars:
            break
    excerpt = "\n".join(excerpt_lines).strip()
    if len(excerpt) > max_chars:
        excerpt = excerpt[: max_chars - 1].rstrip() + "…"
    return excerpt


def _resolve_preview_chapter_titles(*, draft_markdown: str, manifest) -> list[str]:
    if manifest is not None and manifest.chapter_titles:
        return [str(title).strip() for title in manifest.chapter_titles[:4] if str(title).strip()]

    titles: list[str] = []
    for raw_line in draft_markdown.splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("#").strip()
        if not title or title.lower() == "knowledge document overview":
            continue
        titles.append(title)
        if len(titles) >= 4:
            break
    return titles


def _build_runtime_preview(
    *,
    build_status,
    draft_markdown: str,
    manifest,
) -> KnowledgeBuildPreviewResponse | None:
    if build_status is None and not draft_markdown.strip() and manifest is None:
        return None

    sample_nodes = []
    if build_status is not None:
        sample_nodes = [
            BuildPreviewNodeResponse(
                name=str(item.get("name", "")).strip(),
                node_type=str(item.get("type", "Topic")).strip() or "Topic",
            )
            for item in build_status.sample_nodes
            if str(item.get("name", "")).strip()
        ][:6]
        sample_cards = [
            {
                "title": str(item.get("title", "")).strip(),
                "card_type": str(item.get("card_type", "")).strip() or "topic",
                "summary": str(item.get("summary", "")).strip(),
            }
            for item in build_status.sample_cards
            if str(item.get("title", "")).strip() and str(item.get("summary", "")).strip()
        ]
    else:
        sample_cards = []

    return KnowledgeBuildPreviewResponse(
        current_stage_description=(
            build_status.current_stage_description.strip()
            if build_status is not None and build_status.current_stage_description
            else None
        ),
        digest_mode=build_status.digest_mode if build_status is not None else None,
        mode_reason=build_status.mode_reason if build_status is not None else None,
        processed_chunks=build_status.processed_chunks if build_status is not None else 0,
        total_chunks=build_status.total_chunks if build_status is not None else 0,
        discovered_node_count=build_status.discovered_node_count if build_status is not None else 0,
        discovered_node_types=dict(build_status.discovered_node_types) if build_status is not None else {},
        sample_nodes=sample_nodes,
        sample_cards=sample_cards,
        latest_chapter_titles=_resolve_preview_chapter_titles(
            draft_markdown=draft_markdown,
            manifest=manifest,
        ),
        draft_excerpt=_extract_markdown_excerpt(draft_markdown),
    )


def _build_runtime_metrics(*, build_status) -> KnowledgeBuildMetricsResponse | None:
    build_session_id = (
        str(build_status.build_session_id).strip()
        if build_status is not None and build_status.build_session_id is not None
        else ""
    )
    if not build_session_id:
        return None

    token_summary = build_token_summary(build_session_id=build_session_id)
    if token_summary.total_calls <= 0 and token_summary.failed_call_count <= 0:
        return None

    lane_counts = {
        lane: count
        for lane, count in token_summary.call_count_by_lane.items()
        if lane and lane != "(unknown_lane)" and count > 0
    }
    return KnowledgeBuildMetricsResponse(
        llm_total_calls=token_summary.total_calls,
        failed_llm_call_count=token_summary.failed_call_count,
        llm_avg_latency_ms=token_summary.avg_latency_ms,
        call_count_by_lane=lane_counts,
    )


def _resolve_runtime_build_status(*, subject: str) -> KnowledgeBuildStatusResponse:
    build_lock = read_knowledge_build_lock(subject)
    build_status = read_knowledge_build_status(subject)
    effective_build = build_status
    if effective_build is None and build_lock is not None:
        effective_build = update_knowledge_build_status(
            subject,
            requested_at=build_lock.requested_at,
            status="running",
            stage="build_accepted",
            source_file_ids=build_lock.source_file_ids,
            prompt=build_lock.prompt,
        )

    if effective_build is None:
        return KnowledgeBuildStatusResponse(
            status="idle",
            requested_at=utcnow(),
            stage="idle",
            error_message=None,
            draft_available=False,
        )

    return KnowledgeBuildStatusResponse(
        status=effective_build.status,
        requested_at=effective_build.requested_at,
        stage=effective_build.stage,
        error_message=_sanitize_build_error_message(effective_build.error_message),
        draft_available=bool(effective_build.draft_available),
    )


def trigger_docgen_build(
    session: Session,
    *,
    subject: Subject,
    file_uids: list[str] | None,
    prompt: str | None,
    embedding_resolution: str | None,
) -> tuple[DocGenBuildData, list[int]]:
    """Acquire the build lock and return accepted source info for doc generation."""

    conflict = inspect_subject_build_precheck(session, subject=subject)
    vector_status = resolve_subject_build_vector_status(
        session,
        subject=subject,
        embedding_resolution=embedding_resolution,
    )
    force_full_rebuild = bool(
        conflict is not None
        and conflict.requires_full_rebuild
        and vector_status.mode != "disabled"
    )
    effective_file_uids = None if force_full_rebuild else file_uids
    if force_full_rebuild:
        knowledge_repo.clear_chunk_vector_metadata(session, subject=subject.slug)
    accepted_files, ready_file_count = _select_ready_docgen_files(
        session,
        subject=subject.slug,
        file_uids=effective_file_uids,
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
    if not acquire_knowledge_build_lock(subject.slug, lock):
        raise SubjectBuildLockConflictError(subject.slug)

    clear_docgen_staging(subject.slug)
    _write_build_status(
        subject.slug,
        requested_at=requested_at,
        status="accepted",
        stage="build_accepted",
        error_message=None,
        draft_available=False,
        source_file_ids=accepted_file_ids,
        prompt=cleaned_prompt,
        staged_chapter_count=0,
        published_doc_count=0,
    )
    logger.info(
        "knowledge_build_requested",
        subject=subject.slug,
        requested_at=requested_at.isoformat(),
        file_count=len(accepted_file_ids),
        force_full_rebuild=force_full_rebuild,
        vector_mode=vector_status.mode,
    )

    return (
        DocGenBuildData(
            accepted_file_uids=accepted_file_uids,
            ready_file_count=ready_file_count,
            prompt=cleaned_prompt,
            requested_at=requested_at,
            vector_status=vector_status,
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
    build_session_id = uuid.uuid4().hex

    try:
        _clear_docgen_staging_safely(subject)
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="running",
            stage="prepare_shared",
            build_session_id=build_session_id,
            error_message=None,
            draft_available=False,
            source_file_ids=file_ids,
            prompt=prompt,
        )
        _cleanup_pending_digest_outputs(subject)
        result = await run_unified_digest_build(
            subject=subject,
            file_ids=file_ids,
            user_prompt=prompt,
            requested_at=requested_at,
            build_session_id=build_session_id,
        )
        if not result.success:
            _clear_docgen_staging_safely(subject)
            _write_build_status(
                subject,
                requested_at=requested_at,
                status="failed",
                stage="failed",
                build_session_id=build_session_id,
                error_message=result.error,
                draft_available=False,
                staged_chapter_count=0,
            )
            build_logger.error("knowledge_unified_build_failed", error=result.error)
            return

        _write_build_status(
            subject,
            requested_at=requested_at,
            status="completed",
            stage="completed",
            build_session_id=build_session_id,
            error_message=None,
            draft_available=False,
            published_doc_count=result.doc_count,
        )
        build_logger.info(
            "knowledge_unified_build_completed",
            doc_count=result.doc_count,
            chunk_count=result.chunk_count,
            new_node_count=result.new_node_count,
            new_edge_count=result.new_edge_count,
            elapsed_ms=result.elapsed_ms,
            llm_total_calls=int((result.token_summary or {}).get("total_calls", 0)),
            llm_call_count_by_lane=dict((result.token_summary or {}).get("call_count_by_lane", {})),
        )
    except asyncio.CancelledError:
        _clear_docgen_staging_safely(subject)
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="cancelled",
            stage="cancelled",
            build_session_id=build_session_id,
            error_message="build_cancelled",
            draft_available=False,
            staged_chapter_count=0,
        )
        build_logger.warning("knowledge_unified_build_cancelled")
        raise
    except Exception:
        _clear_docgen_staging_safely(subject)
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="failed",
            stage="failed",
            build_session_id=build_session_id,
            error_message="build_crashed",
            draft_available=False,
            staged_chapter_count=0,
        )
        build_logger.exception("knowledge_unified_build_failed")
        return
    finally:
        release_knowledge_build_lock(subject)


def get_docgen_result(session: Session, *, subject: str) -> DocGenGetResponse:
    """Read live docs, staging draft preview, and runtime build metadata."""

    merged_path = build_merged_knowledge_base_path(subject)
    draft_path = build_merged_knowledge_base_build_path(subject)
    manifest = read_knowledge_manifest(subject)
    build_status = read_knowledge_build_status(subject)
    markdown = merged_path.read_text(encoding="utf-8") if merged_path.exists() else ""
    draft_markdown = draft_path.read_text(encoding="utf-8") if draft_path.exists() else ""

    updated_at: datetime | None = None
    draft_updated_at: datetime | None = None
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

    if build_status is not None and build_status.draft_updated_at is not None:
        draft_updated_at = build_status.draft_updated_at
    elif draft_path.exists():
        draft_updated_at = datetime.fromtimestamp(draft_path.stat().st_mtime)

    build_response = _resolve_runtime_build_status(subject=subject)
    build_response.draft_available = bool(build_response.draft_available or draft_markdown.strip())
    build_preview = _build_runtime_preview(
        build_status=build_status,
        draft_markdown=draft_markdown,
        manifest=manifest,
    )
    build_metrics = _build_runtime_metrics(build_status=build_status)

    return DocGenGetResponse(
        exists=bool(merged_path.exists() and markdown.strip()),
        markdown=markdown,
        updated_at=updated_at,
        source_file_uids=source_file_uids,
        prompt=manifest.prompt if manifest is not None else None,
        draft_markdown=draft_markdown,
        draft_updated_at=draft_updated_at,
        build=build_response,
        build_preview=build_preview,
        build_metrics=build_metrics,
        vector_status=get_subject_vector_status_by_slug(session, subject),
    )

__all__ = [
    "get_docgen_result",
    "run_docgen_background",
    "run_graph_digest_background",
    "run_unified_build_background",
    "trigger_docgen_build",
]
