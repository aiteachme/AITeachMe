"""Unified LlamaIndex vector-index manager for subject knowledge chunks.

The canonical business source of truth remains ``retrieval_chunk``. This
module owns only the vector index lifecycle: upsert, query, delete, clear and
local persistence.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from threading import RLock
from typing import Any

import structlog
import sqlalchemy as sa
from llama_index.core.schema import TextNode
from llama_index.core.vector_stores.types import (
    MetadataFilter,
    MetadataFilters,
    VectorStoreQuery,
)
from sqlalchemy.engine.url import make_url

from app.shared.infra.settings import get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.runtime import is_cloud_mode
from app.shared.infra.storage import get_content_store, resolve_subject_storage_scope, run_store_sync
from app.shared.infra.search.llamaindex_index.sqlite_vec_store import SQLiteVecVectorStore
from app.shared.infra.subject.settings import (
    build_postgres_subject_index_name,
    build_subject_index_ref_for_subject,
    extract_postgres_subject_index_data_table_name,
    get_subject_embedding_binding,
)

logger = structlog.get_logger(__name__)

_SUBJECT_LOCKS: dict[str, RLock] = {}
_SUBJECT_LOCKS_GUARD = RLock()


@dataclass(slots=True)
class IndexedChunk:
    """One chunk payload stored as a LlamaIndex node."""

    chunk_id: int
    file_id: str
    subject: str
    title: str
    header_path: str
    content: str
    digest_chunk_uid: str = ""
    embedding: list[float] | None = None


@dataclass(slots=True)
class SubjectIndexHit:
    """One vector-index hit returned by the LlamaIndex store."""

    chunk_id: int
    score: float
    source: str = "llamaindex"


def _subject_lock(subject: str) -> RLock:
    normalized = subject.strip()
    with _SUBJECT_LOCKS_GUARD:
        lock = _SUBJECT_LOCKS.get(normalized)
        if lock is None:
            lock = RLock()
            _SUBJECT_LOCKS[normalized] = lock
        return lock


def _local_index_prefix(subject: str) -> str:
    normalized_subject = subject.strip()
    scope = resolve_subject_storage_scope(normalized_subject)
    return f"{scope.namespace}/rag_index/"


def _node_id(chunk_id: int) -> str:
    return str(int(chunk_id))


def _chunk_id_from_node_id(node_id: str) -> int | None:
    try:
        return int(str(node_id))
    except (TypeError, ValueError):
        return None


def _node_metadata(chunk: IndexedChunk) -> dict[str, Any]:
    return {
        "subject": chunk.subject,
        "chunk_id": int(chunk.chunk_id),
        "file_id": chunk.file_id,
        "title": chunk.title,
        "header_path": chunk.header_path,
        "digest_chunk_uid": chunk.digest_chunk_uid,
        "source": "llamaindex",
    }


def _to_text_node(chunk: IndexedChunk, embedding: list[float]) -> TextNode:
    return TextNode(
        id_=_node_id(chunk.chunk_id),
        text=chunk.content,
        embedding=embedding,
        metadata=_node_metadata(chunk),
        excluded_embed_metadata_keys=["subject", "chunk_id", "file_id", "source"],
        excluded_llm_metadata_keys=["subject", "chunk_id", "file_id", "source"],
    )


def _load_local_store(
    subject: str,
    *,
    embedding_dim: int | None = None,
) -> SQLiteVecVectorStore:
    return SQLiteVecVectorStore(
        subject=subject.strip(),
        embedding_dim=embedding_dim,
    )


def _subject_filter(subject: str) -> MetadataFilters:
    return MetadataFilters(filters=[MetadataFilter(key="subject", value=subject.strip())])


def _sync_database_url() -> str:
    database_url = (get_env("DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError("APP_MODE=cloud requires DATABASE_URL for LlamaIndex PGVectorStore.")
    return database_url


def _postgres_identifier_is_safe(identifier: str | None) -> bool:
    return bool(identifier and re.fullmatch(r"[a-z_][a-z0-9_]*", identifier))


def _subject_record_snapshot(subject: str):
    from sqlmodel import Session, select

    from app.models.subject import Subject
    from app.shared.infra.database import get_engine

    normalized_subject = subject.strip()
    if not normalized_subject:
        return None

    with Session(get_engine()) as session:
        return session.exec(
            select(Subject).where(Subject.slug == normalized_subject)
        ).first()


def _subject_binding_snapshot(subject: str):
    subject_row = _subject_record_snapshot(subject)
    if subject_row is None:
        return None
    return get_subject_embedding_binding(subject_row)


def _subject_store_spec(
    subject: str,
    *,
    embedding_dim: int | None = None,
) -> tuple[str, int]:
    subject_row = _subject_record_snapshot(subject)
    if subject_row is None:
        raise RuntimeError(f"Subject '{subject.strip()}' not found for vector-store resolution.")
    binding = get_subject_embedding_binding(subject_row)
    index_name = build_postgres_subject_index_name(
        subject_row.slug,
        owner_user_id=subject_row.user_id,
    )
    resolved_dim = (
        embedding_dim
        or (binding.embedding_dim if binding is not None else None)
        or get_settings().embedding_dim
    )
    if resolved_dim is None or int(resolved_dim) <= 0:
        raise RuntimeError(
            f"Cannot resolve embedding dimension for subject '{subject.strip()}'."
        )
    return index_name, int(resolved_dim)


def _load_postgres_store(
    *,
    subject: str,
    embedding_dim: int | None = None,
):
    try:
        from llama_index.vector_stores.postgres import PGVectorStore
    except ImportError as exc:  # pragma: no cover - depends on cloud extras
        raise RuntimeError(
            "Cloud LlamaIndex indexing requires `llama-index-vector-stores-postgres`."
        ) from exc

    index_name, resolved_dim = _subject_store_spec(
        subject,
        embedding_dim=embedding_dim,
    )
    sync_url = make_url(_sync_database_url()).set(drivername="postgresql+psycopg2")
    async_url = sync_url.set(drivername="postgresql+asyncpg")
    return PGVectorStore.from_params(
        connection_string=sync_url,
        async_connection_string=async_url,
        table_name=index_name,
        embed_dim=resolved_dim,
        use_jsonb=True,
        hnsw_kwargs={
            "hnsw_m": 16,
            "hnsw_ef_construction": 64,
            "hnsw_ef_search": 40,
            "hnsw_dist_method": "vector_cosine_ops",
        },
    )


def prepare_postgres_store(
    *,
    subject: str | None = None,
    embedding_dim: int | None = None,
) -> None:
    """Initialize or verify cloud PGVectorStore support.

    When ``subject`` is omitted, this only verifies that the PostgreSQL
    vector-store dependency and connection string are usable. When a subject is
    supplied, its subject-scoped PGVectorStore table is initialized on demand.
    """

    if not is_cloud_mode():
        return
    if not subject:
        try:
            from llama_index.vector_stores.postgres import PGVectorStore
        except ImportError as exc:  # pragma: no cover - depends on cloud extras
            raise RuntimeError(
                "Cloud LlamaIndex indexing requires `llama-index-vector-stores-postgres`."
            ) from exc
        del PGVectorStore
        _sync_database_url()
        logger.info("llamaindex_postgres_store_support_ready")
        return

    index_name, resolved_dim = _subject_store_spec(subject, embedding_dim=embedding_dim)
    _load_postgres_store(
        subject=subject,
        embedding_dim=resolved_dim,
    )
    logger.info(
        "llamaindex_postgres_store_prepared",
        subject=subject.strip(),
        table_name=index_name,
        embedding_dim=resolved_dim,
    )


def _load_store(
    subject: str,
    *,
    embedding_dim: int | None = None,
):
    if is_cloud_mode():
        return _load_postgres_store(
            subject=subject,
            embedding_dim=embedding_dim,
        )
    return _load_local_store(subject, embedding_dim=embedding_dim)


def _delete_node_ids(vector_store: Any, chunk_ids: list[int], *, subject: str) -> None:
    node_ids = [_node_id(chunk_id) for chunk_id in chunk_ids]
    if not node_ids:
        return

    delete_nodes = getattr(vector_store, "delete_nodes", None)
    if callable(delete_nodes):
        delete_nodes(node_ids=node_ids, filters=_subject_filter(subject))
        return

    for node_id in node_ids:
        delete = getattr(vector_store, "delete", None)
        if callable(delete):
            delete(ref_doc_id=node_id)


def upsert_chunks(subject: str, chunks: list[IndexedChunk]) -> None:
    """Upsert pre-embedded chunks into the active LlamaIndex vector store."""

    normalized_subject = subject.strip()
    if not normalized_subject or not chunks:
        return

    nodes: list[TextNode] = []
    embedding_dim: int | None = None
    for chunk in chunks:
        if chunk.embedding is None:
            raise ValueError(f"IndexedChunk {chunk.chunk_id} is missing an embedding.")
        chunk_dim = len(chunk.embedding)
        if chunk_dim <= 0:
            raise ValueError(f"IndexedChunk {chunk.chunk_id} has an empty embedding.")
        if embedding_dim is None:
            embedding_dim = chunk_dim
        elif embedding_dim != chunk_dim:
            raise ValueError(
                "All IndexedChunk embeddings must share the same dimension. "
                f"Got {embedding_dim} and {chunk_dim}."
            )
        nodes.append(_to_text_node(chunk, chunk.embedding))

    with _subject_lock(normalized_subject):
        vector_store = _load_store(
            normalized_subject,
            embedding_dim=embedding_dim,
        )
        _delete_node_ids(
            vector_store,
            [chunk.chunk_id for chunk in chunks],
            subject=normalized_subject,
        )
        vector_store.add(nodes)

    logger.info(
        "llamaindex_chunks_upserted",
        subject=normalized_subject,
        chunk_count=len(chunks),
        backend="postgres" if is_cloud_mode() else "sqlite-vec",
    )


def rebuild_subject_index(subject: str, chunks: list[IndexedChunk]) -> None:
    """Replace one subject index with the supplied pre-embedded chunks."""

    clear_subject_index(subject)
    upsert_chunks(subject, chunks)


def delete_chunks(subject: str, chunk_ids: list[int]) -> None:
    """Delete selected chunks from the active LlamaIndex vector store."""

    normalized_subject = subject.strip()
    normalized_ids = [int(chunk_id) for chunk_id in chunk_ids if chunk_id is not None]
    if not normalized_subject or not normalized_ids:
        return
    if not subject_index_exists(normalized_subject):
        return

    with _subject_lock(normalized_subject):
        vector_store = _load_store(normalized_subject)
        _delete_node_ids(vector_store, normalized_ids, subject=normalized_subject)

    logger.info(
        "llamaindex_chunks_deleted",
        subject=normalized_subject,
        chunk_count=len(normalized_ids),
    )


def clear_subject_index(subject: str) -> None:
    """Remove all vector-index entries for one subject."""

    normalized_subject = subject.strip()
    if not normalized_subject:
        return
    with _subject_lock(normalized_subject):
        if is_cloud_mode():
            if not subject_index_exists(normalized_subject):
                return
            from app.shared.infra.database import get_engine

            subject_row = _subject_record_snapshot(normalized_subject)
            if subject_row is None:
                return
            vector_ref = build_subject_index_ref_for_subject(subject_row)
            data_table = extract_postgres_subject_index_data_table_name(vector_ref)
            if not _postgres_identifier_is_safe(data_table):
                return
            with get_engine().begin() as connection:
                connection.execute(sa.text(f"DROP TABLE IF EXISTS public.{data_table}"))
        else:
            vector_store = _load_local_store(normalized_subject)
            vector_store.clear()
            # Remove legacy SimpleVectorStore JSON payloads from older builds.
            try:
                cs = get_content_store()
                run_store_sync(cs.delete_prefix, _local_index_prefix(normalized_subject), default=0)
            except Exception as exc:  # pragma: no cover - legacy cleanup only
                logger.warning(
                    "llamaindex_legacy_local_store_cleanup_failed",
                    subject=normalized_subject,
                    error=str(exc),
                )

    logger.info("llamaindex_subject_index_cleared", subject=normalized_subject)


def subject_index_exists(subject: str) -> bool:
    """Return whether a subject has any persisted LlamaIndex index payload."""

    normalized_subject = subject.strip()
    if not normalized_subject:
        return False
    if is_cloud_mode():
        from app.shared.infra.database import get_engine, vector_table_exists

        subject_row = _subject_record_snapshot(normalized_subject)
        if subject_row is None:
            return False
        expected_ref = build_subject_index_ref_for_subject(subject_row)
        with get_engine().connect() as connection:
            return vector_table_exists(connection, expected_ref)
    return _load_local_store(normalized_subject).subject_has_rows()


def count_indexed_chunks(subject: str, chunk_ids: list[int]) -> int:
    """Count indexed chunk IDs for local consistency checks."""

    normalized_subject = subject.strip()
    normalized_ids = {_node_id(chunk_id) for chunk_id in chunk_ids if chunk_id is not None}
    if not normalized_subject or not normalized_ids:
        return 0
    if is_cloud_mode():
        from app.shared.infra.database import get_engine, vector_table_exists

        subject_row = _subject_record_snapshot(normalized_subject)
        if subject_row is None:
            return 0
        vector_ref = build_subject_index_ref_for_subject(subject_row)
        data_table = extract_postgres_subject_index_data_table_name(vector_ref)
        if not _postgres_identifier_is_safe(data_table):
            return 0
        with get_engine().connect() as connection:
            if not vector_table_exists(connection, vector_ref):
                return 0
            params = {f"node_id_{index}": node_id for index, node_id in enumerate(sorted(normalized_ids))}
            placeholders = ", ".join(f":{name}" for name in params)
            result = connection.execute(
                sa.text(
                    f"SELECT COUNT(*) FROM public.{data_table} "
                    f"WHERE node_id IN ({placeholders})"
                ),
                params,
            ).scalar_one()
        return int(result or 0)

    vector_store = _load_local_store(normalized_subject)
    return vector_store.count_node_ids(normalized_ids)


def query_subject_index(
    subject: str,
    query_embedding: list[float],
    *,
    top_k: int = 5,
) -> list[SubjectIndexHit]:
    """Query the active vector store with a precomputed embedding."""

    normalized_subject = subject.strip()
    if not normalized_subject or not query_embedding or top_k <= 0:
        return []
    if not subject_index_exists(normalized_subject):
        return []

    if is_cloud_mode():
        binding = _subject_binding_snapshot(normalized_subject)
        if (
            binding is not None
            and binding.embedding_dim is not None
            and int(binding.embedding_dim) != len(query_embedding)
        ):
            logger.warning(
                "llamaindex_query_embedding_dimension_mismatch",
                subject=normalized_subject,
                expected_dim=int(binding.embedding_dim),
                actual_dim=len(query_embedding),
            )
            return []

    vector_store = _load_store(
        normalized_subject,
        embedding_dim=len(query_embedding),
    )
    query = VectorStoreQuery(
        query_embedding=query_embedding,
        similarity_top_k=top_k,
        filters=_subject_filter(normalized_subject),
    )
    result = vector_store.query(query)

    hits: list[SubjectIndexHit] = []
    ids = list(result.ids or [])
    scores = list(result.similarities or [])
    for index, node_id in enumerate(ids):
        chunk_id = _chunk_id_from_node_id(node_id)
        if chunk_id is None:
            continue
        score = float(scores[index]) if index < len(scores) and scores[index] is not None else 0.0
        hits.append(SubjectIndexHit(chunk_id=chunk_id, score=score))
    return hits


async def retrieve_subject_chunks(
    subject: str,
    query: str,
    *,
    top_k: int = 5,
    query_embedding: list[float] | None = None,
) -> list[SubjectIndexHit]:
    """Embed a query and retrieve matching chunk IDs from LlamaIndex."""

    normalized_query = query.strip()
    if not normalized_query or top_k <= 0:
        return []

    embedding = query_embedding
    if embedding is None:
        from app.shared.infra.embedding import aembed_texts

        binding = _subject_binding_snapshot(subject)
        model_name = binding.embedding_model if binding is not None else None
        vectors = await aembed_texts(
            [normalized_query],
            soft_fail=True,
            model=model_name,
        )
        embedding = vectors[0] if vectors else []

    if is_cloud_mode():
        return await asyncio.to_thread(
            query_subject_index,
            subject,
            embedding,
            top_k=top_k,
        )
    return query_subject_index(subject, embedding, top_k=top_k)


__all__ = [
    "IndexedChunk",
    "SubjectIndexHit",
    "clear_subject_index",
    "count_indexed_chunks",
    "delete_chunks",
    "query_subject_index",
    "rebuild_subject_index",
    "retrieve_subject_chunks",
    "subject_index_exists",
    "upsert_chunks",
]
