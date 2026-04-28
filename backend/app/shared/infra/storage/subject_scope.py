"""Subject-scoped storage namespace helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlmodel import Session, select

from app.models.subject import Subject
from app.shared.infra.database import managed_session
from app.shared.infra.exceptions import SubjectRegistryNotFoundError
from app.utils.subject import validate_subject_id

_INVALID_USER_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")
_INVALID_STORAGE_SEGMENT_RE = re.compile(r"[^\w.-]+", re.UNICODE)
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


def _sanitize_user_segment(user_id: str) -> str:
    cleaned = _INVALID_USER_SEGMENT_RE.sub("_", str(user_id or "").strip()).strip("._")
    return cleaned or "local"


def _sanitize_storage_segment(value: str | None, *, default: str, max_length: int) -> str:
    basename = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _INVALID_STORAGE_SEGMENT_RE.sub("_", basename.strip())
    cleaned = _MULTI_UNDERSCORE_RE.sub("_", cleaned).strip(" ._")
    return (cleaned or default)[:max_length].strip(" ._") or default


def sanitize_storage_file_stem(filename: str | None) -> str:
    """Return a readable, storage-safe stem for an uploaded filename."""

    basename = str(filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if "." in basename.strip("."):
        stem = basename.rsplit(".", 1)[0]
    else:
        stem = basename
    return _sanitize_storage_segment(stem, default="untitled", max_length=80)


def build_file_storage_segment(*, file_uid: str, filename: str | None) -> str:
    """Build a stable per-file storage segment.

    The uid remains the identity anchor; the sanitized filename stem is only
    for operator readability when browsing local data dirs or object storage.
    """

    safe_uid = _sanitize_storage_segment(file_uid, default="file", max_length=64)
    safe_stem = sanitize_storage_file_stem(filename)
    return f"{safe_uid}__{safe_stem}"


def _normalize_extension(extension: str) -> str:
    cleaned = str(extension or "").strip()
    if not cleaned:
        return ""
    return cleaned if cleaned.startswith(".") else f".{cleaned}"


@dataclass(frozen=True)
class UserFileStorageScope:
    """Canonical persisted storage namespace for one user's source-file library."""

    user_id: str

    @property
    def user_segment(self) -> str:
        return _sanitize_user_segment(self.user_id)

    @property
    def namespace(self) -> str:
        return f"users/{self.user_segment}/files"

    def file_prefix(self, *, file_uid: str, filename: str | None) -> str:
        return f"{self.namespace}/{build_file_storage_segment(file_uid=file_uid, filename=filename)}/"

    def raw_file_key(self, *, file_uid: str, filename: str | None, extension: str) -> str:
        normalized_extension = _normalize_extension(extension)
        return f"{self.file_prefix(file_uid=file_uid, filename=filename)}raw{normalized_extension}"

    def raw_markdown_key(self, *, file_uid: str, filename: str | None) -> str:
        return f"{self.file_prefix(file_uid=file_uid, filename=filename)}markdown.md"

    def asset_key(self, *, file_uid: str, filename: str | None, name: str) -> str:
        return f"{self.file_prefix(file_uid=file_uid, filename=filename)}assets/{name}"

    def asset_prefix(self, *, file_uid: str, filename: str | None) -> str:
        return f"{self.file_prefix(file_uid=file_uid, filename=filename)}assets/"


@dataclass(frozen=True)
class SubjectStorageScope:
    """Canonical persisted storage namespace for one user-owned subject."""

    user_id: str
    subject_id: str

    @property
    def user_segment(self) -> str:
        return _sanitize_user_segment(self.user_id)

    @property
    def namespace(self) -> str:
        return f"users/{self.user_segment}/subjects/{self.subject_id}"

    def subject_prefix(self) -> str:
        return f"{self.namespace}/"

    def file_storage_segment(self, *, file_uid: str, filename: str | None) -> str:
        return build_file_storage_segment(file_uid=file_uid, filename=filename)

    def raw_file_key(self, *, file_uid: str, filename: str | None, extension: str) -> str:
        normalized_extension = _normalize_extension(extension)
        segment = self.file_storage_segment(file_uid=file_uid, filename=filename)
        return f"{self.namespace}/raw_files/{segment}/raw{normalized_extension}"

    def raw_markdown_key(self, *, file_uid: str, filename: str | None) -> str:
        segment = self.file_storage_segment(file_uid=file_uid, filename=filename)
        return f"{self.namespace}/raw_markdowns/{segment}/markdown.md"

    def asset_key(self, *, file_uid: str, filename: str | None, name: str) -> str:
        return f"{self.asset_prefix(file_uid=file_uid, filename=filename)}{name}"

    def asset_prefix(self, *, file_uid: str, filename: str | None) -> str:
        segment = self.file_storage_segment(file_uid=file_uid, filename=filename)
        return f"{self.namespace}/assets/{segment}/"

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
        return f"{self.namespace}/knowledge_markdowns/manifest.json"

    def embedding_cache_key(self) -> str:
        return f"{self.namespace}/cache/node_embedding_cache.json"


def build_subject_storage_scope(*, user_id: str, subject_id: str) -> SubjectStorageScope:
    """Create the canonical storage scope for one user-owned subject."""

    return SubjectStorageScope(
        user_id=str(user_id or "local"),
        subject_id=validate_subject_id(subject_id),
    )


def build_user_file_storage_scope(*, user_id: str) -> UserFileStorageScope:
    """Create the canonical storage scope for one user's file library."""

    return UserFileStorageScope(user_id=str(user_id or "local"))


def resolve_subject_storage_scope(subject_id: str, *, session: Session | None = None) -> SubjectStorageScope:
    """Resolve a subject id into its persisted storage scope."""

    normalized_subject = validate_subject_id(subject_id)
    if session is not None:
        record = session.exec(select(Subject).where(Subject.id == normalized_subject)).first()
        if record is None:
            raise SubjectRegistryNotFoundError(normalized_subject)
        return build_subject_storage_scope(
            user_id=record.user_id,
            subject_id=record.id,
        )

    with managed_session() as session:
        record = session.exec(select(Subject).where(Subject.id == normalized_subject)).first()
        if record is None:
            raise SubjectRegistryNotFoundError(normalized_subject)
        return build_subject_storage_scope(
            user_id=record.user_id,
            subject_id=record.id,
        )


__all__ = [
    "SubjectStorageScope",
    "UserFileStorageScope",
    "build_file_storage_segment",
    "build_subject_storage_scope",
    "build_user_file_storage_scope",
    "resolve_subject_storage_scope",
    "sanitize_storage_file_stem",
]
