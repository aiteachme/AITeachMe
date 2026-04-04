"""Support helpers for digest graph workflow nodes.

Reads DB: ``raw_file``, ``retrieval_chunk``.
Writes DB: ``raw_file``, ``retrieval_chunk`` and subject-scoped vector metadata.
Writes FS: reads ingest-produced markdown files from subject-scoped storage.
Idempotency: raw-file/chunk materialization reuses existing rows and only inserts what is missing.
"""

from __future__ import annotations

from pathlib import Path

import structlog
from sqlmodel import Session, select

from app.shared.infra.database import managed_session
from app.workflows.digest.kg.services.chunker import chunk_markdown
from app.workflows.digest.kg.services.cleaner import clean_markdown
from app.workflows.digest.kg.services.embedder import embed_chunks
from app.models import DigestStep, IngestStatus, RawFile, TaskStatus
from app.models import RetrievalChunk
from app.repositories import knowledge_repo
from app.services.subject_embedding_service import (
    get_runtime_embedding_config,
    should_generate_subject_embeddings,
)
from app.workflows.digest.kg.state import KGDigestState

logger = structlog.get_logger()


def workflow_logger(state: KGDigestState) -> structlog.stdlib.BoundLogger:
    """Bind consistent log context for the graph digest workflow."""

    return logger.bind(
        subject=state["subject"],
        job_id=state["job_id"],
        file_ids=state.get("file_ids", []),
    )


def get_raw_file_record(
    session: Session,
    *,
    subject: str,
    raw_file_id: int,
) -> RawFile | None:
    return session.exec(
        select(RawFile).where(
            RawFile.subject == subject,
            RawFile.id == raw_file_id,
        )
    ).first()


def load_clean_markdown(raw_file: RawFile) -> str:
    if not raw_file.markdown_path:
        return ""

    from app.shared.infra.storage import get_content_store, run_store_sync

    cs = get_content_store()
    text: str | None = run_store_sync(cs.read_text, raw_file.markdown_path, default=None)
    if text is None:
        # fallback: DB 中缓存的 markdown_content
        return clean_markdown(raw_file.markdown_content) if raw_file.markdown_content else ""
    return clean_markdown(text)


async def ensure_retrieval_chunks_for_file(
    session: Session,
    *,
    raw_file: RawFile,
) -> tuple[int, list[int]]:
    raw_file_id = raw_file.id
    if raw_file_id is None:
        raise ValueError("RawFile.id should not be empty after persistence.")

    markdown_content = load_clean_markdown(raw_file)
    document = get_raw_file_record(
        session,
        subject=raw_file.subject,
        raw_file_id=raw_file_id,
    )

    if document is None:
        document = knowledge_repo.bulk_create_documents(
            session,
            [
                RawFile(
                    id=raw_file_id,
                    uid=raw_file.uid,
                    subject=raw_file.subject,
                    filename=raw_file.filename,
                    filetype=raw_file.filetype,
                    file_path=raw_file.file_path,
                    markdown_path=raw_file.markdown_path,
                    markdown_content=markdown_content,
                    current_step=DigestStep.STORED.value,
                )
            ],
        )[0]
    elif markdown_content and document.markdown_content != markdown_content:
        updated_document = knowledge_repo.update_document_content(
            session,
            document.id,
            markdown_content,
        )
        if updated_document is not None:
            document = updated_document

    document_id = document.id
    if document_id is None:
        raise ValueError("RawFile.id should not be empty after persistence.")

    existing_chunks = knowledge_repo.get_chunks_by_document_id(session, document_id)
    if existing_chunks:
        return document_id, [chunk.id for chunk in existing_chunks if chunk.id is not None]

    chunks = chunk_markdown(markdown_content)
    db_chunks = knowledge_repo.bulk_create_chunks(
        session,
        [
            RetrievalChunk(
                subject=raw_file.subject,
                document_id=document_id,
                title=chunk.title,
                level=chunk.level,
                header_path=chunk.header_path,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
            )
            for chunk in chunks
        ],
    )
    chunk_ids = [chunk.id for chunk in db_chunks if chunk.id is not None]
    should_embed = should_generate_subject_embeddings(
        session,
        subject_slug=raw_file.subject,
    )
    if should_embed:
        embeddings = await embed_chunks(chunks)
        if embeddings:
            runtime = get_runtime_embedding_config()
            try:
                knowledge_repo.bulk_insert_embeddings(
                    session,
                    subject=raw_file.subject,
                    chunk_ids=chunk_ids,
                    embeddings=embeddings,
                    embedding_model=runtime.embedding_model,
                )
            except Exception:
                logger.exception(
                    "ensure_retrieval_chunks_embedding_failed",
                    subject=raw_file.subject,
                    raw_file_id=raw_file_id,
                    filename=raw_file.filename,
                    document_id=document_id,
                    chunk_count=len(chunk_ids),
                )
                raise
    else:
        logger.info(
            "ensure_retrieval_chunks_embedding_skipped",
            subject=raw_file.subject,
            raw_file_id=raw_file_id,
            reason="subject_vectors_disabled_or_unavailable",
            chunk_count=len(chunk_ids),
        )
    knowledge_repo.update_document_step(session, document_id, DigestStep.EMBEDDED.value)
    return document_id, chunk_ids


async def prepare_chunk_ids_for_files(
    session: Session,
    *,
    raw_files: list[RawFile],
    digest_logger: structlog.stdlib.BoundLogger,
) -> tuple[list[int], list[int]]:
    document_ids: list[int] = []
    chunk_ids: list[int] = []

    for raw_file in raw_files:
        raw_file_id = raw_file.id
        if raw_file_id is None:
            continue

        is_ready = (
            raw_file.status == TaskStatus.COMPLETED.value
            and raw_file.ingest_status == IngestStatus.READY_FOR_DIGEST.value
        )
        if not is_ready:
            digest_logger.warning(
                "kg_prepare_skip_unready_file",
                file_id=raw_file_id,
                status=raw_file.status,
                ingest_status=raw_file.ingest_status,
                markdown_ready=bool(raw_file.markdown_path),
                filename=raw_file.filename,
            )
            continue

        document_id, file_chunk_ids = await ensure_retrieval_chunks_for_file(
            session,
            raw_file=raw_file,
        )
        document_ids.append(document_id)
        chunk_ids.extend(file_chunk_ids)

    unique_document_ids = list(dict.fromkeys(document_ids))
    unique_chunk_ids = list(dict.fromkeys(chunk_ids))
    return unique_document_ids, unique_chunk_ids


def open_managed_session():
    """Tiny seam to keep node modules focused on orchestration."""

    return managed_session()


__all__ = [
    "ensure_retrieval_chunks_for_file",
    "get_raw_file_record",
    "load_clean_markdown",
    "open_managed_session",
    "prepare_chunk_ids_for_files",
    "workflow_logger",
]
