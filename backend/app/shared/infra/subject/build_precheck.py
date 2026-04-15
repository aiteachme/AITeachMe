"""Subject-scoped embedding build precheck and resolution helpers."""

from __future__ import annotations

import structlog
from sqlmodel import Session, select

from app.models.knowledge import RetrievalChunk
from app.models.subject import Subject
from app.repositories.subject_repo import save_subject
from app.schemas.knowledge import (
    KnowledgeBuildPrecheckConflictData,
    SubjectVectorStatusResponse,
)
from app.shared.infra.database import (
    get_engine,
    get_vector_table_dim,
    reset_subject_vec_table,
    vector_table_exists,
)
from app.shared.infra.exceptions import KnowledgeBuildPrecheckConflictError
from app.shared.infra.subject.settings import (
    SubjectEmbeddingBinding,
    SubjectEmbeddingMode,
    build_disabled_binding,
    build_enabled_binding,
    get_legacy_vector_table_name,
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


def _count_rows_for_chunk_ids(
    session: Session,
    *,
    table_name: str,
    chunk_ids: list[int],
) -> int:
    if not chunk_ids:
        return 0

    connection = session.connection()
    if not vector_table_exists(connection, table_name):
        return 0

    placeholders = ", ".join(
        f":chunk_id_{index}" for index in range(len(chunk_ids))
    )
    params = {
        f"chunk_id_{index}": chunk_id for index, chunk_id in enumerate(chunk_ids)
    }
    row = connection.exec_driver_sql(
        f'SELECT COUNT(*) FROM "{table_name}" WHERE chunk_id IN ({placeholders})',
        params,
    ).first()
    return int(row[0]) if row is not None else 0


def subject_uses_legacy_vector_storage(session: Session, subject_slug: str) -> bool:
    """Check whether the subject still relies on the legacy global vector table."""

    chunks = list(
        session.exec(
            select(RetrievalChunk).where(RetrievalChunk.subject == subject_slug)
        ).all()
    )
    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    if not chunk_ids:
        return False

    legacy_table = get_legacy_vector_table_name()
    connection = session.connection()
    if not vector_table_exists(connection, legacy_table):
        return False

    if any((chunk.vector_ref or legacy_table) == legacy_table for chunk in chunks):
        return True

    return _count_rows_for_chunk_ids(
        session,
        table_name=legacy_table,
        chunk_ids=chunk_ids,
    ) > 0


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

    legacy_in_use = subject_uses_legacy_vector_storage(session, subject.slug)

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
            reason="legacy_vector_table" if legacy_in_use else "subject_not_bound",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )
    if legacy_in_use:
        return _build_precheck_conflict(
            reason="legacy_vector_table",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )
    if not binding.vector_table:
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
    if binding.embedding_dim != runtime.embedding_dim:
        return _build_precheck_conflict(
            reason="embedding_dimension_mismatch",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )

    connection = session.connection()
    if not vector_table_exists(connection, binding.vector_table):
        return _build_precheck_conflict(
            reason="vector_table_missing",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )

    table_dim = get_vector_table_dim(connection, binding.vector_table)
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
        "legacy_vector_table",
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

    if embedding_resolution is None:
        _raise_precheck_conflict(conflict)

    if embedding_resolution == "disable":
        set_subject_embedding_binding(
            subject,
            build_disabled_binding(
                subject_slug=subject.slug,
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
            embedding_model=runtime.embedding_model,
            embedding_dim=runtime.embedding_dim,
        ),
    )
    save_subject(session, subject)
    reset_subject_vec_table(
        get_engine(),
        subject=subject.slug,
        embedding_dim=runtime.embedding_dim,
    )
    status = get_subject_vector_status(session, subject)

    if auto_rebuild_reason is not None:
        auto_rebuild_notices = {
            "subject_not_bound": "已自动绑定当前 embedding 模型并初始化向量索引。",
            "embedding_model_mismatch": f"检测到 embedding 模型变更，已自动切换到 {runtime.embedding_model} 并重建向量索引。",
            "embedding_dimension_mismatch": "检测到 embedding 维度变更，已自动重建向量索引。",
            "vector_table_missing": "向量表缺失，已自动重建。",
            "vector_table_dimension_mismatch": "向量表维度不一致，已自动重建。",
            "legacy_vector_table": "已从旧版全局向量表迁移到学科独立向量表。",
        }
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
    "subject_uses_legacy_vector_storage",
]
