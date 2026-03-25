"""Canonical section materialization for unified digest builds."""

from __future__ import annotations

import json
from uuid import uuid4

import structlog
from sqlmodel import select

from app.core.database import managed_session
from app.core.embedding import aembed_texts
from app.models import RetrievalChunk, Subject
from app.repositories.knowledge.knowledge_repo import (
    bulk_create_chunks,
    bulk_insert_embeddings,
    delete_chunks_by_source,
)
from app.workflows.digest.shared.models import SharedInputs
from app.workflows.digest.unified.models import MaterializedSections

logger = structlog.get_logger()


def _token_count(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


async def materialize_shared_inputs(
    *,
    subject: str,
    shared_inputs: SharedInputs,
    build_session_id: str | None = None,
) -> MaterializedSections:
    """Persist canonical retrieval chunks for one unified build session."""

    session_id = build_session_id or uuid4().hex
    source_file_ids = [packet.file_id for packet in shared_inputs.source_packets]

    with managed_session() as session:
        subject_row = session.exec(select(Subject).where(Subject.slug == subject)).first()
        if subject_row is None or subject_row.id is None:
            raise ValueError(f"Unknown subject `{subject}`")

        deleted_chunks = delete_chunks_by_source(
            session,
            source_type="raw_file",
            source_ids=source_file_ids,
        )
        logger.info(
            "canonical_chunk_reset_completed",
            subject=subject,
            deleted_chunks=deleted_chunks,
        )

        chunk_rows = bulk_create_chunks(
            session,
            [
                RetrievalChunk(
                    user_id=subject_row.user_id,
                    subject_id=int(subject_row.id),
                    source_type="raw_file",
                    source_id=section.source_file_id,
                    chunk_role="body",
                    chunk_index=section.chunk_index,
                    level=section.level,
                    title=section.title,
                    header_path=section.header_path,
                    digest_chunk_uid=section.digest_chunk_uid,
                    build_session_id=session_id,
                    content=section.normalized_content,
                    token_count=_token_count(section.normalized_content),
                    page_num=section.page_num,
                    metadata_json=json.dumps(
                        {
                            "source_filename": section.source_filename,
                            "char_count": section.char_count,
                            "formula_refs": section.formula_refs,
                            "image_refs": section.image_refs,
                        },
                        ensure_ascii=False,
                    ),
                )
                for section in shared_inputs.section_packets
            ],
        )
        chunk_ids = [int(chunk.id) for chunk in chunk_rows if chunk.id is not None]
        if chunk_rows:
            try:
                embeddings = await aembed_texts(
                    [f"{chunk.title}\n{chunk.content}".strip() for chunk in chunk_rows]
                )
                bulk_insert_embeddings(session, chunk_ids, embeddings)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "canonical_chunk_embeddings_skipped",
                    subject=subject,
                    build_session_id=session_id,
                    reason=str(exc),
                )

    materialized = MaterializedSections(
        build_session_id=session_id,
        source_file_ids=source_file_ids,
        document_ids=list(source_file_ids),
        chunk_ids=chunk_ids,
        chunk_uid_to_chunk_id={
            chunk.digest_chunk_uid: int(chunk.id)
            for chunk in chunk_rows
            if chunk.id is not None
        },
        chunk_id_to_chunk_uid={
            int(chunk.id): chunk.digest_chunk_uid
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
