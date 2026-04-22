"""Read-only subject vector capability helpers shared by infra-facing callers."""

from __future__ import annotations

import importlib.util

from pydantic import BaseModel
from sqlmodel import Session, select

from app.models.subject import Subject
from app.schemas.knowledge import SubjectVectorStatusResponse
from app.shared.infra.env_support import get_env
from app.shared.infra.runtime import is_cloud_mode
from app.shared.infra.settings import get_settings
from app.shared.infra.subject.settings import (
    SubjectEmbeddingBinding,
    SubjectEmbeddingMode,
    get_subject_embedding_binding,
)

SUBJECT_VECTOR_PRECHECK_DETAIL_MAP: dict[str, str] = {
    "embedding_not_configured": "当前后端未配置 embedding 模型，本轮会跳过 embedding 写入、向量检索和 RAG，知识文档与图谱仍会继续构建。",
    "embedding_api_key_missing": "当前后端缺少 embedding 所需的 API Key，本轮会跳过 embedding 写入、向量检索和 RAG，知识文档与图谱仍会继续构建。",
    "vector_extension_unavailable": "当前运行环境不可用向量索引，本轮会跳过 embedding 写入、向量检索和 RAG，知识文档与图谱仍会继续构建。",
    "llamaindex_unavailable": "当前环境缺少 LlamaIndex 依赖，本轮会跳过 embedding 写入、向量检索和 RAG，知识文档与图谱仍会继续构建。",
    "llamaindex_postgres_unavailable": "当前云端环境缺少 LlamaIndex Postgres 索引依赖，本轮会跳过 embedding 写入、向量检索和 RAG，知识文档与图谱仍会继续构建。",
    "subject_not_bound": "当前学科尚未绑定 embedding 模型，请先确认是全量重建当前学科向量，还是继续以非向量模式构建。",
    "embedding_model_mismatch": "当前运行时 embedding 模型与学科已绑定模型不一致，请全量重建当前学科向量，或继续以非向量模式构建。",
    "embedding_dimension_mismatch": "当前运行时 embedding 维度与学科已绑定维度不一致，请全量重建当前学科向量，或继续以非向量模式构建。",
    "vector_table_missing": "当前学科缺少可用的向量表，请全量重建当前学科向量，或继续以非向量模式构建。",
    "vector_table_dimension_mismatch": "当前学科向量表维度与学科绑定配置不一致，请全量重建当前学科向量，或继续以非向量模式构建。",
}

_DISABLED_SEARCH_NOTICE = "当前学科未启用向量检索。"
_VECTOR_UNAVAILABLE_NOTICE = "当前学科向量检索暂不可用。"


class RuntimeEmbeddingConfig(BaseModel):
    """Current runtime embedding capability snapshot."""

    configured: bool = False
    available: bool = False
    embedding_model: str | None = None
    embedding_dim: int | None = None
    dimension_explicit: bool = False
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
    dimension_explicit = settings.embedding_dim_is_explicit

    if model is None:
        return RuntimeEmbeddingConfig(reason="embedding_not_configured")
    if not get_env("LLM_API_KEY"):
        return RuntimeEmbeddingConfig(
            configured=True,
            embedding_model=model,
            embedding_dim=embedding_dim,
            dimension_explicit=dimension_explicit,
            reason="embedding_api_key_missing",
        )

    try:
        llamaindex_core_spec = importlib.util.find_spec("llama_index.core")
    except ModuleNotFoundError:
        llamaindex_core_spec = None
    if llamaindex_core_spec is None:
        return RuntimeEmbeddingConfig(
            configured=True,
            embedding_model=model,
            embedding_dim=embedding_dim,
            dimension_explicit=dimension_explicit,
            reason="llamaindex_unavailable",
        )

    if is_cloud_mode():
        try:
            postgres_store_spec = importlib.util.find_spec("llama_index.vector_stores.postgres")
        except ModuleNotFoundError:
            postgres_store_spec = None
        if postgres_store_spec is None:
            return RuntimeEmbeddingConfig(
                configured=True,
                embedding_model=model,
                embedding_dim=embedding_dim,
                dimension_explicit=dimension_explicit,
                reason="llamaindex_postgres_unavailable",
            )

    if embedding_dim is None or embedding_dim <= 0:
        return RuntimeEmbeddingConfig(
            configured=True,
            embedding_model=model,
            embedding_dim=embedding_dim,
            dimension_explicit=dimension_explicit,
            reason="vector_extension_unavailable",
        )

    return RuntimeEmbeddingConfig(
        configured=True,
        available=True,
        embedding_model=model,
        embedding_dim=embedding_dim,
        dimension_explicit=dimension_explicit,
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
        if current_runtime.reason in SUBJECT_VECTOR_PRECHECK_DETAIL_MAP:
            return SubjectVectorStatusResponse(
                mode=SubjectEmbeddingMode.ENABLED.value,
                notice=SUBJECT_VECTOR_PRECHECK_DETAIL_MAP[current_runtime.reason],
            )
        return SubjectVectorStatusResponse(mode=SubjectEmbeddingMode.ENABLED.value)

    notice: str | None = None
    if binding.mode == SubjectEmbeddingMode.DISABLED:
        notice = (
            "当前学科已切换为非向量模式。知识文档、图谱和课程结构仍可继续构建，"
            "但向量检索与依赖向量的能力已暂停；重新选择“全量重建向量”后可恢复。"
        )
    elif not current_runtime.available and current_runtime.reason in SUBJECT_VECTOR_PRECHECK_DETAIL_MAP:
        notice = SUBJECT_VECTOR_PRECHECK_DETAIL_MAP[current_runtime.reason]
    elif current_runtime.embedding_model != binding.embedding_model:
        notice = SUBJECT_VECTOR_PRECHECK_DETAIL_MAP["embedding_model_mismatch"]
    elif (
        current_runtime.dimension_explicit
        and current_runtime.embedding_dim != binding.embedding_dim
    ):
        notice = SUBJECT_VECTOR_PRECHECK_DETAIL_MAP["embedding_dimension_mismatch"]

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
        notice=SUBJECT_VECTOR_PRECHECK_DETAIL_MAP[reason],
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
    if binding.embedding_dim is None:
        return SubjectVectorCapability(binding=binding, status=status, queryable=False)
    if runtime.dimension_explicit and binding.embedding_dim != runtime.embedding_dim:
        return SubjectVectorCapability(binding=binding, status=status, queryable=False)
    if not binding.vector_table:
        return SubjectVectorCapability(binding=binding, status=status, queryable=False)

    should_check_backing_store = is_cloud_mode() or not binding.vector_table.startswith("llamaindex://")
    if should_check_backing_store:
        from app.shared.infra.database import get_vector_table_dim, vector_table_exists

        connection = session.connection()
        if not vector_table_exists(connection, binding.vector_table):
            return SubjectVectorCapability(
                binding=binding,
                status=_build_table_conflict_status(binding, reason="vector_table_missing"),
                queryable=False,
            )
        table_dim = get_vector_table_dim(connection, binding.vector_table)
        if table_dim is not None and table_dim != binding.embedding_dim:
            return SubjectVectorCapability(
                binding=binding,
                status=_build_table_conflict_status(binding, reason="vector_table_dimension_mismatch"),
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
    if capability.binding is not None and capability.binding.mode == SubjectEmbeddingMode.DISABLED:
        return _DISABLED_SEARCH_NOTICE
    if capability.status.notice:
        return capability.status.notice
    return _VECTOR_UNAVAILABLE_NOTICE


__all__ = [
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
]
