"""Subject-scoped embedding settings helpers."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.models.subject import Subject
from app.shared.infra.runtime import is_cloud_mode
from app.utils.time import utcnow

_LEGACY_VECTOR_TABLE = "chunk_embeddings"
_SUBJECT_VECTOR_TABLE_PREFIX = "chunk_embeddings_"
_POSTGRES_VECTOR_REF = "retrieval_chunk.embedding"


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


def get_legacy_vector_table_name() -> str:
    """Return the legacy global vector table name."""

    return _LEGACY_VECTOR_TABLE


def build_subject_vector_table_name(subject_slug: str) -> str:
    """Return the subject-scoped vector table name."""

    normalized = subject_slug.strip().replace("-", "_")
    return f"{_SUBJECT_VECTOR_TABLE_PREFIX}{normalized}"


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

    vector_target = (
        _POSTGRES_VECTOR_REF
        if is_cloud_mode()
        else build_subject_vector_table_name(subject_slug)
    )

    return SubjectEmbeddingBinding(
        mode=SubjectEmbeddingMode.ENABLED,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        vector_table=vector_target,
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
            else (
                _POSTGRES_VECTOR_REF
                if is_cloud_mode()
                else build_subject_vector_table_name(subject_slug)
            )
        ),
        disabled_reason=disabled_reason,
        updated_at=updated_at or utcnow(),
    )


__all__ = [
    "SubjectEmbeddingBinding",
    "SubjectEmbeddingMode",
    "SubjectSettingsPayload",
    "build_disabled_binding",
    "build_enabled_binding",
    "build_subject_vector_table_name",
    "get_postgres_vector_ref",
    "dump_subject_settings",
    "get_legacy_vector_table_name",
    "get_subject_embedding_binding",
    "load_subject_settings",
    "set_subject_embedding_binding",
]


def get_postgres_vector_ref() -> str:
    """Return the canonical pgvector storage target."""

    return _POSTGRES_VECTOR_REF
