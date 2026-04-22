"""Subject-scoped embedding build precheck and resolution helpers."""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.models.subject import Subject
from app.repositories.subject_repo import save_subject
from app.schemas.knowledge import (
    KnowledgeBuildPrecheckConflictData,
    SubjectVectorStatusResponse,
)
from app.shared.infra.database import (
    get_vector_table_dim,
    vector_table_exists,
)
from app.shared.infra.exceptions import KnowledgeBuildPrecheckConflictError
from app.shared.infra.subject.settings import (
    build_subject_index_ref_for_subject,
    SubjectEmbeddingBinding,
    SubjectEmbeddingMode,
    build_disabled_binding,
    build_enabled_binding,
    get_subject_embedding_binding,
    set_subject_embedding_binding,
)
from app.shared.infra.subject.vectors import (
    SUBJECT_VECTOR_PRECHECK_DETAIL_MAP,
    RuntimeEmbeddingConfig,
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

logger = structlog.get_logger()

_USER_DISABLED_REASON = "user_selected_disable_after_precheck"
_PRECHECK_DETAIL_MAP = SUBJECT_VECTOR_PRECHECK_DETAIL_MAP
_RUNTIME_UNAVAILABLE_REASONS = {
    "embedding_not_configured",
    "embedding_api_key_missing",
    "llamaindex_unavailable",
    "vector_extension_unavailable",
    "llamaindex_postgres_unavailable",
}
def _build_precheck_conflict(
    *,
    reason: str,
    binding: SubjectEmbeddingBinding | None,
    runtime: RuntimeEmbeddingConfig,
    requires_full_rebuild: bool,
) -> KnowledgeBuildPrecheckConflictData:
    return KnowledgeBuildPrecheckConflictData(
        reason=reason,
        subject_model=binding.embedding_model if binding is not None else None,
        subject_dim=binding.embedding_dim if binding is not None else None,
        runtime_model=runtime.embedding_model,
        runtime_dim=runtime.embedding_dim,
        requires_full_rebuild=requires_full_rebuild,
        vector_enabled_after_continue=False,
    )


def inspect_subject_build_precheck(
    session: Session,
    *,
    subject: Subject,
) -> KnowledgeBuildPrecheckConflictData | None:
    """Inspect whether the next knowledge build needs an embedding decision."""

    binding = get_subject_embedding_binding(subject)
    runtime = get_runtime_embedding_config()
    if binding is not None and binding.mode == SubjectEmbeddingMode.DISABLED:
        return None

    if not runtime.configured:
        return _build_precheck_conflict(
            reason="embedding_not_configured",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=False,
        )
    if not runtime.available:
        return _build_precheck_conflict(
            reason=runtime.reason or "vector_extension_unavailable",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=False,
        )
    if binding is None:
        return _build_precheck_conflict(
            reason="subject_not_bound",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )
    expected_ref = build_subject_index_ref_for_subject(subject)
    if not binding.vector_table or binding.vector_table != expected_ref:
        return _build_precheck_conflict(
            reason="vector_table_missing",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )
    if binding.embedding_model != runtime.embedding_model:
        return _build_precheck_conflict(
            reason="embedding_model_mismatch",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )
    if runtime.dimension_explicit and binding.embedding_dim != runtime.embedding_dim:
        return _build_precheck_conflict(
            reason="embedding_dimension_mismatch",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )

    connection = session.connection()
    if not vector_table_exists(connection, expected_ref):
        return _build_precheck_conflict(
            reason="vector_table_missing",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )

    table_dim = get_vector_table_dim(connection, expected_ref)
    if (
        table_dim is not None
        and binding.embedding_dim is not None
        and table_dim != binding.embedding_dim
    ):
        return _build_precheck_conflict(
            reason="vector_table_dimension_mismatch",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )

    return None


def _raise_precheck_conflict(conflict: KnowledgeBuildPrecheckConflictData) -> None:
    detail = _PRECHECK_DETAIL_MAP.get(
        conflict.reason,
        "当前学科向量配置需要先确认处理方式。",
    )
    raise KnowledgeBuildPrecheckConflictError(
        detail,
        data=conflict.model_dump(mode="json"),
    )


def resolve_subject_build_vector_status(
    session: Session,
    *,
    subject: Subject,
    embedding_resolution: str | None,
) -> SubjectVectorStatusResponse:
    """Apply one optional resolution and return the resulting vector status."""

    auto_rebuild_reason: str | None = None
    conflict = inspect_subject_build_precheck(session, subject=subject)
    if conflict is None:
        return get_subject_vector_status(session, subject)

    auto_rebuild_reasons = {
        "subject_not_bound",
        "embedding_model_mismatch",
        "embedding_dimension_mismatch",
        "vector_table_missing",
        "vector_table_dimension_mismatch",
    }
    if (
        embedding_resolution is None
        and conflict.reason in auto_rebuild_reasons
        and conflict.requires_full_rebuild
    ):
        logger.info(
            "embedding_auto_rebuild",
            subject=subject.slug,
            reason=conflict.reason,
            runtime_model=conflict.runtime_model,
            runtime_dim=conflict.runtime_dim,
            subject_model=conflict.subject_model,
            subject_dim=conflict.subject_dim,
            detail=_PRECHECK_DETAIL_MAP.get(conflict.reason, ""),
        )
        auto_rebuild_reason = conflict.reason
        embedding_resolution = "rebuild"

    if embedding_resolution is None and conflict.reason in _RUNTIME_UNAVAILABLE_REASONS:
        logger.info(
            "embedding_unavailable_build_continues_without_vectors",
            subject=subject.slug,
            reason=conflict.reason,
            runtime_model=conflict.runtime_model,
            runtime_dim=conflict.runtime_dim,
            detail=_PRECHECK_DETAIL_MAP.get(conflict.reason, ""),
        )
        status = get_subject_vector_status(session, subject)
        status.notice = _PRECHECK_DETAIL_MAP.get(conflict.reason, status.notice)
        return status

    if embedding_resolution is None:
        _raise_precheck_conflict(conflict)

    if embedding_resolution == "disable":
        set_subject_embedding_binding(
            subject,
            build_disabled_binding(
                subject_slug=subject.slug,
                owner_user_id=subject.user_id,
                disabled_reason=_USER_DISABLED_REASON,
                previous_binding=get_subject_embedding_binding(subject),
            ),
        )
        save_subject(session, subject)
        return get_subject_vector_status(session, subject)

    if embedding_resolution != "rebuild":
        _raise_precheck_conflict(conflict)

    runtime = get_runtime_embedding_config()
    if (
        not runtime.available
        or runtime.embedding_model is None
        or runtime.embedding_dim is None
    ):
        _raise_precheck_conflict(conflict)

    set_subject_embedding_binding(
        subject,
        build_enabled_binding(
            subject_slug=subject.slug,
            owner_user_id=subject.user_id,
            embedding_model=runtime.embedding_model,
            embedding_dim=runtime.embedding_dim,
        ),
    )
    save_subject(session, subject)
    from app.shared.infra.search.llamaindex_index import clear_subject_index

    clear_subject_index(subject.slug)
    status = get_subject_vector_status(session, subject)

    if auto_rebuild_reason is not None:
        auto_rebuild_notices = {
            "subject_not_bound": "已自动绑定当前 embedding 模型并初始化向量索引。",
            "embedding_model_mismatch": f"检测到 embedding 模型变更，已自动切换到 {runtime.embedding_model} 并重建向量索引。",
            "embedding_dimension_mismatch": "检测到 embedding 维度变更，已自动重建向量索引。",
            "vector_table_missing": "向量表缺失，已自动重建。",
            "vector_table_dimension_mismatch": "向量表维度不一致，已自动重建。",        }
        status.notice = auto_rebuild_notices.get(auto_rebuild_reason)

    return status


__all__ = [
    "RuntimeEmbeddingConfig",
    "SubjectVectorCapability",
    "build_subject_vector_status",
    "get_runtime_embedding_config",
    "get_subject_record_by_slug",
    "get_subject_vector_capability",
    "get_subject_vector_search_notice",
    "get_subject_vector_status",
    "get_subject_vector_status_by_slug",
    "inspect_subject_build_precheck",
    "resolve_subject_build_vector_status",
    "should_generate_subject_embeddings",
]
