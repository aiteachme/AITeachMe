"""Helpers for restoring published knowledge-document manifests."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Sequence

from sqlmodel import Session, select

from app.models.knowledge_doc import KnowledgeDocument
from app.shared.infra.knowledge.build_store import (
    KnowledgeDocsManifest,
    read_knowledge_manifest,
    write_knowledge_manifest,
)
from app.shared.infra.storage import CourseStorageScope
from app.utils.time import ensure_utc_datetime, utcnow


_VERSIONED_PATH_MARKER = "/knowledge_markdowns/versions"
_VERSION_SEGMENT_RE = re.compile(r"^v\d{4,}$")
_RECEIPT_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class PublishedVersionedPathResolution:
    """Validated versioned publication location for one committed doc set."""

    detected: bool
    parent: str | None


def resolve_published_versioned_paths(
    docs: Sequence[KnowledgeDocument],
    *,
    course_scope: CourseStorageScope,
) -> PublishedVersionedPathResolution:
    """Resolve one trusted receipt parent, failing closed on mixed paths."""

    paths = [str(doc.markdown_path or "").strip() for doc in docs]
    detected = any(
        _VERSIONED_PATH_MARKER in path.replace("\\", "/").lower()
        for path in paths
    )
    if not detected:
        return PublishedVersionedPathResolution(detected=False, parent=None)

    versioned_prefix = f"{course_scope.namespace}/knowledge_markdowns/versions/"
    parents: set[str] = set()
    for path in paths:
        if not path.startswith(versioned_prefix) or "\\" in path:
            return PublishedVersionedPathResolution(detected=True, parent=None)
        relative_path = path.removeprefix(versioned_prefix)
        receipt_path, separator, filename = relative_path.rpartition("/")
        receipt_parts = receipt_path.split("/")
        if (
            not separator
            or len(receipt_parts) != 2
            or _VERSION_SEGMENT_RE.fullmatch(receipt_parts[0]) is None
            or _RECEIPT_SEGMENT_RE.fullmatch(receipt_parts[1]) is None
            or not filename
            or filename != filename.strip()
            or filename in {".", ".."}
            or not filename.lower().endswith(".md")
        ):
            return PublishedVersionedPathResolution(detected=True, parent=None)
        parents.add(f"{versioned_prefix}{receipt_path}")

    if len(parents) != 1:
        return PublishedVersionedPathResolution(detected=True, parent=None)
    return PublishedVersionedPathResolution(detected=True, parent=next(iter(parents)))


def ensure_published_knowledge_manifest(
    session: Session,
    *,
    course_id: str,
    course_scope: CourseStorageScope,
) -> KnowledgeDocsManifest | None:
    """Return the published-doc manifest, rebuilding it from DB rows when absent."""

    stored_manifest = read_knowledge_manifest(course_id, course_scope=course_scope)
    manifest = select_published_knowledge_manifest(
        session,
        course_id=course_id,
        course_scope=course_scope,
        stored_manifest=stored_manifest,
    )
    if manifest is None:
        return None

    if stored_manifest is None or manifest != stored_manifest:
        write_knowledge_manifest(course_id, manifest, course_scope=course_scope)
    return manifest


def select_published_knowledge_manifest(
    session: Session,
    *,
    course_id: str,
    course_scope: CourseStorageScope,
    stored_manifest: KnowledgeDocsManifest | None,
    prompt: str | None = None,
    build_session_id: str | None = None,
) -> KnowledgeDocsManifest | None:
    """Use committed DB rows as the authoritative publication pointer."""

    derived_manifest = build_manifest_from_published_docs(
        session,
        course_id=course_id,
        course_scope=course_scope,
        prompt=prompt,
        build_session_id=build_session_id,
    )
    if derived_manifest is None:
        return None
    if stored_manifest is not None and _matches_committed_publication(
        stored_manifest,
        derived_manifest,
    ):
        return stored_manifest
    return derived_manifest


def _matches_committed_publication(
    stored_manifest: KnowledgeDocsManifest,
    derived_manifest: KnowledgeDocsManifest,
) -> bool:
    """Return whether one storage projection belongs to the DB publication."""

    if int(stored_manifest.version_no or 0) != int(derived_manifest.version_no or 0):
        return False

    stored_manifest_key = str(stored_manifest.docgen_manifest_key or "").strip()
    derived_manifest_key = str(derived_manifest.docgen_manifest_key or "").strip()
    if stored_manifest_key or derived_manifest_key:
        return bool(
            stored_manifest_key
            and derived_manifest_key
            and stored_manifest_key == derived_manifest_key
        )

    # Legacy publications have no versioned manifest key. Match every stable
    # field that can be reconstructed from the committed document rows.
    return (
        ensure_utc_datetime(stored_manifest.updated_at)
        == ensure_utc_datetime(derived_manifest.updated_at)
        and int(stored_manifest.chapter_count or 0) == int(derived_manifest.chapter_count or 0)
        and _normalized_strings(stored_manifest.chapter_titles)
        == _normalized_strings(derived_manifest.chapter_titles)
        and sorted(set(_normalized_strings(stored_manifest.source_file_ids)))
        == sorted(set(_normalized_strings(derived_manifest.source_file_ids)))
    )


def _normalized_strings(values: list[str]) -> list[str]:
    return [normalized for value in values if (normalized := str(value or "").strip())]


def build_manifest_from_published_docs(
    session: Session,
    *,
    course_id: str,
    course_scope: CourseStorageScope,
    prompt: str | None = None,
    build_session_id: str | None = None,
) -> KnowledgeDocsManifest | None:
    """Build a minimal manifest from current published KnowledgeDocument rows."""

    docs = list(
        session.exec(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.course_id == course_id,
                KnowledgeDocument.is_current.is_(True),
                KnowledgeDocument.status == "published",
            )
            .order_by(
                KnowledgeDocument.order_index,
                KnowledgeDocument.chapter_index,
                KnowledgeDocument.id,
            )
        ).all()
    )
    if not docs:
        return None

    chapter_docs = [doc for doc in docs if (doc.document_role or "chapter") == "chapter"] or docs
    source_file_ids = sorted(
        {
            str(file_id).strip()
            for doc in docs
            for file_id in _json_list(doc.source_file_ids)
            if str(file_id).strip()
        }
    )
    timestamps = [
        normalized
        for doc in docs
        if (normalized := ensure_utc_datetime(doc.published_at or doc.updated_at or doc.created_at)) is not None
    ]
    versioned_paths = resolve_published_versioned_paths(docs, course_scope=course_scope)
    expected_session_id = str(build_session_id or "").strip()
    resolved_prompt = (
        str(prompt or "").strip() or None
        if expected_session_id
        and any(str(doc.build_session_id or "").strip() == expected_session_id for doc in docs)
        else None
    )
    return KnowledgeDocsManifest(
        updated_at=max(timestamps) if timestamps else utcnow(),
        version_no=max(int(doc.version_no or doc.version or 1) for doc in docs),
        source_file_ids=source_file_ids,
        prompt=resolved_prompt,
        chapter_count=len(chapter_docs),
        chapter_titles=[doc.title for doc in chapter_docs if doc.title],
        docgen_manifest_key=(
            f"{versioned_paths.parent}/docgen_manifest.json"
            if versioned_paths.parent is not None
            else None
        ),
    )


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []
