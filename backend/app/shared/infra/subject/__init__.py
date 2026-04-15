"""Subject-scoped infra helpers."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

from app.shared.infra.subject.settings import (
    SubjectEmbeddingBinding,
    SubjectEmbeddingMode,
    SubjectSettingsPayload,
    build_disabled_binding,
    build_enabled_binding,
    build_subject_index_ref,
    build_subject_vector_table_name,
    dump_subject_settings,
    get_legacy_vector_table_name,
    get_postgres_vector_ref,
    get_subject_embedding_binding,
    load_subject_settings,
    set_subject_embedding_binding,
)

if TYPE_CHECKING:
    from app.shared.infra.subject.build_precheck import (
        inspect_subject_build_precheck,
        resolve_subject_build_vector_status,
        subject_uses_legacy_vector_storage,
    )
    from app.shared.infra.subject.vectors import (
        RuntimeEmbeddingConfig,
        SUBJECT_VECTOR_PRECHECK_DETAIL_MAP,
        SubjectVectorCapability,
        build_subject_vector_status,
        get_runtime_embedding_config,
        get_subject_record_by_slug,
        get_subject_vector_capability,
        get_subject_vector_search_notice,
        get_subject_vector_status,
        get_subject_vector_status_by_slug,
        should_generate_subject_embeddings,
    )

_VECTOR_EXPORTS = {
    "RuntimeEmbeddingConfig",
    "SUBJECT_VECTOR_PRECHECK_DETAIL_MAP",
    "SubjectVectorCapability",
    "build_subject_vector_status",
    "get_runtime_embedding_config",
    "get_subject_record_by_slug",
    "get_subject_vector_capability",
    "get_subject_vector_search_notice",
    "get_subject_vector_status",
    "get_subject_vector_status_by_slug",
    "should_generate_subject_embeddings",
}
_BUILD_PRECHECK_EXPORTS = {
    "inspect_subject_build_precheck",
    "resolve_subject_build_vector_status",
    "subject_uses_legacy_vector_storage",
}


def __getattr__(name: str) -> Any:
    if name in _BUILD_PRECHECK_EXPORTS:
        module = import_module("app.shared.infra.subject.build_precheck")
        value = getattr(module, name)
        globals()[name] = value
        return value
    if name not in _VECTOR_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module("app.shared.infra.subject.vectors")
    value = getattr(module, name)
    globals()[name] = value
    return value


__all__ = [
    "RuntimeEmbeddingConfig",
    "SUBJECT_VECTOR_PRECHECK_DETAIL_MAP",
    "SubjectEmbeddingBinding",
    "SubjectEmbeddingMode",
    "SubjectSettingsPayload",
    "SubjectVectorCapability",
    "build_disabled_binding",
    "build_enabled_binding",
    "build_subject_index_ref",
    "build_subject_vector_status",
    "build_subject_vector_table_name",
    "dump_subject_settings",
    "get_legacy_vector_table_name",
    "get_postgres_vector_ref",
    "get_runtime_embedding_config",
    "get_subject_embedding_binding",
    "get_subject_record_by_slug",
    "get_subject_vector_capability",
    "get_subject_vector_search_notice",
    "get_subject_vector_status",
    "get_subject_vector_status_by_slug",
    "inspect_subject_build_precheck",
    "load_subject_settings",
    "resolve_subject_build_vector_status",
    "set_subject_embedding_binding",
    "should_generate_subject_embeddings",
    "subject_uses_legacy_vector_storage",
]
