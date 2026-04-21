"""Knowledge-graph background build orchestration."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import structlog
from sqlmodel import select

from app.models.knowledge import RetrievalChunk
from app.shared.infra.database import managed_session
from app.repositories.files_repo import list_raw_files_by_ids
from app.utils.docgen_store import release_knowledge_build_lock, update_knowledge_build_status
from app.utils.job_helpers import cleanup_pending_by_subject
from app.workflows.digest.kg_docs_sync.inputs import (
    extract_doc_chapter_metadatas,
    load_knowledge_doc_markdown,
    resolve_graph_input_paths,
)
from app.workflows.digest.kg_file_ingest.lib.support import prepare_chunk_ids_for_files

logger = structlog.get_logger()


def _sanitize_build_error_message(error_message: str | None) -> str | None:
    text = (error_message or "").strip()
    if not text:
        return None
    if text == "build_cancelled":
        return "Knowledge graph build cancelled."
    if text == "build_crashed":
        return "Knowledge graph build crashed."
    if text == "no_graph_build_sources":
        return "No graph build sources found. Provide files or knowledge markdown."
    if text == "no_ready_digest_inputs":
        return "No ready digest inputs found. Files must be fully prepared for digest ingestion."
    if "Dimension mismatch" in text or "sqlite3.OperationalError" in text or ("chunk_embeddings" in text and "embedding" in text):
        return "Embedding configuration or storage is inconsistent."
    if "[SQL:" in text or "parameters:" in text or "Traceback" in text or len(text) > 240:
        return "Knowledge graph build failed."
    return text

def _write_build_status(subject: str, *, requested_at: datetime, status: str, stage: str, **extra: object) -> None:
    build_kind = str(extra.pop("build_kind", "graph") or "graph")
    payload = {"requested_at": requested_at, "build_kind": build_kind, "status": status, "stage": stage, **extra}
    if "error_message" in payload:
        payload["error_message"] = _sanitize_build_error_message(payload.get("error_message"))
    update_knowledge_build_status(subject, **payload)


def _new_graph_run_id() -> int:
    return (uuid.uuid4().int % 2_000_000_000) + 1


def _new_build_session_id() -> str:
    return uuid.uuid4().hex


def _cleanup_pending_digest_outputs(subject: str) -> None:
    try:
        with managed_session() as session:
            cleanup_pending_by_subject(session, subject=subject, job_type="graph")
    except Exception:
        logger.exception("knowledge_pending_cleanup_failed", subject=subject)


async def _prepare_debug_chunks_for_files(
    *,
    subject: str,
    file_ids: list[int],
    build_session_id: str,
) -> int:
    if not file_ids:
        return 0

    with managed_session() as session:
        raw_files = list_raw_files_by_ids(session, subject, file_ids)
        if not raw_files:
            return 0

        _document_ids, chunk_ids = await prepare_chunk_ids_for_files(
            session,
            raw_files=raw_files,
            digest_logger=logger.bind(
                subject=subject,
                file_ids=file_ids,
                build_session_id=build_session_id,
                lane="kg_debug",
            ),
        )
        if not chunk_ids:
            return 0

        chunks = list(
            session.exec(
                select(RetrievalChunk).where(
                    RetrievalChunk.subject == subject,
                    RetrievalChunk.id.in_(chunk_ids),
                )
            ).all()
        )
        for chunk in chunks:
            chunk.build_session_id = build_session_id
            session.add(chunk)
        session.commit()
        return len(chunk_ids)


async def run_graph_docs_sync_after_doc_build(
    *,
    subject: str,
    requested_at: datetime,
    build_session_id: str,
    file_ids: list[int],
    prompt: str | None,
    build_kind: str = "graph",
) -> dict[str, int | str]:
    """Re-sync knowledge units and knowledge images from the latest knowledge document."""

    from app.workflows.digest.kg_docs_sync import run_graph_docs_sync_workflow

    knowledge_doc_markdown, knowledge_doc_source = load_knowledge_doc_markdown(subject)
    doc_chapter_metadatas = extract_doc_chapter_metadatas(knowledge_doc_markdown)
    if not knowledge_doc_markdown.strip():
        return {
            "knowledge_doc_source": knowledge_doc_source,
            "knowledge_doc_chapter_count": len(doc_chapter_metadatas),
            "doc_sync_unit_changes": 0,
            "doc_sync_edge_changes": 0,
            "doc_sync_elapsed_ms": 0,
        }

    _write_build_status(
        subject,
        requested_at=requested_at,
        status="running",
        stage="graph_docs_sync",
        build_session_id=build_session_id,
        error_message=None,
        draft_available=False,
        source_file_ids=file_ids,
        prompt=prompt,
        build_kind=build_kind,
        graph_input_paths=resolve_graph_input_paths(
            file_ids=file_ids,
            knowledge_doc_markdown=knowledge_doc_markdown,
        ),
        knowledge_doc_source=knowledge_doc_source,
        knowledge_doc_chapter_count=len(doc_chapter_metadatas),
        current_stage_description="Syncing KnowledgeUnits, knowledge images, and relations from the latest knowledge markdown.",
    )
    sync_result = await run_graph_docs_sync_workflow(
        subject=subject,
        markdown=knowledge_doc_markdown,
        build_session_id=build_session_id,
    )
    if sync_result.failed:
        raise RuntimeError(sync_result.error.detail)

    sync_report = sync_result.require_value()
    return {
        "knowledge_doc_source": knowledge_doc_source,
        "knowledge_doc_chapter_count": len(doc_chapter_metadatas),
        "doc_sync_unit_changes": sync_report.unit_change_count,
        "doc_sync_edge_changes": sync_report.edge_change_count,
        "doc_sync_elapsed_ms": sync_report.elapsed_ms,
    }


async def run_graph_file_ingest_background(
    *,
    subject: str,
    file_ids: list[int],
    prompt: str | None,
    requested_at: datetime,
    build_session_id: str,
    doc_chapter_metadatas: list[dict[str, object]] | None = None,
    build_kind: str = "graph",
) -> dict[str, int]:
    """Build graph candidates from parsed files without owning the outer build lock."""

    from app.workflows.digest.kg_file_ingest import run_graph_file_ingest_workflow

    if not file_ids:
        return {"processed_chunks": 0}

    _write_build_status(
        subject,
        requested_at=requested_at,
        status="running",
        stage="graph_file_ingest",
        build_session_id=build_session_id,
        error_message=None,
        draft_available=False,
        source_file_ids=file_ids,
        prompt=prompt,
        build_kind=build_kind,
        current_stage_description="Extracting candidates from parsed files and building the graph.",
    )
    _cleanup_pending_digest_outputs(subject)
    result = await run_graph_file_ingest_workflow(
        subject=subject,
        job_id=_new_graph_run_id(),
        file_ids=file_ids,
        user_prompt=prompt,
        build_session_id=build_session_id,
        doc_chapter_metadatas=doc_chapter_metadatas,
    )
    if result.failed:
        raise RuntimeError(result.error.detail)

    final_state = result.require_value()
    return {
        "processed_chunks": len(final_state.get("chunk_ids", [])),
    }


async def run_graph_build_background(
    *,
    subject: str,
    file_ids: list[int],
    prompt: str | None,
    requested_at: datetime,
) -> None:
    build_session_id = _new_build_session_id()
    try:
        knowledge_doc_markdown, _knowledge_doc_source = load_knowledge_doc_markdown(subject)
        doc_chapter_metadatas = extract_doc_chapter_metadatas(knowledge_doc_markdown)
        doc_sync_metrics: dict[str, int | str] = {
            "knowledge_doc_source": "none",
            "knowledge_doc_chapter_count": len(doc_chapter_metadatas),
            "doc_sync_unit_changes": 0,
            "doc_sync_edge_changes": 0,
            "doc_sync_elapsed_ms": 0,
        }
        if not file_ids and not knowledge_doc_markdown.strip():
            _write_build_status(
                subject,
                requested_at=requested_at,
                status="failed",
                stage="failed",
                build_session_id=build_session_id,
                error_message="no_graph_build_sources",
            )
            logger.error("knowledge_graph_build_failed_no_sources", subject=subject)
            return

        if knowledge_doc_markdown:
            doc_sync_metrics = await run_graph_docs_sync_after_doc_build(
                subject=subject,
                requested_at=requested_at,
                build_session_id=build_session_id,
                file_ids=file_ids,
                prompt=prompt,
            )

        _write_build_status(
            subject,
            requested_at=requested_at,
            status="running",
            stage="graph_file_ingest" if file_ids else "prepare_shared",
            build_session_id=build_session_id,
            error_message=None,
            draft_available=False,
            source_file_ids=file_ids,
            prompt=prompt,
            graph_input_paths=resolve_graph_input_paths(
                file_ids=file_ids,
                knowledge_doc_markdown=knowledge_doc_markdown,
            ),
            **doc_sync_metrics,
            current_stage_description=(
                "Extracting candidates from parsed files and building the graph."
                if file_ids
                else "Skipped file-ingest workflow (no files); keeping docs-sync results only."
            ),
        )
        ingest_metrics = await run_graph_file_ingest_background(
            subject=subject,
            file_ids=file_ids,
            prompt=prompt,
            requested_at=requested_at,
            build_session_id=build_session_id,
            doc_chapter_metadatas=doc_chapter_metadatas,
        )

        _write_build_status(
            subject,
            requested_at=requested_at,
            status="completed",
            stage="completed",
            build_session_id=build_session_id,
            error_message=None,
            processed_chunks=int(ingest_metrics.get("processed_chunks", 0) or 0),
            graph_input_paths=resolve_graph_input_paths(
                file_ids=file_ids,
                knowledge_doc_markdown=knowledge_doc_markdown,
            ),
            **doc_sync_metrics,
        )
    except asyncio.CancelledError:
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="cancelled",
            stage="cancelled",
            build_session_id=build_session_id,
            error_message="build_cancelled",
        )
        raise
    except Exception:
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="failed",
            stage="failed",
            build_session_id=build_session_id,
            error_message="build_crashed",
        )
        logger.exception("knowledge_graph_build_error", subject=subject)
        return
    finally:
        release_knowledge_build_lock(subject)


async def run_graph_file_ingest_debug_background(
    *,
    subject: str,
    file_ids: list[int],
    prompt: str | None,
    requested_at: datetime,
) -> None:
    """Run only the kg_file_ingest lane as a standalone debug action."""

    build_session_id = _new_build_session_id()
    try:
        if not file_ids:
            _write_build_status(
                subject,
                requested_at=requested_at,
                status="failed",
                stage="failed",
                build_session_id=build_session_id,
                error_message="no_graph_build_sources",
            )
            logger.error("knowledge_graph_file_ingest_debug_failed_no_sources", subject=subject)
            return

        prepared_chunk_count = await _prepare_debug_chunks_for_files(
            subject=subject,
            file_ids=file_ids,
            build_session_id=build_session_id,
        )
        if prepared_chunk_count <= 0:
            _write_build_status(
                subject,
                requested_at=requested_at,
                status="failed",
                stage="failed",
                build_session_id=build_session_id,
                error_message="no_ready_digest_inputs",
                source_file_ids=file_ids,
                prompt=prompt,
                current_stage_description="当前文件尚未准备好进入知识图谱摄取。",
            )
            logger.error(
                "knowledge_graph_file_ingest_debug_failed_no_ready_chunks",
                subject=subject,
                file_ids=file_ids,
            )
            return

        ingest_metrics = await run_graph_file_ingest_background(
            subject=subject,
            file_ids=file_ids,
            prompt=prompt,
            requested_at=requested_at,
            build_session_id=build_session_id,
            doc_chapter_metadatas=[],
        )
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="completed",
            stage="completed",
            build_session_id=build_session_id,
            error_message=None,
            source_file_ids=file_ids,
            prompt=prompt,
            processed_chunks=int(ingest_metrics.get("processed_chunks", 0) or 0),
            current_stage_description="kg_file_ingest 调试执行完成。",
        )
    except asyncio.CancelledError:
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="cancelled",
            stage="cancelled",
            build_session_id=build_session_id,
            error_message="build_cancelled",
        )
        raise
    except Exception as exc:
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="failed",
            stage="failed",
            build_session_id=build_session_id,
            error_message=str(exc) or "build_crashed",
            current_stage_description="kg_file_ingest 调试执行失败。",
        )
        logger.exception("knowledge_graph_file_ingest_debug_error", subject=subject)
        return
    finally:
        release_knowledge_build_lock(subject)


async def run_graph_docs_sync_debug_background(
    *,
    subject: str,
    prompt: str | None,
    requested_at: datetime,
) -> None:
    """Run only the kg_docs_sync lane as a standalone debug action."""

    build_session_id = _new_build_session_id()
    try:
        knowledge_doc_markdown, knowledge_doc_source = load_knowledge_doc_markdown(subject)
        if not knowledge_doc_markdown.strip():
            _write_build_status(
                subject,
                requested_at=requested_at,
                status="failed",
                stage="failed",
                build_session_id=build_session_id,
                error_message="no_graph_build_sources",
                current_stage_description="当前没有可同步的知识文档。",
            )
            logger.error("knowledge_graph_docs_sync_debug_failed_no_markdown", subject=subject)
            return

        metrics = await run_graph_docs_sync_after_doc_build(
            subject=subject,
            requested_at=requested_at,
            build_session_id=build_session_id,
            file_ids=[],
            prompt=prompt,
        )
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="completed",
            stage="completed",
            build_session_id=build_session_id,
            error_message=None,
            prompt=prompt,
            current_stage_description="kg_docs_sync 调试执行完成。",
            **metrics,
        )
    except asyncio.CancelledError:
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="cancelled",
            stage="cancelled",
            build_session_id=build_session_id,
            error_message="build_cancelled",
        )
        raise
    except Exception as exc:
        _write_build_status(
            subject,
            requested_at=requested_at,
            status="failed",
            stage="failed",
            build_session_id=build_session_id,
            error_message=str(exc) or "build_crashed",
            current_stage_description="kg_docs_sync 调试执行失败。",
        )
        logger.exception("knowledge_graph_docs_sync_debug_error", subject=subject)
        return
    finally:
        release_knowledge_build_lock(subject)


__all__ = [
    "run_graph_build_background",
    "run_graph_docs_sync_debug_background",
    "run_graph_docs_sync_after_doc_build",
    "run_graph_file_ingest_debug_background",
    "run_graph_file_ingest_background",
]
