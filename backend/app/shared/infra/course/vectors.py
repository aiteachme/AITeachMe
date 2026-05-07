"""Read-only course vector capability helpers shared by infra-facing callers."""

from __future__ import annotations

import importlib.util
import sqlite3

from pydantic import BaseModel
from sqlmodel import Session, func, select

from app.models.course import Course
from app.models.knowledge import RetrievalChunk
from app.schemas.knowledge import CourseVectorStatusResponse
from app.shared.infra.env_support import get_env, get_env_choice
from app.shared.infra.runtime import is_cloud_mode
from app.shared.infra.settings import get_settings
from app.shared.infra.settings.support import llm_provider_requires_api_key, resolve_runtime_llm_provider
from app.shared.infra.course.settings import (
    build_course_index_ref_for_course,
    CourseEmbeddingBinding,
    CourseEmbeddingMode,
    get_course_embedding_binding,
)

COURSE_VECTOR_PRECHECK_DETAIL_MAP: dict[str, str] = {
    "embedding_not_configured": "当前后端未配置 embedding 模型，本轮会跳过 embedding 写入、向量检索和 RAG，知识文档与图谱仍会继续构建。",
    "embedding_api_key_missing": "当前后端缺少 embedding 所需的 API Key，本轮会跳过 embedding 写入、向量检索和 RAG，知识文档与图谱仍会继续构建。",
    "vector_extension_unavailable": "当前运行环境不可用向量索引，本轮会跳过 embedding 写入、向量检索和 RAG，知识文档与图谱仍会继续构建。",
    "llamaindex_unavailable": "当前环境缺少 LlamaIndex 依赖，本轮会跳过 embedding 写入、向量检索和 RAG，知识文档与图谱仍会继续构建。",
    "llamaindex_postgres_unavailable": "当前云端环境缺少 LlamaIndex Postgres 索引依赖，本轮会跳过 embedding 写入、向量检索和 RAG，知识文档与图谱仍会继续构建。",
    "course_not_bound": "当前课程尚未绑定 embedding 模型，请先确认是全量重建当前课程向量，还是继续以非向量模式构建。",
    "embedding_model_mismatch": "当前运行时 embedding 模型与课程已绑定模型不一致，请全量重建当前课程向量，或继续以非向量模式构建。",
    "embedding_dimension_mismatch": "当前运行时 embedding 维度与课程已绑定维度不一致，请全量重建当前课程向量，或继续以非向量模式构建。",
    "vector_table_missing": "当前课程缺少可用的向量索引，请全量重建当前课程向量，或继续以非向量模式构建。",
    "vector_table_dimension_mismatch": "当前课程向量索引维度与课程绑定配置不一致，请全量重建当前课程向量，或继续以非向量模式构建。",
}

_DISABLED_SEARCH_NOTICE = "当前课程未启用向量检索。"
_VECTOR_UNAVAILABLE_NOTICE = "当前课程向量检索暂不可用。"


class RuntimeEmbeddingConfig(BaseModel):
    """Current runtime embedding capability snapshot."""

    configured: bool = False
    available: bool = False
    embedding_model: str | None = None
    embedding_dim: int | None = None
    dimension_explicit: bool = False
    reason: str | None = None


class CourseVectorCapability(BaseModel):
    """Computed course-level vector capability state."""

    binding: CourseEmbeddingBinding | None = None
    status: CourseVectorStatusResponse
    queryable: bool = False
    writable: bool = False


def _can_load_local_sqlite_vec() -> bool:
    """Return whether sqlite-vec can actually be loaded by SQLite."""

    try:
        import sqlite_vec
    except ImportError:
        return False

    connection = sqlite3.connect(":memory:")
    try:
        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        return True
    except (AttributeError, OSError, sqlite3.Error):
        return False
    finally:
        try:
            connection.enable_load_extension(False)
        except Exception:
            pass
        connection.close()


