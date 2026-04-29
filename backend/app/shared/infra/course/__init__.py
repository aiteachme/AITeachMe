"""Course-scoped infra helpers."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from app.shared.infra.course.settings import (
    CourseEmbeddingBinding,
    CourseEmbeddingMode,
    CourseSettingsPayload,
    build_disabled_binding,
    build_enabled_binding,
    build_postgres_course_index_data_table_name,
    build_postgres_course_index_name,
    build_course_index_ref,
    build_course_index_ref_for_course,
    dump_course_settings,
    extract_postgres_course_index_data_table_name,
    extract_postgres_course_index_name,
    get_course_embedding_binding,
    load_course_settings,
    set_course_embedding_binding,
)

if TYPE_CHECKING:
    from app.shared.infra.course.build_precheck import (
        inspect_course_build_precheck,
        resolve_course_build_vector_status,
    )
    from app.shared.infra.course.vectors import (
        RuntimeEmbeddingConfig,
        COURSE_VECTOR_PRECHECK_DETAIL_MAP,
        CourseVectorCapability,
        build_course_vector_status,
        get_runtime_embedding_config,
        get_course_record_by_id,
        get_course_vector_capability,
        get_course_vector_search_notice,
        get_course_vector_status,
        get_course_vector_status_by_id,
        should_generate_course_embeddings,
        course_has_retrieval_chunks,
    )

_VECTOR_EXPORTS = {
    "RuntimeEmbeddingConfig",
    "COURSE_VECTOR_PRECHECK_DETAIL_MAP",
    "CourseVectorCapability",
    "build_course_vector_status",
    "get_runtime_embedding_config",
    "get_course_record_by_id",
    "get_course_vector_capability",
    "get_course_vector_search_notice",
    "get_course_vector_status",
    "get_course_vector_status_by_id",
    "should_generate_course_embeddings",
    "course_has_retrieval_chunks",
}
_BUILD_PRECHECK_EXPORTS = {
    "inspect_course_build_precheck",
    "resolve_course_build_vector_status",
}


def __getattr__(name: str) -> Any:
    if name in _BUILD_PRECHECK_EXPORTS:
        module = import_module("app.shared.infra.course.build_precheck")
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name not in _VECTOR_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module("app.shared.infra.course.vectors")
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "RuntimeEmbeddingConfig",
    "COURSE_VECTOR_PRECHECK_DETAIL_MAP",
    "CourseEmbeddingBinding",
    "CourseEmbeddingMode",
    "CourseSettingsPayload",
    "CourseVectorCapability",
    "build_disabled_binding",
    "build_enabled_binding",
    "build_postgres_course_index_data_table_name",
    "build_postgres_course_index_name",
    "build_course_index_ref",
    "build_course_index_ref_for_course",
    "build_course_vector_status",
    "dump_course_settings",
    "extract_postgres_course_index_data_table_name",
    "extract_postgres_course_index_name",
    "get_runtime_embedding_config",
    "get_course_embedding_binding",
    "get_course_record_by_id",
    "get_course_vector_capability",
    "get_course_vector_search_notice",
    "get_course_vector_status",
    "get_course_vector_status_by_id",
    "inspect_course_build_precheck",
    "load_course_settings",
    "resolve_course_build_vector_status",
    "set_course_embedding_binding",
    "should_generate_course_embeddings",
    "course_has_retrieval_chunks",
]
