"""Course-scoped embedding settings helpers."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.models.course import Course
from app.shared.infra.runtime import is_cloud_mode
from app.utils.time import utcnow

_LOCAL_LLAMA_INDEX_REF_PREFIX = "llamaindex://sqlite-vec/"
_POSTGRES_LLAMA_INDEX_REF_PREFIX = "llamaindex://postgres/"
_POSTGRES_LLAMA_INDEX_NAME_PREFIX = "atm_llamaindex_rag_"
_POSTGRES_LLAMA_INDEX_DATA_PREFIX = "data_"
_POSTGRES_IDENTIFIER_MAX_CHARS = 63
_INVALID_USER_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


class CourseEmbeddingMode(str, Enum):
    """Allowed course-level embedding modes."""

    ENABLED = "enabled"
    DISABLED = "disabled"


class CourseEmbeddingBinding(BaseModel):
    """Embedding binding persisted inside ``course.settings_json``."""

    mode: CourseEmbeddingMode = CourseEmbeddingMode.ENABLED
    embedding_model: str | None = None
    embedding_dim: int | None = None
    vector_table: str | None = None
    disabled_reason: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class CourseSettingsPayload(BaseModel):
    """Structured representation of ``course.settings_json``."""

    model_config = ConfigDict(extra="allow")

    embedding: CourseEmbeddingBinding | None = None
def _sanitize_user_segment(user_id: str | None) -> str:
    cleaned = _INVALID_USER_SEGMENT_RE.sub("_", str(user_id or "").strip()).strip("._")
    return cleaned or "local"


def _normalize_course_index_token(course_id: str, *, owner_user_id: str | None = None) -> str:
    raw_course = (course_id or "").strip().lower()
    raw_user = _sanitize_user_segment(owner_user_id).lower()
    normalized_course = re.sub(r"[^a-z0-9_]+", "_", raw_course).strip("_") or "course"
    # PGVectorStore derives ``data_<name>_embedding_idx``. Keep that longest
    # identifier below PostgreSQL's 63-character limit while retaining a
    # user-and-course-scoped digest.
    digest = hashlib.sha1(f"{raw_user}:{raw_course}".encode("utf-8")).hexdigest()[:13]
    trimmed_course = normalized_course[:8]
    return f"{trimmed_course}_{digest}"


def build_postgres_course_index_name(course_id: str, *, owner_user_id: str) -> str:
    """Return the deterministic PGVector index name for one course."""

    return (
        f"{_POSTGRES_LLAMA_INDEX_NAME_PREFIX}"
        f"{_normalize_course_index_token(course_id, owner_user_id=owner_user_id)}"
    )


def build_postgres_course_index_data_table_name(
    course_id: str,
    *,
    owner_user_id: str,
) -> str:
    """Return the concrete PostgreSQL data table used by PGVectorStore.

    PGVectorStore prefixes the index name with ``data_``. PostgreSQL silently
    truncates longer identifiers, so mirror that rule for existence checks and
    direct SQL queries.
    """

    table_name = (
        f"{_POSTGRES_LLAMA_INDEX_DATA_PREFIX}"
        f"{build_postgres_course_index_name(course_id, owner_user_id=owner_user_id)}"
    )
    return table_name[:_POSTGRES_IDENTIFIER_MAX_CHARS]


def extract_postgres_course_index_name(vector_ref: str | None) -> str | None:
    """Extract the PGVector index name from one stored vector ref."""

    value = (vector_ref or "").strip()
    if not value.startswith(_POSTGRES_LLAMA_INDEX_REF_PREFIX):
        return None
    index_name = value.removeprefix(_POSTGRES_LLAMA_INDEX_REF_PREFIX).strip().lower()
    return index_name or None


def extract_postgres_course_index_data_table_name(vector_ref: str | None) -> str | None:
    """Extract the concrete PostgreSQL PGVector data table from one vector ref."""

    index_name = extract_postgres_course_index_name(vector_ref)
    if not index_name:
        return None
    return f"{_POSTGRES_LLAMA_INDEX_DATA_PREFIX}{index_name}"[
        :_POSTGRES_IDENTIFIER_MAX_CHARS
    ]


def build_course_index_ref(course_id: str, *, owner_user_id: str) -> str:
    """Return the course-scoped LlamaIndex storage reference."""

    if is_cloud_mode():
        return (
            f"{_POSTGRES_LLAMA_INDEX_REF_PREFIX}"
            f"{build_postgres_course_index_name(course_id, owner_user_id=owner_user_id)}"
        )
    user_segment = _sanitize_user_segment(owner_user_id)
    return (
        f"{_LOCAL_LLAMA_INDEX_REF_PREFIX}"
        f"users/{user_segment}/courses/{course_id.strip()}/rag_index"
    )


def build_course_index_ref_for_course(course: Course) -> str:
    """Return the deterministic vector reference for one course record."""

    return build_course_index_ref(
        course.id,
        owner_user_id=course.user_id,
    )


def load_course_settings(course: Course) -> CourseSettingsPayload:
    """Parse ``course.settings_json`` into a structured payload."""

    raw_value = (course.settings_json or "").strip()
    if not raw_value:
        return CourseSettingsPayload()

    try:
        return CourseSettingsPayload.model_validate_json(raw_value)
    except Exception:
        return CourseSettingsPayload()


def dump_course_settings(course: Course, settings_payload: CourseSettingsPayload) -> None:
    """Persist the structured settings payload back to the course model."""

    course.settings_json = settings_payload.model_dump_json()


def get_course_embedding_binding(course: Course) -> CourseEmbeddingBinding | None:
    """Read the course-level embedding binding."""

    return load_course_settings(course).embedding


def set_course_embedding_binding(course: Course, binding: CourseEmbeddingBinding | None) -> None:
    """Update the course-level embedding binding."""

    settings_payload = load_course_settings(course)
    settings_payload.embedding = binding
    dump_course_settings(course, settings_payload)


def build_enabled_binding(
    *,
    course_id: str,
    owner_user_id: str,
    embedding_model: str,
    embedding_dim: int,
    updated_at: datetime | None = None,
) -> CourseEmbeddingBinding:
    """Create an enabled binding for one course."""

    return CourseEmbeddingBinding(
        mode=CourseEmbeddingMode.ENABLED,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        vector_table=build_course_index_ref(course_id, owner_user_id=owner_user_id),
        disabled_reason=None,
        updated_at=updated_at or utcnow(),
    )


def build_disabled_binding(
    *,
    course_id: str,
    owner_user_id: str,
    disabled_reason: str,
    previous_binding: CourseEmbeddingBinding | None = None,
    updated_at: datetime | None = None,
) -> CourseEmbeddingBinding:
    """Create a disabled binding while keeping any previous metadata."""

    return CourseEmbeddingBinding(
        mode=CourseEmbeddingMode.DISABLED,
        embedding_model=(
            previous_binding.embedding_model if previous_binding is not None else None
        ),
        embedding_dim=(
            previous_binding.embedding_dim if previous_binding is not None else None
        ),
        vector_table=(
            previous_binding.vector_table
            if previous_binding is not None
            else build_course_index_ref(course_id, owner_user_id=owner_user_id)
        ),
        disabled_reason=disabled_reason,
        updated_at=updated_at or utcnow(),
    )
__all__ = [
    "CourseEmbeddingBinding",
    "CourseEmbeddingMode",
    "CourseSettingsPayload",
    "build_disabled_binding",
    "build_enabled_binding",
    "build_postgres_course_index_data_table_name",
    "build_postgres_course_index_name",
    "build_course_index_ref",
    "build_course_index_ref_for_course",
    "dump_course_settings",
    "extract_postgres_course_index_data_table_name",
    "extract_postgres_course_index_name",
    "get_course_embedding_binding",
    "load_course_settings",
    "set_course_embedding_binding",
]
