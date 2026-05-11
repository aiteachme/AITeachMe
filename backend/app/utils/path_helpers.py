"""Filesystem path helpers for runtime data.

This is the canonical location for all runtime path construction helpers.
Pure functions with no business logic — only depends on ``core.runtime_paths``.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.shared.infra.runtime import get_runtime_data_dir


def get_data_dir() -> Path:
    """Return the runtime data root directory."""

    return get_runtime_data_dir()


def _canonical_course_dir(course_id: str, *, user_id: str | None = None) -> Path:
    """Return the canonical course directory under `users/<user>/courses/`."""

    if user_id is not None:
        from app.shared.infra.storage import build_course_storage_scope

        scope = build_course_storage_scope(user_id=user_id, course_id=course_id)
    else:
        from app.shared.infra.storage import resolve_course_storage_scope

        scope = resolve_course_storage_scope(course_id)
    return get_data_dir() / scope.namespace


def build_course_dir(course_id: str, *, user_id: str | None = None) -> Path:
    """Return the course data directory."""

    return _canonical_course_dir(course_id, user_id=user_id)


def build_temp_dir(course_id: str, *, user_id: str | None = None) -> Path:
    """Return the temp directory."""

    return build_course_dir(course_id, user_id=user_id) / "temp"


def build_user_file_temp_dir(*, user_id: str) -> Path:
    """Return the user-library temp directory."""

    from app.shared.infra.storage import build_user_file_storage_scope

    scope = build_user_file_storage_scope(user_id=user_id)
    return get_data_dir() / scope.namespace / "temp"


def build_knowledge_markdown_dir(course_id: str, *, user_id: str | None = None) -> Path:
    """Return the published knowledge-markdown directory."""

    return build_course_dir(course_id, user_id=user_id) / "knowledge_markdowns"


def build_knowledge_markdown_build_dir(course_id: str) -> Path:
    """Return the knowledge-markdown build/intermediate directory."""

    return build_knowledge_markdown_dir(course_id) / "_build"


def build_knowledge_build_lock_path(course_id: str) -> Path:
    """Return the course-level knowledge docs lock path."""

    return build_knowledge_markdown_dir(course_id) / ".build.lock"


def build_docgen_intermediate_latest_dir(course_id: str) -> Path:
    """Return the current build intermediate directory."""

    return build_knowledge_markdown_build_dir(course_id)


_INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*\r\n\t]+')
_WHITESPACE_RE = re.compile(r"\s+")
_MULTI_UNDERSCORE_RE = re.compile(r"_+")


def sanitize_doc_title(title: str) -> str:
    """Sanitize a chapter/doc title for use in filenames and storage keys."""

    normalized = _WHITESPACE_RE.sub(" ", title).strip()
    normalized = _INVALID_FILENAME_CHARS_RE.sub("_", normalized)
    normalized = normalized.replace(".", "_")
    normalized = _MULTI_UNDERSCORE_RE.sub("_", normalized).strip(" _.")
    return (normalized or "untitled")[:50]


def _sanitize_storage_token(value: str) -> str:
    cleaned = re.sub(r"[^\w\-]+", "_", value).strip("_")
    return cleaned or "file"


def build_asset_name_prefix(
    *,
    filename: str | None = None,
    file_id: str | None = None,
) -> str:
    """Build a deterministic asset filename prefix for one raw file."""

    stem = Path(filename or "").stem or "file"
    safe_stem = _sanitize_storage_token(stem)[:24]
    identity = file_id or safe_stem
    safe_identity = _sanitize_storage_token(identity)[:48]
    return f"{safe_stem}__{safe_identity}__"


def list_asset_files(
    asset_dir: str | Path | None,
    *,
    asset_name_prefix: str | None = None,
) -> list[Path]:
    """List asset files, optionally filtered by filename prefix."""

    if not asset_dir:
        return []

    path = Path(asset_dir)
    if not path.exists() or not path.is_dir():
        return []

    return [
        item
        for item in sorted(path.iterdir())
        if item.is_file() and (not asset_name_prefix or item.name.startswith(asset_name_prefix))
    ]


def to_storage_key(path: str | Path) -> str:
    """Convert an absolute runtime path into a local storage key."""

    absolute_path = Path(path).resolve()
    data_dir = get_data_dir()
    return absolute_path.relative_to(data_dir).as_posix()


def resolve_storage_key_path(storage_key: str) -> Path:
    """Resolve a local storage key into an absolute runtime path."""

    return (get_data_dir() / storage_key).resolve()
