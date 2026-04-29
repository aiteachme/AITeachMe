"""LlamaIndex-backed course index management."""

from app.shared.infra.search.llamaindex_index.manager import (
    IndexedChunk,
    CourseIndexHit,
    clear_course_index,
    count_indexed_chunks,
    delete_chunks,
    prepare_postgres_store,
    query_course_index,
    rebuild_course_index,
    retrieve_course_chunks,
    course_index_exists,
    upsert_chunks,
)

__all__ = [
    "IndexedChunk",
    "CourseIndexHit",
    "clear_course_index",
    "count_indexed_chunks",
    "delete_chunks",
    "prepare_postgres_store",
    "query_course_index",
    "rebuild_course_index",
    "retrieve_course_chunks",
    "course_index_exists",
    "upsert_chunks",
]
