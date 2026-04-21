"""LlamaIndex-backed subject index management."""

from app.shared.infra.search.llamaindex_index.manager import (
    IndexedChunk,
    SubjectIndexHit,
    clear_subject_index,
    count_indexed_chunks,
    delete_chunks,
    prepare_postgres_store,
    query_subject_index,
    rebuild_subject_index,
    retrieve_subject_chunks,
    subject_index_exists,
    upsert_chunks,
)

__all__ = [
    "IndexedChunk",
    "SubjectIndexHit",
    "clear_subject_index",
    "count_indexed_chunks",
    "delete_chunks",
    "prepare_postgres_store",
    "query_subject_index",
    "rebuild_subject_index",
    "retrieve_subject_chunks",
    "subject_index_exists",
    "upsert_chunks",
]
