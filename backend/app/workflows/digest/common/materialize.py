"""Canonical section materialization for digest builds."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field
import structlog
from sqlmodel import select

from app.shared.infra.database import managed_session
from app.shared.infra.search.llamaindex_index import aembed_texts_for_ingestion, course_index_write_scope
from app.shared.infra.storage import resolve_course_storage_scope
from app.models import DigestStep, RetrievalChunk
from app.models.raw_file import RawFile
import app.repositories.knowledge.knowledge_repo as knowledge_repo
from app.utils.time import utcnow
from app.shared.infra.course import (
    build_course_index_ref_for_course,
    get_runtime_embedding_config,
    get_course_record_by_id,
    get_course_vector_capability,
)
from app.shared.infra.course.vectors import RuntimeEmbeddingConfig
from app.shared.infra.workflow.runtime import run_sync_and_drain
from app.workflows.digest.common.models import MaterializedSections, SharedInputs

logger = structlog.get_logger()


class ChunkManifestEntry(BaseModel):
    """Persisted metadata for one canonical retrieval chunk."""

    digest_chunk_uid: str
    source_file_id: str
    document_id: str
    chunk_id: int
    content_hash: str
    title: str
    header_path: str
    level: int
    chunk_index: int
    updated_at: datetime


class KnowledgeChunkManifest(BaseModel):
    """Incremental manifest for canonical chunk materialization."""

    course_id: str
    updated_at: datetime
    build_session_id: str
    source_file_ids: list[str] = Field(default_factory=list)
    chunks: list[ChunkManifestEntry] = Field(default_factory=list)


def _chunk_content_hash(*, title: str, content: str) -> str:
    payload = f"{title}\n{content}".strip().encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _load_chunk_manifest(course_id: str) -> KnowledgeChunkManifest | None:
    from app.shared.infra.storage import get_content_store, run_store_sync

    cs = get_content_store()
    return run_store_sync(
        cs.read_json,
        resolve_course_storage_scope(course_id).chunk_manifest_key(),
        KnowledgeChunkManifest,
    )


def _write_chunk_manifest(course_id: str, manifest: KnowledgeChunkManifest) -> str:
    from app.shared.infra.storage import get_content_store, run_store_sync

    cs = get_content_store()
    key = resolve_course_storage_scope(course_id).chunk_manifest_key()
    run_store_sync(cs.write_json, key, manifest)
    return key


def _chunk_requires_embedding(
    chunk: RetrievalChunk,
    *,
    runtime_model: str | None,
    expected_table: str | None,
) -> bool:
    if not chunk.vector_ref:
        return True
    if runtime_model and chunk.embedding_model != runtime_model:
        return True
    if expected_table and chunk.vector_ref != expected_table:
        return True
    return False


@dataclass(slots=True)
class _PreparedMaterialization:
    result: MaterializedSections
    runtime: RuntimeEmbeddingConfig
    chunks: list[ChunkManifestEntry]
    source_contents: dict[str, str]
    embedding_chunk_ids: list[int]
    embedding_texts: list[str]


def _update_document_steps(
    documents: list[RawFile], chunks: list[RetrievalChunk], indexed_ids: set[int],
) -> None:
    chunk_ids_by_file: dict[str, set[int]] = {}
    for chunk in chunks:
        chunk_ids_by_file.setdefault(chunk.file_id, set()).add(int(chunk.id))
    for document in documents:
        ids = chunk_ids_by_file.get(document.id, set())
        step = (
            DigestStep.EMBEDDED if ids and ids <= indexed_ids
            else DigestStep.CHUNKED if ids else DigestStep.STORED
        )
        if document.current_step != step.value:
            document.current_step = step.value
            document.updated_at = utcnow()


def _prepare_materialization(
    *, course_id: str, shared_inputs: SharedInputs, session_id: str, update_source_documents: bool,
) -> _PreparedMaterialization:
    # No SQL write transaction is held while the vector store writes through
    # its own connection. The course scope serializes these short phases.
    with course_index_write_scope(course_id):
        source_file_ids = [packet.file_id for packet in shared_inputs.source_packets]
        existing_manifest = _load_chunk_manifest(course_id)
        manifest_entries = {
            entry.digest_chunk_uid: entry
            for entry in (existing_manifest.chunks if existing_manifest is not None else [])
            if entry.source_file_id not in source_file_ids
        }
        with managed_session() as session:
            course = get_course_record_by_id(session, course_id)
            if course is None:
                raise RuntimeError(f"Course `{course_id}` not found while materializing retrieval inputs.")
            if not update_source_documents:
                from app.workflows.digest.common.prepare import normalize_markdown_content

                current_sources = {
                    document.id: document
                    for document in session.exec(select(RawFile).where(RawFile.id.in_(source_file_ids))).all()
                }
                for packet in shared_inputs.source_packets:
                    current = current_sources.get(packet.file_id)
                    if (
                        current is not None and current.markdown_content.strip()
                        and normalize_markdown_content(current.markdown_content) != packet.normalized_content
                    ):
                        raise RuntimeError("Retrieval source material was superseded before materialization.")
            runtime = get_runtime_embedding_config()
            writable = get_course_vector_capability(session, course).writable
            expected_table = build_course_index_ref_for_course(course)
            existing_chunks = knowledge_repo.get_chunks_by_source_file_ids(
                session, course_id=course_id, source_file_ids=source_file_ids,
            )
            existing_by_uid = {chunk.digest_chunk_uid: chunk for chunk in existing_chunks}
            source_ids = set(source_file_ids)
            sections = [
                section for section in shared_inputs.section_packets
                if section.source_file_id in source_ids
            ]
            desired_uids = {section.digest_chunk_uid for section in sections}
            stale_chunks = [chunk for chunk in existing_chunks if chunk.digest_chunk_uid not in desired_uids]
            changed_ids = {
                int(chunk.id)
                for section in sections
                if (chunk := existing_by_uid.get(section.digest_chunk_uid)) is not None
                and (chunk.title != section.title or chunk.content != section.normalized_content)
            }
            invalid_ids = changed_ids | {int(chunk.id) for chunk in stale_chunks}
            reused_ids = [int(chunk.id) for chunk in existing_chunks if int(chunk.id) not in invalid_ids]
            indexed_ids = (
                knowledge_repo.list_indexed_embedding_chunk_ids(
                    session, table_name=expected_table, chunk_ids=reused_ids,
                ) if writable and reused_ids else set()
            )
            ready_ids = {
                int(chunk.id) for chunk in existing_chunks
                if int(chunk.id) in indexed_ids and not _chunk_requires_embedding(
                    chunk, runtime_model=runtime.embedding_model, expected_table=expected_table,
                )
            }
            # Delete vectors before starting SQL mutations: sqlite-vec opens
            # an independent write connection to the same database.
            if invalid_ids:
                knowledge_repo.delete_embeddings_by_chunk_ids(
                    session, course_id=course_id, chunk_ids=sorted(invalid_ids),
                )
            for chunk in stale_chunks:
                session.delete(chunk)
            # Remove old unique (file, ordinal) keys before inserting replacements.
            session.flush()
            documents = knowledge_repo.bulk_create_documents(
                session,
                [RawFile(
                    id=packet.file_id, user_id=course.user_id, origin_course_id=course_id,
                    filename=packet.filename, filetype="markdown", file_path="",
                    markdown_content=packet.normalized_content, current_step=DigestStep.STORED.value,
                ) for packet in shared_inputs.source_packets],
                commit=False,
            )
            reused_chunks: list[RetrievalChunk] = []
            new_chunks: list[RetrievalChunk] = []
            for section in sections:
                chunk = existing_by_uid.get(section.digest_chunk_uid)
                if chunk is None:
                    new_chunks.append(RetrievalChunk(
                        course_id=course_id, file_id=section.source_file_id, title=section.title,
                        level=section.level, header_path=section.header_path,
                        chunk_index=section.chunk_index, digest_chunk_uid=section.digest_chunk_uid,
                        build_session_id=session_id, content=section.normalized_content,
                    ))
                    continue
                chunk.file_id = section.source_file_id
                chunk.title = section.title
                chunk.level = section.level
                chunk.header_path = section.header_path
                chunk.chunk_index = section.chunk_index
                chunk.content = section.normalized_content
                chunk.build_session_id = session_id
                chunk.is_active = True
                chunk.updated_at = utcnow()
                if int(chunk.id) in changed_ids:
                    chunk.embedding_model = None
                    chunk.vector_ref = None
                session.add(chunk)
                reused_chunks.append(chunk)
            knowledge_repo.bulk_create_chunks(session, new_chunks, commit=False)
            chunks = [*reused_chunks, *new_chunks]
            _update_document_steps(documents, chunks, ready_ids)
            entries = [ChunkManifestEntry(
                digest_chunk_uid=chunk.digest_chunk_uid, source_file_id=chunk.file_id,
                document_id=chunk.file_id, chunk_id=int(chunk.id),
                content_hash=_chunk_content_hash(title=chunk.title, content=chunk.content),
                title=chunk.title, header_path=chunk.header_path, level=chunk.level,
                chunk_index=chunk.chunk_index, updated_at=chunk.updated_at,
            ) for chunk in chunks]
            result = MaterializedSections(
                build_session_id=session_id, source_file_ids=source_file_ids,
                document_ids=[document.id for document in documents],
                chunk_ids=[entry.chunk_id for entry in entries],
                chunk_uid_to_chunk_id={entry.digest_chunk_uid: entry.chunk_id for entry in entries},
                chunk_id_to_chunk_uid={entry.chunk_id: entry.digest_chunk_uid for entry in entries},
            )
            targets = [chunk for chunk in chunks if writable and int(chunk.id) not in ready_ids]
            prepared = _PreparedMaterialization(
                result=result, runtime=runtime, chunks=entries,
                source_contents={document.id: document.markdown_content for document in documents},
                embedding_chunk_ids=[int(chunk.id) for chunk in targets],
                embedding_texts=[f"{chunk.title}\n{chunk.content}".strip() for chunk in targets],
            )
        # The manifest describes committed chunks, independently of whether
        # embedding succeeds. A delayed embedding completion never rewrites it.
        manifest_entries.update({entry.digest_chunk_uid: entry for entry in entries})
        manifest = KnowledgeChunkManifest(
            course_id=course_id, updated_at=utcnow(), build_session_id=session_id,
            source_file_ids=sorted({
                *(existing_manifest.source_file_ids if existing_manifest is not None else []),
                *source_file_ids,
            }),
            chunks=sorted(
                manifest_entries.values(),
                key=lambda entry: (entry.source_file_id, entry.chunk_index, entry.digest_chunk_uid),
            ),
        )
        _write_chunk_manifest(course_id, manifest)
    logger.info(
        "canonical_chunk_materialization_completed", course_id=course_id, build_session_id=session_id,
        document_count=len(result.document_ids), chunk_count=len(result.chunk_ids),
        reused_chunk_count=len(reused_chunks), created_chunk_count=len(new_chunks),
        deleted_chunk_count=len(stale_chunks),
    )
    return prepared


def _persist_embeddings(
    *, course_id: str, prepared: _PreparedMaterialization, embeddings: list[list[float]],
) -> None:
    with course_index_write_scope(course_id), managed_session() as session:
        runtime = get_runtime_embedding_config()
        course = get_course_record_by_id(session, course_id)
        if (
            course is None or not runtime.available
            or runtime.embedding_model != prepared.runtime.embedding_model
            or runtime.embedding_dim != prepared.runtime.embedding_dim
            or runtime.dimension_explicit != prepared.runtime.dimension_explicit
            or not get_course_vector_capability(session, course).writable
        ):
            raise RuntimeError("Course embedding configuration changed during materialization; retry required.")
        chunks = knowledge_repo.get_chunks_by_ids(session, prepared.result.chunk_ids)
        by_id = {int(chunk.id): chunk for chunk in chunks}
        for entry in prepared.chunks:
            chunk = by_id.get(entry.chunk_id)
            if (
                chunk is None or chunk.course_id != course_id or not chunk.is_active
                or chunk.build_session_id != prepared.result.build_session_id
                or chunk.file_id != entry.source_file_id or chunk.digest_chunk_uid != entry.digest_chunk_uid
                or _chunk_content_hash(title=chunk.title, content=chunk.content) != entry.content_hash
            ):
                raise RuntimeError("Retrieval materialization was superseded while embeddings were running.")
        documents = list(session.exec(
            select(RawFile).where(RawFile.id.in_(prepared.result.document_ids))
        ).all())
        if {document.id: document.markdown_content for document in documents} != prepared.source_contents:
            raise RuntimeError("Retrieval source material was superseded while embeddings were running.")
        if runtime.dimension_explicit and any(len(vector) != runtime.embedding_dim for vector in embeddings):
            raise RuntimeError("Returned vectors do not match the configured embedding dimension.")
        # The session is read-only up to here, so independent vector writes
        # cannot wait on a SQLite write transaction owned by this thread.
        knowledge_repo.bulk_insert_embeddings(
            session, course_id=course_id, chunk_ids=prepared.embedding_chunk_ids,
            embeddings=embeddings, embedding_model=runtime.embedding_model,
        )
        expected_table = build_course_index_ref_for_course(course)
        indexed_ids = knowledge_repo.list_indexed_embedding_chunk_ids(
            session, table_name=expected_table, chunk_ids=prepared.result.chunk_ids,
        )
        ready_ids = {
            int(chunk.id) for chunk in chunks
            if int(chunk.id) in indexed_ids and not _chunk_requires_embedding(
                chunk, runtime_model=runtime.embedding_model, expected_table=expected_table,
            )
        }
        _update_document_steps(documents, chunks, ready_ids)


async def materialize_shared_inputs(
    *,
    course_id: str,
    shared_inputs: SharedInputs,
    build_session_id: str | None = None,
    update_source_documents: bool = False,
) -> MaterializedSections:
    """Materialize chunks, await embeddings without a DB session, then validate and persist."""

    prepared = await run_sync_and_drain(
        _prepare_materialization, course_id=course_id, shared_inputs=shared_inputs,
        session_id=build_session_id or uuid4().hex,
        update_source_documents=update_source_documents,
    )
    if prepared.embedding_chunk_ids:
        embeddings = await aembed_texts_for_ingestion(
            prepared.embedding_texts, model=prepared.runtime.embedding_model, soft_fail=True,
        )
        if embeddings:
            await run_sync_and_drain(
                _persist_embeddings, course_id=course_id, prepared=prepared, embeddings=embeddings,
            )
        else:
            logger.warning(
                "canonical_chunk_embedding_soft_skipped", course_id=course_id,
                build_session_id=prepared.result.build_session_id,
                reason="embedding_call_unavailable_or_failed", chunk_count=len(prepared.embedding_chunk_ids),
            )
    return prepared.result
