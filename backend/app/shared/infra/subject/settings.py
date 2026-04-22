"""Subject-scoped embedding settings helpers."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.models.subject import Subject
from app.shared.infra.runtime import is_cloud_mode
from app.utils.time import utcnow

_SUBJECT_VECTOR_TABLE_PREFIX = "chunk_embeddings_"
_POSTGRES_VECTOR_REF = "retrieval_chunk.embedding"
_LOCAL_LLAMA_INDEX_REF_PREFIX = "llamaindex://local/"
_POSTGRES_LLAMA_INDEX_REF_PREFIX = "llamaindex://postgres/"
_POSTGRES_LLAMA_INDEX_NAME_PREFIX = "atm_llamaindex_rag_"
_POSTGRES_LLAMA_INDEX_DATA_PREFIX = "data_"


class SubjectEmbeddingMode(str, Enum):
    """Allowed subject-level embedding modes."""

    ENABLED = "enabled"
    DISABLED = "disabled"


class SubjectEmbeddingBinding(BaseModel):
    """Embedding binding persisted inside ``subject.settings_json``."""

    mode: SubjectEmbeddingMode = SubjectEmbeddingMode.ENABLED
    embedding_model: str | None = None
    embedding_dim: int | None = None
    vector_table: str | None = None
    disabled_reason: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)


class SubjectSettingsPayload(BaseModel):
    """Structured representation of ``subject.settings_json``."""

    embedding: SubjectEmbeddingBinding | None = None


def build_subject_vector_table_name(subject_slug: str) -> str:
    """Return the subject-scoped vector table name."""

    normalized = subject_slug.strip().replace("-", "_")
    return f"{_SUBJECT_VECTOR_TABLE_PREFIX}{normalized}"


def _normalize_subject_index_token(subject_slug: str) -> str:
    raw = (subject_slug or "").strip().lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", raw).strip("_") or "subject"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    trimmed = normalized[:24]
    return f"{trimmed}_{digest}"


def build_postgres_subject_index_name(subject_slug: str) -> str:
    """Return the deterministic PGVector index name for one subject."""

    return f"{_POSTGRES_LLAMA_INDEX_NAME_PREFIX}{_normalize_subject_index_token(subject_slug)}"


def build_postgres_subject_index_data_table_name(subject_slug: str) -> str:
    """Return the concrete PostgreSQL data table used by PGVectorStore."""

    return f"{_POSTGRES_LLAMA_INDEX_DATA_PREFIX}{build_postgres_subject_index_name(subject_slug)}"


def extract_postgres_subject_index_name(vector_ref: str | None) -> str | None:
    """Extract the PGVector index name from one stored vector ref."""

    value = (vector_ref or "").strip()
    if not value.startswith(_POSTGRES_LLAMA_INDEX_REF_PREFIX):
        return None
    index_name = value.removeprefix(_POSTGRES_LLAMA_INDEX_REF_PREFIX).strip().lower()
    return index_name or None


def extract_postgres_subject_index_data_table_name(vector_ref: str | None) -> str | None:
    """Extract the concrete PostgreSQL PGVector data table from one vector ref."""

    index_name = extract_postgres_subject_index_name(vector_ref)
    if not index_name:
        return None
    return f"{_POSTGRES_LLAMA_INDEX_DATA_PREFIX}{index_name}"


def build_subject_index_ref(subject_slug: str) -> str:
    """Return the subject-scoped LlamaIndex storage reference."""

    if is_cloud_mode():
        return f"{_POSTGRES_LLAMA_INDEX_REF_PREFIX}{build_postgres_subject_index_name(subject_slug)}"
    return f"{_LOCAL_LLAMA_INDEX_REF_PREFIX}{subject_slug.strip()}/rag_index"


def load_subject_settings(subject: Subject) -> SubjectSettingsPayload:
    """Parse ``subject.settings_json`` into a structured payload."""

    raw_value = (subject.settings_json or "").strip()
    if not raw_value:
        return SubjectSettingsPayload()

    try:
        return SubjectSettingsPayload.model_validate_json(raw_value)
    except Exception:
        return SubjectSettingsPayload()


def dump_subject_settings(subject: Subject, settings_payload: SubjectSettingsPayload) -> None:
    """Persist the structured settings payload back to the subject model."""

    subject.settings_json = settings_payload.model_dump_json()


def get_subject_embedding_binding(subject: Subject) -> SubjectEmbeddingBinding | None:
    """Read the subject-level embedding binding."""

    return load_subject_settings(subject).embedding


def set_subject_embedding_binding(subject: Subject, binding: SubjectEmbeddingBinding | None) -> None:
    """Update the subject-level embedding binding."""

    settings_payload = load_subject_settings(subject)
    settings_payload.embedding = binding
    dump_subject_settings(subject, settings_payload)


def build_enabled_binding(
    *,
    subject_slug: str,
    embedding_model: str,
    embedding_dim: int,
    updated_at: datetime | None = None,
) -> SubjectEmbeddingBinding:
    """Create an enabled binding for one subject."""

    return SubjectEmbeddingBinding(
        mode=SubjectEmbeddingMode.ENABLED,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        vector_table=build_subject_index_ref(subject_slug),
        disabled_reason=None,
        updated_at=updated_at or utcnow(),
    )


def build_disabled_binding(
    *,
    subject_slug: str,
    disabled_reason: str,
    previous_binding: SubjectEmbeddingBinding | None = None,
    updated_at: datetime | None = None,
) -> SubjectEmbeddingBinding:
    """Create a disabled binding while keeping any previous metadata."""

    return SubjectEmbeddingBinding(
        mode=SubjectEmbeddingMode.DISABLED,
        embedding_model=(
            previous_binding.embedding_model if previous_binding is not None else None
        ),
        embedding_dim=(
            previous_binding.embedding_dim if previous_binding is not None else None
        ),
        vector_table=(
            previous_binding.vector_table
            if previous_binding is not None
            else build_subject_index_ref(subject_slug)
        ),
        disabled_reason=disabled_reason,
        updated_at=updated_at or utcnow(),
    )


def get_postgres_vector_ref() -> str:
    """Return the canonical pgvector storage target."""

    return _POSTGRES_VECTOR_REF


__all__ = [
    "SubjectEmbeddingBinding",
    "SubjectEmbeddingMode",
    "SubjectSettingsPayload",
    "build_disabled_binding",
    "build_enabled_binding",
    "build_postgres_subject_index_data_table_name",
    "build_postgres_subject_index_name",
    "build_subject_index_ref",
    "build_subject_vector_table_name",
    "dump_subject_settings",
    "extract_postgres_subject_index_data_table_name",
    "extract_postgres_subject_index_name",
    "get_postgres_vector_ref",
    "get_subject_embedding_binding",
    "load_subject_settings",
    "set_subject_embedding_binding",
]
