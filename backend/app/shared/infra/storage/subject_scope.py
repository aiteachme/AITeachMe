"""Subject-scoped storage namespace helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlmodel import select

from app.models.subject import Subject
from app.shared.infra.database import managed_session
from app.shared.infra.exceptions import SubjectRegistryNotFoundError
from app.utils.subject import validate_subject

_INVALID_USER_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_user_segment(user_id: str) -> str:
    cleaned = _INVALID_USER_SEGMENT_RE.sub("_", str(user_id or "").strip()).strip("._")
    return cleaned or "local"


@dataclass(frozen=True)
class SubjectStorageScope:
    """Canonical persisted storage namespace for one user-owned subject."""

    user_id: str
    subject: str

    @property
    def user_segment(self) -> str:
        return _sanitize_user_segment(self.user_id)

    @property
    def namespace(self) -> str:
        return f"users/{self.user_segment}/subjects/{self.subject}"

    def subject_prefix(self) -> str:
        return f"{self.namespace}/"

    def raw_file_key(self, file_id: int, extension: str) -> str:
        normalized_extension = extension if extension.startswith(".") else f".{extension}"
        return f"{self.namespace}/raw_files/{file_id}{normalized_extension}"

    def raw_markdown_key(self, file_id: int) -> str:
        return f"{self.namespace}/raw_markdowns/{file_id}.md"

    def asset_key(self, file_id: int, name: str) -> str:
        return f"{self.namespace}/assets/{file_id}/{name}"

    def asset_prefix(self, file_id: int) -> str:
        return f"{self.namespace}/assets/{file_id}/"

    def knowledge_doc_key(self, filename: str) -> str:
        return f"{self.namespace}/knowledge_markdowns/{filename}"

    def knowledge_build_prefix(self) -> str:
        return f"{self.namespace}/knowledge_markdowns/_build/"

    def chunk_manifest_key(self) -> str:
        return f"{self.namespace}/knowledge_markdowns/chunk_manifest.json"

    def build_status_key(self) -> str:
        return f"{self.namespace}/knowledge_markdowns/_build/status.json"

    def build_runtime_key(self) -> str:
        return f"{self.namespace}/knowledge_markdowns/_build/runtime.json"

    def build_manifest_key(self) -> str:
        return f"{self.namespace}/knowledge_markdowns/_build/manifest.json"

    def embedding_cache_key(self) -> str:
        return f"{self.namespace}/cache/node_embedding_cache.json"


def build_subject_storage_scope(*, user_id: str, subject: str) -> SubjectStorageScope:
    """Create the canonical storage scope for one user-owned subject."""

    return SubjectStorageScope(
        user_id=str(user_id or "local"),
        subject=validate_subject(subject),
    )


def resolve_subject_storage_scope(subject: str) -> SubjectStorageScope:
    """Resolve a subject slug into its persisted storage scope."""

    normalized_subject = validate_subject(subject)
    with managed_session() as session:
        record = session.exec(select(Subject).where(Subject.slug == normalized_subject)).first()
        if record is None:
            raise SubjectRegistryNotFoundError(normalized_subject)
        return build_subject_storage_scope(
            user_id=record.user_id,
            subject=record.slug,
        )


__all__ = [
    "SubjectStorageScope",
    "build_subject_storage_scope",
    "resolve_subject_storage_scope",
]
