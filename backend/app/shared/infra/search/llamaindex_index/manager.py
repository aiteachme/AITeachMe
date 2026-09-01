"""Unified LlamaIndex vector-index manager for course knowledge chunks.

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
from app.shared.infra.exceptions import CourseRegistryNotFoundError
from app.shared.infra.runtime import is_cloud_mode
from app.shared.infra.storage import get_content_store, resolve_course_storage_scope, run_store_sync
from app.shared.infra.search.llamaindex_index.sqlite_vec_store import SQLiteVecVectorStore
from app.shared.infra.course.settings import (
    build_postgres_course_index_name,
    build_course_index_ref_for_course,
    extract_postgres_course_index_data_table_name,
    get_course_embedding_binding,
)

logger = structlog.get_logger(__name__)

_COURSE_LOCKS: dict[str, RLock] = {}
_COURSE_LOCKS_GUARD = RLock()


@dataclass(slots=True)
class IndexedChunk:
    """One chunk payload stored as a LlamaIndex node."""

    chunk_id: int
    file_id: str
    course_id: str
    title: str
    header_path: str
    content: str
    digest_chunk_uid: str = ""
    embedding: list[float] | None = None


@dataclass(slots=True)
class CourseIndexHit:
    """One vector-index hit returned by the LlamaIndex store."""

    chunk_id: int
    score: float
    source: str = "llamaindex"


def _course_lock(course_id: str) -> RLock:
    normalized = course_id.strip()
    with _COURSE_LOCKS_GUARD:
        lock = _COURSE_LOCKS.get(normalized)
        if lock is None:
            lock = RLock()
            _COURSE_LOCKS[normalized] = lock
        return lock


def _local_index_prefix(course_id: str) -> str:
    normalized_course_id = course_id.strip()
    scope = resolve_course_storage_scope(normalized_course_id)
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
        "course_id": chunk.course_id,
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
        excluded_embed_metadata_keys=["course_id", "chunk_id", "file_id", "source"],
        excluded_llm_metadata_keys=["course_id", "chunk_id", "file_id", "source"],
    )


def _load_local_store(
    course_id: str,
    *,
    embedding_dim: int | None = None,
) -> SQLiteVecVectorStore:
    return SQLiteVecVectorStore(
        course_id=course_id.strip(),
        embedding_dim=embedding_dim,
    )


def _course_filter(course_id: str) -> MetadataFilters:
    return MetadataFilters(filters=[MetadataFilter(key="course_id", value=course_id.strip())])


def _sync_database_url() -> str:
    database_url = (get_env("DATABASE_URL") or "").strip()
    if not database_url:
        raise RuntimeError("APP_MODE=cloud requires DATABASE_URL for LlamaIndex PGVectorStore.")
    return database_url


def _postgres_identifier_is_safe(identifier: str | None) -> bool:
    return bool(identifier and re.fullmatch(r"[a-z_][a-z0-9_]*", identifier))


def _course_record_snapshot(course_id: str):
    from sqlmodel import Session, select

    from app.models.course import Course
    from app.shared.infra.database import get_engine

    normalized_course_id = course_id.strip()
    if not normalized_course_id:
        return None

    with Session(get_engine()) as session:
        return session.exec(
            select(Course).where(Course.id == normalized_course_id)
        ).first()


def _course_binding_snapshot(course_id: str):
    course_row = _course_record_snapshot(course_id)
    if course_row is None:
        return None
    return get_course_embedding_binding(course_row)


def _course_store_spec(
    course_id: str,
    *,
    embedding_dim: int | None = None,
) -> tuple[str, int]:
    course_row = _course_record_snapshot(course_id)
    if course_row is None:
        raise RuntimeError(f"Course '{course_id.strip()}' not found for vector-store resolution.")
    binding = get_course_embedding_binding(course_row)
    index_name = build_postgres_course_index_name(
        course_row.id,
        owner_user_id=course_row.user_id,
    )
    resolved_dim = (
        embedding_dim
        or (binding.embedding_dim if binding is not None else None)
        or get_settings().embedding_dim
    )
    if resolved_dim is None or int(resolved_dim) <= 0:
        raise RuntimeError(
            f"Cannot resolve embedding dimension for course '{course_id.strip()}'."
        )
    return index_name, int(resolved_dim)


def _load_postgres_store(
    *,
    course_id: str,
    embedding_dim: int | None = None,
):
    try:
        from llama_index.vector_stores.postgres import PGVectorStore
    except ImportError as exc:  # pragma: no cover - depends on cloud extras
        raise RuntimeError(
            "Cloud LlamaIndex indexing requires `llama-index-vector-stores-postgres`."
        ) from exc

    index_name, resolved_dim = _course_store_spec(
        course_id,
        embedding_dim=embedding_dim,
    )
    sync_url = make_url(_sync_database_url()).set(drivername="postgresql+psycopg2")
    async_url = sync_url.set(drivername="postgresql+asyncpg")
    # PGVectorStore coerces URL objects with str(), which masks the password as
    # a literal "***". Render credential-bearing strings explicitly instead.
    return PGVectorStore(
        connection_string=sync_url.render_as_string(hide_password=False),
        async_connection_string=async_url.render_as_string(hide_password=False),
        table_name=index_name,
        embed_dim=resolved_dim,
        use_jsonb=True,
        hnsw_kwargs={
            "hnsw_m": 16,
            "hnsw_ef_construction": 64,
            "hnsw_ef_search": 40,
            "hnsw_dist_method": "vector_cosine_ops",
        },
        initialization_fail_on_error=True,
    )


def prepare_postgres_store(
    *,
    course_id: str | None = None,
    embedding_dim: int | None = None,
) -> None:
    """Initialize or verify cloud PGVectorStore support.

    When ``course_id`` is omitted, this only verifies that the PostgreSQL
    vector-store dependency and connection string are usable. When a course is
    supplied, its course-scoped PGVectorStore table is initialized on demand.
    """

    if not is_cloud_mode():
        return
    if not course_id:
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

    index_name, resolved_dim = _course_store_spec(course_id, embedding_dim=embedding_dim)
    _load_postgres_store(
        course_id=course_id,
        embedding_dim=resolved_dim,
    )
    logger.info(
        "llamaindex_postgres_store_prepared",
        course_id=course_id.strip(),
        table_name=index_name,
        embedding_dim=resolved_dim,
    )


def _load_store(
    course_id: str,
    *,
    embedding_dim: int | None = None,
):
    if is_cloud_mode():
        return _load_postgres_store(
            course_id=course_id,
            embedding_dim=embedding_dim,
        )
    return _load_local_store(course_id, embedding_dim=embedding_dim)


def _delete_node_ids(vector_store: Any, chunk_ids: list[int], *, course_id: str) -> None:
    node_ids = [_node_id(chunk_id) for chunk_id in chunk_ids]
    if not node_ids:
        return

    delete_nodes = getattr(vector_store, "delete_nodes", None)
    if callable(delete_nodes):
        delete_nodes(node_ids=node_ids, filters=_course_filter(course_id))
        return

    for node_id in node_ids:
        delete = getattr(vector_store, "delete", None)
        if callable(delete):
            delete(ref_doc_id=node_id)


def upsert_chunks(course_id: str, chunks: list[IndexedChunk]) -> None:
    """Upsert pre-embedded chunks into the active LlamaIndex vector store."""

    normalized_course_id = course_id.strip()
    if not normalized_course_id or not chunks:
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

    with _course_lock(normalized_course_id):
        vector_store = _load_store(
            normalized_course_id,
            embedding_dim=embedding_dim,
        )
        _delete_node_ids(
            vector_store,
            [chunk.chunk_id for chunk in chunks],
            course_id=normalized_course_id,
        )
        vector_store.add(nodes)

    expected_chunk_ids = {int(chunk.chunk_id) for chunk in chunks}
    indexed_chunk_ids = list_indexed_chunk_ids(
        normalized_course_id,
        sorted(expected_chunk_ids),
    )
    if indexed_chunk_ids != expected_chunk_ids:
        raise RuntimeError(
            "Vector index write verification failed for course "
            f"'{normalized_course_id}': expected {len(expected_chunk_ids)} chunks, "
            f"found {len(indexed_chunk_ids)}."
        )

    logger.info(
        "llamaindex_chunks_upserted",
        course_id=normalized_course_id,
        chunk_count=len(chunks),
        verified_chunk_count=len(indexed_chunk_ids),
        backend="postgres" if is_cloud_mode() else "sqlite-vec",
    )


def rebuild_course_index(course_id: str, chunks: list[IndexedChunk]) -> None:
    """Replace one course index with the supplied pre-embedded chunks."""

    clear_course_index(course_id)
    upsert_chunks(course_id, chunks)


def delete_chunks(course_id: str, chunk_ids: list[int]) -> None:
    """Delete selected chunks from the active LlamaIndex vector store."""

    normalized_course_id = course_id.strip()
    normalized_ids = [int(chunk_id) for chunk_id in chunk_ids if chunk_id is not None]
    if not normalized_course_id or not normalized_ids:
        return
    if not course_index_exists(normalized_course_id):
        return

    with _course_lock(normalized_course_id):
        vector_store = _load_store(normalized_course_id)
        _delete_node_ids(vector_store, normalized_ids, course_id=normalized_course_id)

    logger.info(
        "llamaindex_chunks_deleted",
        course_id=normalized_course_id,
        chunk_count=len(normalized_ids),
    )


def clear_course_index(course_id: str) -> None:
    """Remove all vector-index entries for one course."""

    normalized_course_id = course_id.strip()
    if not normalized_course_id:
        return
    with _course_lock(normalized_course_id):
        if is_cloud_mode():
            if not course_index_exists(normalized_course_id):
                return
            from app.shared.infra.database import get_engine

            course_row = _course_record_snapshot(normalized_course_id)
            if course_row is None:
                return
            vector_ref = build_course_index_ref_for_course(course_row)
            data_table = extract_postgres_course_index_data_table_name(vector_ref)
            if not _postgres_identifier_is_safe(data_table):
                return
            with get_engine().begin() as connection:
                connection.execute(sa.text(f"DROP TABLE IF EXISTS public.{data_table}"))
        else:
            vector_store = _load_local_store(normalized_course_id)
            vector_store.clear()
            # Remove legacy SimpleVectorStore JSON payloads from older builds.
            try:
                cs = get_content_store()
                run_store_sync(cs.delete_prefix, _local_index_prefix(normalized_course_id), default=0)
            except CourseRegistryNotFoundError:
                pass
            except Exception as exc:  # pragma: no cover - legacy cleanup only
                logger.warning(
                    "llamaindex_legacy_local_store_cleanup_failed",
                    course_id=normalized_course_id,
                    error=str(exc),
                )

    logger.info("llamaindex_course_index_cleared", course_id=normalized_course_id)


def course_index_exists(course_id: str) -> bool:
    """Return whether a course has any persisted LlamaIndex index payload."""

    normalized_course_id = course_id.strip()
    if not normalized_course_id:
        return False
    if is_cloud_mode():
        from app.shared.infra.database import get_engine, vector_table_exists

        course_row = _course_record_snapshot(normalized_course_id)
        if course_row is None:
            return False
        expected_ref = build_course_index_ref_for_course(course_row)
        with get_engine().connect() as connection:
            return vector_table_exists(connection, expected_ref)
    return _load_local_store(normalized_course_id).course_has_rows()


def count_indexed_chunks(course_id: str, chunk_ids: list[int]) -> int:
    """Count indexed chunk IDs for local consistency checks."""

    normalized_course_id = course_id.strip()
    normalized_ids = {_node_id(chunk_id) for chunk_id in chunk_ids if chunk_id is not None}
    if not normalized_course_id or not normalized_ids:
        return 0
    if is_cloud_mode():
        from app.shared.infra.database import get_engine, vector_table_exists

        course_row = _course_record_snapshot(normalized_course_id)
        if course_row is None:
            return 0
        vector_ref = build_course_index_ref_for_course(course_row)
        data_table = extract_postgres_course_index_data_table_name(vector_ref)
        if not _postgres_identifier_is_safe(data_table):
            return 0
        with get_engine().connect() as connection:
            if not vector_table_exists(connection, vector_ref):
                return 0
            params = {
                f"node_id_{index}": node_id
                for index, node_id in enumerate(sorted(normalized_ids))
            }
            placeholders = ", ".join(f":{name}" for name in params)
            result = connection.execute(
                sa.text(
                    f"SELECT COUNT(*) FROM public.{data_table} "
                    f"WHERE node_id IN ({placeholders})"
                ),
                params,
            ).scalar_one()
        return int(result or 0)

    vector_store = _load_local_store(normalized_course_id)
    return vector_store.count_node_ids(normalized_ids)


def list_indexed_chunk_ids(course_id: str, chunk_ids: list[int]) -> set[int]:
    """Return indexed chunk IDs for targeted consistency checks."""

    normalized_course_id = course_id.strip()
    normalized_ids = {_node_id(chunk_id) for chunk_id in chunk_ids if chunk_id is not None}
    if not normalized_course_id or not normalized_ids:
        return set()
    if is_cloud_mode():
        from app.shared.infra.database import get_engine, vector_table_exists

        course_row = _course_record_snapshot(normalized_course_id)
        if course_row is None:
            return set()
        vector_ref = build_course_index_ref_for_course(course_row)
        data_table = extract_postgres_course_index_data_table_name(vector_ref)
        if not _postgres_identifier_is_safe(data_table):
            return set()
        with get_engine().connect() as connection:
            if not vector_table_exists(connection, vector_ref):
                return set()
            params = {f"node_id_{index}": node_id for index, node_id in enumerate(sorted(normalized_ids))}
            placeholders = ", ".join(f":{name}" for name in params)
            rows = connection.execute(
                sa.text(
                    f"SELECT node_id FROM public.{data_table} "
                    f"WHERE node_id IN ({placeholders})"
                ),
                params,
            ).scalars()
            return {
                chunk_id
                for node_id in rows
                if (chunk_id := _chunk_id_from_node_id(str(node_id))) is not None
            }

    vector_store = _load_local_store(normalized_course_id)
    return {
        chunk_id
        for node_id in vector_store.list_node_ids(normalized_ids)
        if (chunk_id := _chunk_id_from_node_id(node_id)) is not None
    }


def query_course_index(
    course_id: str,
    query_embedding: list[float],
    *,
    top_k: int = 5,
) -> list[CourseIndexHit]:
    """Query the active vector store with a precomputed embedding."""

    normalized_course_id = course_id.strip()
    if not normalized_course_id or not query_embedding or top_k <= 0:
        return []
    if not course_index_exists(normalized_course_id):
        return []

    if is_cloud_mode():
        binding = _course_binding_snapshot(normalized_course_id)
        if (
            binding is not None
            and binding.embedding_dim is not None
            and int(binding.embedding_dim) != len(query_embedding)
        ):
            logger.warning(
                "llamaindex_query_embedding_dimension_mismatch",
                course_id=normalized_course_id,
                expected_dim=int(binding.embedding_dim),
                actual_dim=len(query_embedding),
            )
            return []

    vector_store = _load_store(
        normalized_course_id,
        embedding_dim=len(query_embedding),
    )
    query = VectorStoreQuery(
        query_embedding=query_embedding,
        similarity_top_k=top_k,
        filters=_course_filter(normalized_course_id),
    )
    result = vector_store.query(query)

    hits: list[CourseIndexHit] = []
    ids = list(result.ids or [])
    scores = list(result.similarities or [])
    for index, node_id in enumerate(ids):
        chunk_id = _chunk_id_from_node_id(node_id)
        if chunk_id is None:
            continue
        score = float(scores[index]) if index < len(scores) and scores[index] is not None else 0.0
        hits.append(CourseIndexHit(chunk_id=chunk_id, score=score))
    return hits


async def retrieve_course_chunks(
    course_id: str,
    query: str,
    *,
    top_k: int = 5,
    query_embedding: list[float] | None = None,
) -> list[CourseIndexHit]:
    """Embed a query and retrieve matching chunk IDs from LlamaIndex."""

    normalized_query = query.strip()
    if not normalized_query or top_k <= 0:
        return []

    embedding = query_embedding
    if embedding is None:
        from app.shared.infra.embedding import aembed_texts

        binding = _course_binding_snapshot(course_id)
        model_name = binding.embedding_model if binding is not None else None
        vectors = await aembed_texts(
            [normalized_query],
            soft_fail=True,
            model=model_name,
        )
        embedding = vectors[0] if vectors else []

    if is_cloud_mode():
        return await asyncio.to_thread(
            query_course_index,
            course_id,
            embedding,
            top_k=top_k,
        )
    return query_course_index(course_id, embedding, top_k=top_k)


__all__ = [
    "IndexedChunk",
    "CourseIndexHit",
    "clear_course_index",
    "count_indexed_chunks",
    "delete_chunks",
    "list_indexed_chunk_ids",
    "query_course_index",
    "rebuild_course_index",
    "retrieve_course_chunks",
    "course_index_exists",
    "upsert_chunks",
]
