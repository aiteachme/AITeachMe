"""Unified LlamaIndex vector-index manager for subject knowledge chunks.

The canonical business source of truth remains ``retrieval_chunk``. This
module owns only the vector index lifecycle: upsert, query, delete, clear and
local persistence.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from threading import RLock
from typing import Any

import structlog
from llama_index.core.schema import TextNode
from llama_index.core.vector_stores.simple import SimpleVectorStore
from llama_index.core.vector_stores.types import (
    MetadataFilter,
    MetadataFilters,
    VectorStoreQuery,
)
from sqlalchemy.engine.url import make_url

from app.shared.infra.config import get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.runtime import is_cloud_mode
from app.shared.infra.storage import get_content_store, run_store_sync

logger = structlog.get_logger(__name__)

_LOCAL_VECTOR_STORE_FILENAME = "vector_store.json"
_POSTGRES_TABLE_NAME = "atm_llamaindex_rag"
_SUBJECT_LOCKS: dict[str, RLock] = {}
_SUBJECT_LOCKS_GUARD = RLock()


@dataclass(slots=True)
class IndexedChunk:
    """One chunk payload stored as a LlamaIndex node."""

    chunk_id: int
    document_id: int
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
    return f"{subject.strip()}/rag_index/"


def _local_vector_store_key(subject: str) -> str:
    return f"{_local_index_prefix(subject)}{_LOCAL_VECTOR_STORE_FILENAME}"


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
        "document_id": int(chunk.document_id),
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
        excluded_embed_metadata_keys=["subject", "chunk_id", "document_id", "source"],
        excluded_llm_metadata_keys=["subject", "chunk_id", "document_id", "source"],
    )


def _load_local_store(subject: str) -> SimpleVectorStore:
    cs = get_content_store()
    payload = run_store_sync(cs.read_text, _local_vector_store_key(subject), default=None)
    if not payload:
        return SimpleVectorStore()
    try:
        return SimpleVectorStore.from_json(payload)
    except Exception as exc:
        logger.warning("llamaindex_local_store_load_failed", subject=subject, error=str(exc))
        return SimpleVectorStore()


def _persist_local_store(subject: str, vector_store: SimpleVectorStore) -> None:
    cs = get_content_store()
    run_store_sync(cs.write_text, _local_vector_store_key(subject), vector_store.to_json())


def _subject_filter(subject: str) -> MetadataFilters:
    return MetadataFilters(filters=[MetadataFilter(key="subject", value=subject.strip())])


def _sync_database_url() -> str:
    database_url = (get_env("DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError("APP_MODE=cloud requires DATABASE_URL for LlamaIndex PGVectorStore.")
    return database_url


def _load_postgres_store():
    try:
        from llama_index.vector_stores.postgres import PGVectorStore
    except ImportError as exc:  # pragma: no cover - depends on cloud extras
        raise RuntimeError(
            "Cloud LlamaIndex indexing requires `llama-index-vector-stores-postgres`."
        ) from exc

    settings = get_settings()
    url = make_url(_sync_database_url())
    return PGVectorStore.from_params(
        database=url.database or "",
        host=url.host or "localhost",
        password=url.password or "",
        port=url.port or 5432,
        user=url.username or "",
        table_name=_POSTGRES_TABLE_NAME,
        embed_dim=settings.embedding_dim,
        hnsw_kwargs={
            "hnsw_m": 16,
            "hnsw_ef_construction": 64,
            "hnsw_ef_search": 40,
            "hnsw_dist_method": "vector_cosine_ops",
        },
    )


def _load_store(subject: str):
    if is_cloud_mode():
        return _load_postgres_store()
    return _load_local_store(subject)


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
    for chunk in chunks:
        if chunk.embedding is None:
            raise ValueError(f"IndexedChunk {chunk.chunk_id} is missing an embedding.")
        nodes.append(_to_text_node(chunk, chunk.embedding))

    with _subject_lock(normalized_subject):
        vector_store = _load_store(normalized_subject)
        _delete_node_ids(
            vector_store,
            [chunk.chunk_id for chunk in chunks],
            subject=normalized_subject,
        )
        vector_store.add(nodes)
        if not is_cloud_mode():
            _persist_local_store(normalized_subject, vector_store)

    logger.info(
        "llamaindex_chunks_upserted",
        subject=normalized_subject,
        chunk_count=len(chunks),
        backend="postgres" if is_cloud_mode() else "simple",
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
    if not is_cloud_mode() and not subject_index_exists(normalized_subject):
        return

    with _subject_lock(normalized_subject):
        vector_store = _load_store(normalized_subject)
        _delete_node_ids(vector_store, normalized_ids, subject=normalized_subject)
        if not is_cloud_mode():
            _persist_local_store(normalized_subject, vector_store)

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
            vector_store = _load_postgres_store()
            delete_nodes = getattr(vector_store, "delete_nodes", None)
            if callable(delete_nodes):
                delete_nodes(filters=_subject_filter(normalized_subject))
        else:
            cs = get_content_store()
            run_store_sync(cs.delete_prefix, _local_index_prefix(normalized_subject), default=0)

    logger.info("llamaindex_subject_index_cleared", subject=normalized_subject)


def subject_index_exists(subject: str) -> bool:
    """Return whether a subject has any persisted LlamaIndex index payload."""

    normalized_subject = subject.strip()
    if not normalized_subject:
        return False
    if is_cloud_mode():
        return True
    cs = get_content_store()
    return bool(run_store_sync(cs.exists, _local_vector_store_key(normalized_subject), default=False))


def count_indexed_chunks(subject: str, chunk_ids: list[int]) -> int:
    """Count indexed chunk IDs for local consistency checks."""

    normalized_subject = subject.strip()
    normalized_ids = {_node_id(chunk_id) for chunk_id in chunk_ids if chunk_id is not None}
    if not normalized_subject or not normalized_ids:
        return 0
    if is_cloud_mode():
        return len(normalized_ids)

    vector_store = _load_local_store(normalized_subject)
    return sum(1 for node_id in normalized_ids if node_id in vector_store.data.embedding_dict)


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
    if not is_cloud_mode() and not subject_index_exists(normalized_subject):
        return []

    vector_store = _load_store(normalized_subject)
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

        vectors = await aembed_texts([normalized_query])
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
