"""LlamaIndex-backed course index management."""

from app.shared.infra.search.llamaindex_index.manager import (
    IndexedChunk,
    CourseIndexHit,
    clear_course_index,
    count_indexed_chunks,
    delete_chunks,
    list_indexed_chunk_ids,
    prepare_postgres_store,
    query_course_index,
    rebuild_course_index,
    retrieve_course_chunks,
    course_index_exists,
    upsert_chunks,
)
from app.shared.infra.search.llamaindex_index.ingestion import (
    DEFAULT_INGESTION_CHUNK_OVERLAP,
    DEFAULT_INGESTION_CHUNK_SIZE,
    aembed_texts_for_ingestion,
    build_text_splitter,
    split_text_for_ingestion,
)

__all__ = [
    "DEFAULT_INGESTION_CHUNK_OVERLAP",
    "DEFAULT_INGESTION_CHUNK_SIZE",
    "IndexedChunk",
    "CourseIndexHit",
    "aembed_texts_for_ingestion",
    "build_text_splitter",
    "clear_course_index",
    "count_indexed_chunks",
    "delete_chunks",
    "list_indexed_chunk_ids",
    "prepare_postgres_store",
    "query_course_index",
    "rebuild_course_index",
    "retrieve_course_chunks",
    "course_index_exists",
    "split_text_for_ingestion",
    "upsert_chunks",
]
