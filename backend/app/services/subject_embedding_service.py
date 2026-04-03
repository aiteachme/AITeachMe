"""Subject-scoped embedding binding and vector-status helpers."""

from __future__ import annotations

from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.config import get_settings
from app.core.database import (
    get_engine,
    get_vector_table_dim,
    is_vec_ready,
    reset_subject_vec_table,
    vector_table_exists,
)
from app.core.exceptions import KnowledgeBuildPrecheckConflictError
from app.core.subject_embeddings import (
    SubjectEmbeddingBinding,
    SubjectEmbeddingMode,
    build_disabled_binding,
    build_enabled_binding,
    get_legacy_vector_table_name,
    get_subject_embedding_binding,
    set_subject_embedding_binding,
)
from app.models.knowledge import RetrievalChunk
from app.models.subject import Subject
from app.repositories.subject_repo import save_subject
from app.schemas.knowledge import (
    KnowledgeBuildPrecheckConflictData,
    SubjectVectorStatusResponse,
)

_USER_DISABLED_REASON = "user_selected_disable_after_precheck"
_DISABLED_SEARCH_NOTICE = "当前学科未启用向量检索。"

_PRECHECK_DETAIL_MAP = {
    "embedding_not_configured": "当前后端未配置 embedding 模型，请选择关闭当前学科的向量能力，或先补全配置后再全量重建。",
    "embedding_api_key_missing": "当前后端缺少 embedding 所需的 API Key，请选择关闭当前学科的向量能力，或补全配置后再重建。",
    "vector_extension_unavailable": "当前运行环境不可用 sqlite-vec，请先关闭当前学科的向量能力，或修复环境后再重建。",
    "subject_not_bound": "当前学科尚未绑定 embedding 模型，请先确认是全量重建当前学科向量，还是继续以非向量模式构建。",
    "legacy_vector_table": "当前学科仍在使用旧的全局向量表，请先全量重建当前学科向量，或继续以非向量模式构建。",
    "embedding_model_mismatch": "当前运行时 embedding 模型与学科已绑定模型不一致，请全量重建当前学科向量，或继续以非向量模式构建。",
    "embedding_dimension_mismatch": "当前运行时 embedding 维度与学科已绑定维度不一致，请全量重建当前学科向量，或继续以非向量模式构建。",
    "vector_table_missing": "当前学科缺少可用的向量表，请全量重建当前学科向量，或继续以非向量模式构建。",
    "vector_table_dimension_mismatch": "当前学科向量表维度与学科绑定配置不一致，请全量重建当前学科向量，或继续以非向量模式构建。",
}


class RuntimeEmbeddingConfig(BaseModel):
    """Current runtime embedding capability snapshot."""

    configured: bool = False
    available: bool = False
    embedding_model: str | None = None
    embedding_dim: int | None = None
    reason: str | None = None


class SubjectVectorCapability(BaseModel):
    """Computed subject-level vector capability state."""

    binding: SubjectEmbeddingBinding | None = None
    status: SubjectVectorStatusResponse
    queryable: bool = False


def get_runtime_embedding_config() -> RuntimeEmbeddingConfig:
    """Return the runtime embedding configuration used by the backend."""

    settings = get_settings()
    model = settings.normalized_embedding_model
    embedding_dim = settings.embedding_dim or None

    if model is None:
        return RuntimeEmbeddingConfig(reason="embedding_not_configured")
    if not settings.llm_api_key:
        return RuntimeEmbeddingConfig(
            configured=True,
            embedding_model=model,
            embedding_dim=embedding_dim,
            reason="embedding_api_key_missing",
        )
    if not is_vec_ready():
        return RuntimeEmbeddingConfig(
            configured=True,
            embedding_model=model,
            embedding_dim=embedding_dim,
            reason="vector_extension_unavailable",
        )

    return RuntimeEmbeddingConfig(
        configured=True,
        available=True,
        embedding_model=model,
        embedding_dim=embedding_dim,
    )


def get_subject_record_by_slug(session: Session, subject_slug: str) -> Subject | None:
    """Return one subject record by slug."""

    return session.exec(select(Subject).where(Subject.slug == subject_slug)).first()