def get_runtime_embedding_config() -> RuntimeEmbeddingConfig:
    """Return the runtime embedding configuration used by the backend."""

    settings = get_settings()
    model = settings.normalized_embedding_model
    embedding_dim = settings.embedding_dim or None
    base_url = get_env("LLM_BASE_URL")
    provider = resolve_runtime_llm_provider(base_url=base_url)
    dimension_explicit = settings.embedding_dim_is_explicit

    if model is None:
        return RuntimeEmbeddingConfig(reason="embedding_not_configured")
    if llm_provider_requires_api_key(provider, base_url=base_url) and not get_env_choice("LLM_API_KEY"):
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
    else:
        try:
            sqlite_vec_spec = importlib.util.find_spec("sqlite_vec")
        except ModuleNotFoundError:
            sqlite_vec_spec = None
        if sqlite_vec_spec is None or not _can_load_local_sqlite_vec():
            return RuntimeEmbeddingConfig(
                configured=True,
                embedding_model=model,
                embedding_dim=embedding_dim,
                dimension_explicit=dimension_explicit,
                reason="vector_extension_unavailable",
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


def get_course_record_by_id(session: Session, course_id: str) -> Course | None:
    """Return one course record by its stable course_id."""

    return session.exec(select(Course).where(Course.id == course_id)).first()


def course_has_retrieval_chunks(session: Session, course_id: str) -> bool:
    """Return whether a course currently has materialized retrieval chunks."""

    count = session.exec(
        select(func.count(RetrievalChunk.id)).where(RetrievalChunk.course_id == course_id)
    ).one()
    return int(count or 0) > 0


def build_course_vector_status(
    binding: CourseEmbeddingBinding | None,
    *,
    runtime: RuntimeEmbeddingConfig | None = None,
) -> CourseVectorStatusResponse:
    """Build one user-facing vector status payload."""

    current_runtime = runtime or get_runtime_embedding_config()

    if binding is None:
        if current_runtime.reason in COURSE_VECTOR_PRECHECK_DETAIL_MAP:
            return CourseVectorStatusResponse(
                mode=CourseEmbeddingMode.ENABLED.value,
                notice=COURSE_VECTOR_PRECHECK_DETAIL_MAP[current_runtime.reason],
            )
        return CourseVectorStatusResponse(mode=CourseEmbeddingMode.ENABLED.value)

    notice: str | None = None
    if binding.mode == CourseEmbeddingMode.DISABLED:
        notice = (
            "当前课程已切换为非向量模式。知识文档、图谱和课程结构仍可继续构建，"
            "但向量检索与依赖向量的能力已暂停；重新选择“全量重建向量”后可恢复。"
        )
    elif not current_runtime.available and current_runtime.reason in COURSE_VECTOR_PRECHECK_DETAIL_MAP:
        notice = COURSE_VECTOR_PRECHECK_DETAIL_MAP[current_runtime.reason]
    elif current_runtime.embedding_model != binding.embedding_model:
        notice = COURSE_VECTOR_PRECHECK_DETAIL_MAP["embedding_model_mismatch"]
    elif (
        current_runtime.dimension_explicit
        and current_runtime.embedding_dim != binding.embedding_dim
    ):
        notice = COURSE_VECTOR_PRECHECK_DETAIL_MAP["embedding_dimension_mismatch"]

    return CourseVectorStatusResponse(
        mode=binding.mode.value,
        notice=notice,
        embedding_model=binding.embedding_model,
        vector_table=binding.vector_table,
    )


def _build_table_conflict_status(
    binding: CourseEmbeddingBinding,
    *,
    reason: str,
) -> CourseVectorStatusResponse:
    return CourseVectorStatusResponse(
        mode=binding.mode.value,
        notice=COURSE_VECTOR_PRECHECK_DETAIL_MAP[reason],
        embedding_model=binding.embedding_model,
        vector_table=binding.vector_table,
    )


def get_course_vector_capability(
    session: Session,
    course: Course,
) -> CourseVectorCapability:
    """Return the course vector status plus whether vector search can run now."""

    binding = get_course_embedding_binding(course)
    runtime = get_runtime_embedding_config()
    status = build_course_vector_status(binding, runtime=runtime)
    expected_ref = build_course_index_ref_for_course(course)
    if status.vector_table is None and binding is not None:
        status.vector_table = expected_ref

    if binding is None:
        return CourseVectorCapability(
            binding=binding,
            status=status,
            queryable=False,
            writable=runtime.available,
        )
    if binding.mode == CourseEmbeddingMode.DISABLED:
        return CourseVectorCapability(
            binding=binding,
            status=status,
            queryable=False,
            writable=False,
        )
    if not runtime.available:
        return CourseVectorCapability(
            binding=binding,
            status=status,
            queryable=False,
            writable=False,
        )
    if binding.embedding_model != runtime.embedding_model:
        return CourseVectorCapability(
            binding=binding,
            status=status,
            queryable=False,
            writable=False,
        )
    if binding.embedding_dim is None:
        return CourseVectorCapability(
            binding=binding,
            status=status,
            queryable=False,
            writable=False,
        )
    if runtime.dimension_explicit and binding.embedding_dim != runtime.embedding_dim:
        return CourseVectorCapability(
            binding=binding,
            status=status,
            queryable=False,
            writable=False,
        )
    if not binding.vector_table or binding.vector_table != expected_ref:
        if not course_has_retrieval_chunks(session, course.id):
            return CourseVectorCapability(
                binding=binding,
                status=status,
                queryable=False,
                writable=True,
            )
        return CourseVectorCapability(
            binding=binding,
            status=_build_table_conflict_status(binding, reason="vector_table_missing"),
            queryable=False,
            writable=True,
        )
    if is_cloud_mode():
        from app.shared.infra.database import get_vector_table_dim, vector_table_exists

        connection = session.connection()
        index_exists = vector_table_exists(connection, expected_ref)
    else:
        from app.shared.infra.search.llamaindex_index import course_index_exists

        connection = None
        index_exists = course_index_exists(course.id)

    if not index_exists:
        if not course_has_retrieval_chunks(session, course.id):
            return CourseVectorCapability(
                binding=binding,
                status=status,
                queryable=False,
                writable=True,
            )
        return CourseVectorCapability(
            binding=binding,
            status=_build_table_conflict_status(binding, reason="vector_table_missing"),
            queryable=False,
            writable=True,
        )

    if connection is not None:
        table_dim = get_vector_table_dim(connection, expected_ref)
        if table_dim is not None and table_dim != binding.embedding_dim:
            return CourseVectorCapability(
                binding=binding,
                status=_build_table_conflict_status(binding, reason="vector_table_dimension_mismatch"),
                queryable=False,
                writable=False,
            )

    return CourseVectorCapability(binding=binding, status=status, queryable=True, writable=True)


def get_course_vector_status(
    session: Session,
    course: Course,
) -> CourseVectorStatusResponse:
    """Return only the public course vector status payload."""

    return get_course_vector_capability(session, course).status


def get_course_vector_status_by_id(
    session: Session,
    course_id: str,
) -> CourseVectorStatusResponse:
    """Return the vector status for one course ID."""

    course = get_course_record_by_id(session, course_id)
    if course is None:
        return CourseVectorStatusResponse()
    return get_course_vector_status(session, course)


def should_generate_course_embeddings(
    session: Session,
    *,
    course_id: str,
) -> bool:
    """Return whether the current build should generate embeddings."""

    course = get_course_record_by_id(session, course_id)
    if course is None:
        return False

    capability = get_course_vector_capability(session, course)
    return capability.writable


def get_course_vector_search_notice(
    session: Session,
    *,
    course_id: str,
) -> str | None:
    """Return one stable search notice when vector retrieval is unavailable."""

    course = get_course_record_by_id(session, course_id)
    if course is None:
        return None

    capability = get_course_vector_capability(session, course)
    if capability.queryable:
        return None
    if capability.binding is not None and capability.binding.mode == CourseEmbeddingMode.DISABLED:
        return _DISABLED_SEARCH_NOTICE
    if capability.status.notice:
        return capability.status.notice
    return _VECTOR_UNAVAILABLE_NOTICE


__all__ = [
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
]
