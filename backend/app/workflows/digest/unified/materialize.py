"""Canonical section materialization for unified digest builds."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field
import structlog

from app.core.database import managed_session
from app.infra.embedding import aembed_texts
from app.models import DigestStep, RetrievalChunk
from app.models.raw_file import RawFile
from app.repositories import knowledge_repo
from app.utils.path_helpers import build_knowledge_chunk_manifest_path
from app.utils.time import utcnow
from app.workflows.digest.shared.models import SharedInputs
from app.workflows.digest.unified.models import MaterializedSections

logger = structlog.get_logger()


class ChunkManifestEntry(BaseModel):
    """Persisted metadata for one canonical retrieval chunk."""

    digest_chunk_uid: str
    source_file_id: int
    document_id: int
    chunk_id: int
    content_hash: str
    title: str
    header_path: str
    level: int
    chunk_index: int
    updated_at: datetime


class KnowledgeChunkManifest(BaseModel):
    """Incremental manifest for canonical chunk materialization."""

    subject: str
    updated_at: datetime
    build_session_id: str
    source_file_ids: list[int] = Field(default_factory=list)
    chunks: list[ChunkManifestEntry] = Field(default_factory=list)


def _chunk_content_hash(*, title: str, content: str) -> str:
    payload = f"{title}\n{content}".strip().encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_chunk_manifest(subject: str) -> KnowledgeChunkManifest | None:
    path = build_knowledge_chunk_manifest_path(subject)
    if not path.exists():
        return None
    try:
        return KnowledgeChunkManifest.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_chunk_manifest(subject: str, manifest: KnowledgeChunkManifest) -> Path:
    path = build_knowledge_chunk_manifest_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


async def materialize_shared_inputs(
    *,
    subject: str,
    shared_inputs: SharedInputs,
    build_session_id: str | None = None,
) -> MaterializedSections:
    """Persist canonical documents and chunks for one unified build session."""

    session_id = build_session_id or uuid4().hex
    source_file_ids = [packet.file_id for packet in shared_inputs.source_packets]
    existing_manifest = _load_chunk_manifest(subject)
    previous_entries = {
        entry.digest_chunk_uid: entry
        for entry in (existing_manifest.chunks if existing_manifest is not None else [])
    }

    with managed_session() as session:
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
            packet.file_id: int(document.id)
            for packet, document in zip(shared_inputs.source_packets, documents, strict=False)
            if document.id is not None
        }

        existing_chunks = knowledge_repo.get_chunks_by_source_file_ids(
            session,
            subject=subject,
            source_file_ids=source_file_ids,
        )
        existing_chunk_by_uid = {
            chunk.digest_chunk_uid: chunk
            for chunk in existing_chunks
            if chunk.digest_chunk_uid
        }
        desired_sections = [
            section
            for section in shared_inputs.section_packets
            if section.source_file_id in document_id_by_file_id
        ]
        desired_uids = {section.digest_chunk_uid for section in desired_sections}

        stale_chunk_ids = [
            int(chunk.id)
            for uid, chunk in existing_chunk_by_uid.items()
            if uid not in desired_uids and chunk.id is not None
        ]
        deleted_chunks = knowledge_repo.delete_chunks_by_ids(session, stale_chunk_ids)

        reused_chunks: list[RetrievalChunk] = []
        new_chunk_models: list[RetrievalChunk] = []
        new_embedding_inputs: list[str] = []
        reused_count = 0

        for section in desired_sections:
            document_id = document_id_by_file_id[section.source_file_id]
            existing_chunk = existing_chunk_by_uid.get(section.digest_chunk_uid)
            if existing_chunk is None:
                new_chunk_models.append(
                    RetrievalChunk(
                        subject=subject,
                        document_id=document_id,
                        title=section.title,
                        level=section.level,
                        header_path=section.header_path,
                        chunk_index=section.chunk_index,
                        digest_chunk_uid=section.digest_chunk_uid,
                        build_session_id=session_id,
                        content=section.normalized_content,
                    )
                )
                new_embedding_inputs.append(f"{section.title}\n{section.normalized_content}".strip())
                continue

            metadata_changed = any(
                [
                    existing_chunk.document_id != document_id,
                    existing_chunk.title != section.title,
                    existing_chunk.level != section.level,
                    existing_chunk.header_path != section.header_path,
                    existing_chunk.chunk_index != section.chunk_index,
                    existing_chunk.content != section.normalized_content,
                    existing_chunk.build_session_id != session_id,
                    not existing_chunk.is_active,
                ]
            )
            if metadata_changed:
                existing_chunk.document_id = document_id
                existing_chunk.title = section.title
                existing_chunk.level = section.level
                existing_chunk.header_path = section.header_path
                existing_chunk.chunk_index = section.chunk_index
                existing_chunk.content = section.normalized_content
                existing_chunk.build_session_id = session_id
                existing_chunk.is_active = True
                existing_chunk.updated_at = utcnow()
                session.add(existing_chunk)
            reused_chunks.append(existing_chunk)
            reused_count += 1

        if reused_chunks:
            session.commit()
            for chunk in reused_chunks:
                session.refresh(chunk)

        chunk_rows = knowledge_repo.bulk_create_chunks(session, new_chunk_models) if new_chunk_models else []
        new_chunk_ids = [int(chunk.id) for chunk in chunk_rows if chunk.id is not None]
        if chunk_rows and new_chunk_ids:
            embeddings = await aembed_texts(new_embedding_inputs)
            knowledge_repo.bulk_insert_embeddings(session, new_chunk_ids, embeddings)

        for document in documents:
            if document.id is None:
                continue
            knowledge_repo.update_document_step(session, int(document.id), DigestStep.EMBEDDED.value)

        materialized_chunks = [*reused_chunks, *chunk_rows]
        chunk_ids = [int(chunk.id) for chunk in materialized_chunks if chunk.id is not None]
        chunk_uid_to_chunk_id = {
            chunk.digest_chunk_uid: int(chunk.id)
            for chunk in materialized_chunks
            if chunk.id is not None
        }
        chunk_id_to_chunk_uid = {
            int(chunk.id): chunk.digest_chunk_uid
            for chunk in materialized_chunks
            if chunk.id is not None
        }

        manifest_entries: dict[str, ChunkManifestEntry] = {
            uid: entry
            for uid, entry in previous_entries.items()
            if entry.source_file_id not in source_file_ids
        }
        for chunk in materialized_chunks:
            if chunk.id is None:
                continue
            manifest_entries[chunk.digest_chunk_uid] = ChunkManifestEntry(
                digest_chunk_uid=chunk.digest_chunk_uid,
                source_file_id=int(chunk.document_id),
                document_id=int(chunk.document_id),
                chunk_id=int(chunk.id),
                content_hash=_chunk_content_hash(title=chunk.title, content=chunk.content),
                title=chunk.title,
                header_path=chunk.header_path,
                level=chunk.level,
                chunk_index=chunk.chunk_index,
                updated_at=chunk.updated_at,
            )

    materialized = MaterializedSections(
        build_session_id=session_id,
        source_file_ids=source_file_ids,
        document_ids=[int(document.id) for document in documents if document.id is not None],
        chunk_ids=chunk_ids,
        chunk_uid_to_chunk_id=chunk_uid_to_chunk_id,
        chunk_id_to_chunk_uid=chunk_id_to_chunk_uid,
    )
    manifest = KnowledgeChunkManifest(
        subject=subject,
        updated_at=utcnow(),
        build_session_id=session_id,
        source_file_ids=sorted(
            {
                *(existing_manifest.source_file_ids if existing_manifest is not None else []),
                *source_file_ids,
            }
        ),
        chunks=sorted(
            manifest_entries.values(),
            key=lambda entry: (entry.source_file_id, entry.chunk_index, entry.digest_chunk_uid),
        ),
    )
    _write_chunk_manifest(subject, manifest)
    logger.info(
        "canonical_chunk_materialization_completed",
        subject=subject,
        build_session_id=session_id,
        document_count=len(materialized.document_ids),
        chunk_count=len(materialized.chunk_ids),
        reused_chunk_count=reused_count,
        created_chunk_count=len(chunk_rows),
        deleted_chunk_count=deleted_chunks,
    )
    return materialized