def build_subject_vector_status(
    binding: SubjectEmbeddingBinding | None,
    *,
    runtime: RuntimeEmbeddingConfig | None = None,
) -> SubjectVectorStatusResponse:
    """Build one user-facing vector status payload."""

    current_runtime = runtime or get_runtime_embedding_config()

    if binding is None:
        if current_runtime.reason in _PRECHECK_DETAIL_MAP:
            return SubjectVectorStatusResponse(
                mode=SubjectEmbeddingMode.ENABLED.value,
                notice=_PRECHECK_DETAIL_MAP[current_runtime.reason],
            )
        if current_runtime.available:
            return SubjectVectorStatusResponse(
                mode=SubjectEmbeddingMode.ENABLED.value,
                notice=(
                    "当前学科尚未绑定 embedding 模型；下次知识构建会先确认是否全量重建当前学科向量。"
                ),
            )
        return SubjectVectorStatusResponse(mode=SubjectEmbeddingMode.ENABLED.value)

    notice: str | None = None
    if binding.mode == SubjectEmbeddingMode.DISABLED:
        notice = (
            "当前学科已切换为非向量模式。知识文档、图谱和课程结构仍可继续构建，"
            "但向量检索与依赖向量的能力已暂停；重新选择“全量重建向量”后可恢复。"
        )
    elif not current_runtime.available and current_runtime.reason in _PRECHECK_DETAIL_MAP:
        notice = _PRECHECK_DETAIL_MAP[current_runtime.reason]
    elif current_runtime.embedding_model != binding.embedding_model:
        notice = _PRECHECK_DETAIL_MAP["embedding_model_mismatch"]
    elif current_runtime.embedding_dim != binding.embedding_dim:
        notice = _PRECHECK_DETAIL_MAP["embedding_dimension_mismatch"]

    return SubjectVectorStatusResponse(
        mode=binding.mode.value,
        notice=notice,
        embedding_model=binding.embedding_model,
        vector_table=binding.vector_table,
    )


def _build_table_conflict_status(
    binding: SubjectEmbeddingBinding,
    *,
    reason: str,
) -> SubjectVectorStatusResponse:
    return SubjectVectorStatusResponse(
        mode=binding.mode.value,
        notice=_PRECHECK_DETAIL_MAP[reason],
        embedding_model=binding.embedding_model,
        vector_table=binding.vector_table,
    )


def get_subject_vector_capability(
    session: Session,
    subject: Subject,
) -> SubjectVectorCapability:
    """Return the subject vector status plus whether vector search can run now."""

    binding = get_subject_embedding_binding(subject)
    runtime = get_runtime_embedding_config()
    status = build_subject_vector_status(binding, runtime=runtime)

    if binding is None or binding.mode == SubjectEmbeddingMode.DISABLED:
        return SubjectVectorCapability(binding=binding, status=status, queryable=False)
    if not runtime.available:
        return SubjectVectorCapability(binding=binding, status=status, queryable=False)
    if binding.embedding_model != runtime.embedding_model:
        return SubjectVectorCapability(binding=binding, status=status, queryable=False)
    if binding.embedding_dim != runtime.embedding_dim:
        return SubjectVectorCapability(binding=binding, status=status, queryable=False)
    if not binding.vector_table:
        return SubjectVectorCapability(binding=binding, status=status, queryable=False)

    connection = session.connection()
    if not vector_table_exists(connection, binding.vector_table):
        return SubjectVectorCapability(
            binding=binding,
            status=_build_table_conflict_status(binding, reason="vector_table_missing"),
            queryable=False,
        )

    table_dim = get_vector_table_dim(connection, binding.vector_table)
    if (
        table_dim is not None
        and binding.embedding_dim is not None
        and table_dim != binding.embedding_dim
    ):
        return SubjectVectorCapability(
            binding=binding,
            status=_build_table_conflict_status(
                binding,
                reason="vector_table_dimension_mismatch",
            ),
            queryable=False,
        )

    return SubjectVectorCapability(binding=binding, status=status, queryable=True)


def get_subject_vector_status(
    session: Session,
    subject: Subject,
) -> SubjectVectorStatusResponse:
    """Return only the public subject vector status payload."""

    return get_subject_vector_capability(session, subject).status


def get_subject_vector_status_by_slug(
    session: Session,
    subject_slug: str,
) -> SubjectVectorStatusResponse:
    """Return the vector status for one subject slug."""

    subject = get_subject_record_by_slug(session, subject_slug)
    if subject is None:
        return SubjectVectorStatusResponse()
    return get_subject_vector_status(session, subject)


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

    conflict = inspect_subject_build_precheck(session, subject=subject)
    if conflict is None:
        return get_subject_vector_status(session, subject)
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
    return get_subject_vector_status(session, subject)


def should_generate_subject_embeddings(
    session: Session,
    *,
    subject_slug: str,
) -> bool:
    """Return whether the current build should generate embeddings."""

    subject = get_subject_record_by_slug(session, subject_slug)
    if subject is None:
        return False

    capability = get_subject_vector_capability(session, subject)
    return capability.queryable


def get_subject_vector_search_notice(
    session: Session,
    *,
    subject_slug: str,
) -> str | None:
    """Return one stable search notice when vector retrieval is unavailable."""

    subject = get_subject_record_by_slug(session, subject_slug)
    if subject is None:
        return None

    capability = get_subject_vector_capability(session, subject)
    if capability.queryable:
        return None
    if (
        capability.binding is not None
        and capability.binding.mode == SubjectEmbeddingMode.DISABLED
    ):
        return _DISABLED_SEARCH_NOTICE
    if capability.status.notice:
        return capability.status.notice
    return "当前学科向量检索暂不可用。"


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
