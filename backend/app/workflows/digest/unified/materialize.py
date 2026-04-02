"""Canonical section materialization for unified digest builds."""

from __future__ import annotations

from uuid import uuid4

import structlog

from app.core.database import managed_session
from app.infra.embedding import aembed_texts
from app.models import DigestStep, RetrievalChunk
from app.models.raw_file import RawFile
from app.repositories import knowledge_repo
from app.services.subject_embedding_service import (
    get_runtime_embedding_config,
    should_generate_subject_embeddings,
)
from app.workflows.digest.shared.models import SharedInputs
from app.workflows.digest.unified.models import MaterializedSections

logger = structlog.get_logger()


async def materialize_shared_inputs(
    *,
    subject: str,
    shared_inputs: SharedInputs,
    build_session_id: str | None = None,
) -> MaterializedSections:
    """Persist canonical documents and chunks for one unified build session."""

    session_id = build_session_id or uuid4().hex
    source_file_ids = [packet.file_id for packet in shared_inputs.source_packets]

    with managed_session() as session:
        deleted_documents, deleted_chunks = knowledge_repo.delete_documents_by_source_file_ids(
            session,
            subject=subject,
            source_file_ids=source_file_ids,
        )
        logger.info(
            "canonical_chunk_reset_completed",
            subject=subject,
            deleted_documents=deleted_documents,
            deleted_chunks=deleted_chunks,
        )

        documents = knowledge_repo.bulk_create_documents(
            session,
            [
                RawFile(
                    id=packet.file_id,
                    uid=f"raw_{packet.file_id}",
                    subject=subject,
                    filename=packet.filename,
                    filetype="markdown",
                    file_path="",
                    markdown_content=packet.normalized_content,
                    current_step=DigestStep.STORED.value,
                )
                for packet in shared_inputs.source_packets
            ],
        )
        document_id_by_file_id = {
            document.id: document.id
            for document in documents
            if document.id is not None
        }

        chunk_rows = knowledge_repo.bulk_create_chunks(
            session,
            [
                RetrievalChunk(
                    subject=subject,
                    document_id=document_id_by_file_id[section.source_file_id],
                    title=section.title,
                    level=section.level,
                    header_path=section.header_path,
                    chunk_index=section.chunk_index,
                    digest_chunk_uid=section.digest_chunk_uid,
                    build_session_id=session_id,
                    content=section.normalized_content,
                )
                for section in shared_inputs.section_packets
                if section.source_file_id in document_id_by_file_id
            ],
        )
        chunk_ids = [chunk.id for chunk in chunk_rows if chunk.id is not None]
        should_embed = should_generate_subject_embeddings(session, subject_slug=subject)
        if chunk_rows and should_embed:
            runtime = get_runtime_embedding_config()
            embeddings = await aembed_texts(
                [f"{chunk.title}\n{chunk.content}".strip() for chunk in chunk_rows]
            )
            knowledge_repo.bulk_insert_embeddings(
                session,
                subject=subject,
                chunk_ids=chunk_ids,
                embeddings=embeddings,
                embedding_model=runtime.embedding_model,
            )
        elif chunk_rows:
            logger.info(
                "canonical_chunk_embedding_skipped",
                subject=subject,
                reason="subject_vectors_disabled_or_unavailable",
                chunk_count=len(chunk_rows),
            )

        for document in documents:
            if document.id is None:
                continue
            knowledge_repo.update_document_step(session, document.id, DigestStep.EMBEDDED.value)

    materialized = MaterializedSections(
        build_session_id=session_id,
        source_file_ids=source_file_ids,
        document_ids=[document.id for document in documents if document.id is not None],
        chunk_ids=chunk_ids,
        chunk_uid_to_chunk_id={
            chunk.digest_chunk_uid: chunk.id
            for chunk in chunk_rows
            if chunk.id is not None
        },
        chunk_id_to_chunk_uid={
            chunk.id: chunk.digest_chunk_uid
            for chunk in chunk_rows
            if chunk.id is not None
        },
    )
    logger.info(
        "canonical_chunk_materialization_completed",
        subject=subject,
        build_session_id=session_id,
        document_count=len(materialized.document_ids),
        chunk_count=len(materialized.chunk_ids),
    )
    return materialized
