"""Course-scoped embedding build precheck and resolution helpers."""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.models.course import Course
from app.repositories.course_repo import save_course
from app.schemas.knowledge import (
    KnowledgeBuildPrecheckConflictData,
    CourseVectorStatusResponse,
)
from app.shared.infra.database import get_vector_table_dim, vector_table_exists
from app.shared.infra.runtime import is_cloud_mode
from app.shared.infra.exceptions import KnowledgeBuildPrecheckConflictError
from app.shared.infra.course.settings import (
    build_course_index_ref_for_course,
    CourseEmbeddingBinding,
    CourseEmbeddingMode,
    build_disabled_binding,
    build_enabled_binding,
    get_course_embedding_binding,
    set_course_embedding_binding,
)
from app.shared.infra.course.vectors import (
    COURSE_VECTOR_PRECHECK_DETAIL_MAP,
    RuntimeEmbeddingConfig,
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

logger = structlog.get_logger()

_USER_DISABLED_REASON = "user_selected_disable_after_precheck"
_PRECHECK_DETAIL_MAP = COURSE_VECTOR_PRECHECK_DETAIL_MAP
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
    binding: CourseEmbeddingBinding | None,
    runtime: RuntimeEmbeddingConfig,
    requires_full_rebuild: bool,
) -> KnowledgeBuildPrecheckConflictData:
    return KnowledgeBuildPrecheckConflictData(
        reason=reason,
        course_model=binding.embedding_model if binding is not None else None,
        course_dim=binding.embedding_dim if binding is not None else None,
        runtime_model=runtime.embedding_model,
        runtime_dim=runtime.embedding_dim,
        requires_full_rebuild=requires_full_rebuild,
        vector_enabled_after_continue=False,
    )


def inspect_course_build_precheck(
    session: Session,
    *,
    course: Course,
) -> KnowledgeBuildPrecheckConflictData | None:
    """Inspect whether the next knowledge build needs an embedding decision."""

    binding = get_course_embedding_binding(course)
    runtime = get_runtime_embedding_config()
    if binding is not None and binding.mode == CourseEmbeddingMode.DISABLED:
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
            reason="course_not_bound",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )
    expected_ref = build_course_index_ref_for_course(course)
    if not binding.vector_table or binding.vector_table != expected_ref:
        if not course_has_retrieval_chunks(session, course.id):
            return None
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

    if is_cloud_mode():
        connection = session.connection()
        index_exists = vector_table_exists(connection, expected_ref)
    else:
        from app.shared.infra.search.llamaindex_index import course_index_exists

        connection = None
        index_exists = course_index_exists(course.id)

    if not index_exists:
        if not course_has_retrieval_chunks(session, course.id):
            return None
        return _build_precheck_conflict(
            reason="vector_table_missing",
            binding=binding,
            runtime=runtime,
            requires_full_rebuild=True,
        )

    if connection is not None:
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
        "当前课程向量配置需要先确认处理方式。",
    )
    raise KnowledgeBuildPrecheckConflictError(
        detail,
        data=conflict.model_dump(mode="json"),
    )


def resolve_course_build_vector_status(
    session: Session,
    *,
    course: Course,
    embedding_resolution: str | None,
) -> CourseVectorStatusResponse:
    """Apply one optional resolution and return the resulting vector status."""

    auto_rebuild_reason: str | None = None
    conflict = inspect_course_build_precheck(session, course=course)
    if conflict is None:
        return get_course_vector_status(session, course)

    auto_rebuild_reasons = {
        "course_not_bound",
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
            course=course.id,
            reason=conflict.reason,
            runtime_model=conflict.runtime_model,
            runtime_dim=conflict.runtime_dim,
            course_model=conflict.course_model,
            course_dim=conflict.course_dim,
            detail=_PRECHECK_DETAIL_MAP.get(conflict.reason, ""),
        )
        auto_rebuild_reason = conflict.reason
        embedding_resolution = "rebuild"

    if embedding_resolution is None and conflict.reason in _RUNTIME_UNAVAILABLE_REASONS:
        logger.info(
            "embedding_unavailable_build_continues_without_vectors",
            course=course.id,
            reason=conflict.reason,
            runtime_model=conflict.runtime_model,
            runtime_dim=conflict.runtime_dim,
            detail=_PRECHECK_DETAIL_MAP.get(conflict.reason, ""),
        )
        status = get_course_vector_status(session, course)
        status.notice = _PRECHECK_DETAIL_MAP.get(conflict.reason, status.notice)
        return status

    if embedding_resolution is None:
        _raise_precheck_conflict(conflict)

    if embedding_resolution == "disable":
        set_course_embedding_binding(
            course,
            build_disabled_binding(
                course_id=course.id,
                owner_user_id=course.user_id,
                disabled_reason=_USER_DISABLED_REASON,
                previous_binding=get_course_embedding_binding(course),
            ),
        )
        save_course(session, course)
        return get_course_vector_status(session, course)

    if embedding_resolution != "rebuild":
        _raise_precheck_conflict(conflict)

    runtime = get_runtime_embedding_config()
    if (
        not runtime.available
        or runtime.embedding_model is None
        or runtime.embedding_dim is None
    ):
        _raise_precheck_conflict(conflict)

    set_course_embedding_binding(
        course,
        build_enabled_binding(
            course_id=course.id,
            owner_user_id=course.user_id,
            embedding_model=runtime.embedding_model,
            embedding_dim=runtime.embedding_dim,
        ),
    )
    save_course(session, course)
    from app.shared.infra.search.llamaindex_index import clear_course_index

    clear_course_index(course.id)
    status = get_course_vector_status(session, course)

    if auto_rebuild_reason is not None:
        auto_rebuild_notices = {
            "course_not_bound": "已自动绑定当前 embedding 模型并初始化向量索引。",
            "embedding_model_mismatch": f"检测到 embedding 模型变更，已自动切换到 {runtime.embedding_model} 并重建向量索引。",
            "embedding_dimension_mismatch": "检测到 embedding 维度变更，已自动重建向量索引。",
            "vector_table_missing": "向量索引缺失，已自动重建。",
            "vector_table_dimension_mismatch": "向量索引维度不一致，已自动重建。",
        }
        status.notice = auto_rebuild_notices.get(auto_rebuild_reason)

    return status


__all__ = [
    "RuntimeEmbeddingConfig",
    "CourseVectorCapability",
    "build_course_vector_status",
    "get_runtime_embedding_config",
    "get_course_record_by_id",
    "get_course_vector_capability",
    "get_course_vector_search_notice",
    "get_course_vector_status",
    "get_course_vector_status_by_id",
    "inspect_course_build_precheck",
    "resolve_course_build_vector_status",
    "should_generate_course_embeddings",
    "course_has_retrieval_chunks",
]
