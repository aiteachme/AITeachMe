"""Version-pinned chunk views over the authoritative published document.

This module keeps the HTTP layer independent from DocGen storage details.  A
publication fingerprint is derived from the committed document rows, their
validated publication location, and the interactive overlays that are applied
to the learner-facing Markdown.  Callers re-check that fingerprint after the
Markdown read so a concurrent publication switch can never return new content
under an old publication id.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re
from threading import Lock
from typing import Sequence

from markdown_it import MarkdownIt
from markdown_it.token import Token

from app.repositories.knowledge.docgen_repo import get_current_published_doc_refs
from app.schemas.knowledge import (
    KnowledgeDocPublishedChunkResponse,
    KnowledgeDocPublishedChunkSummary,
    KnowledgeDocPublishedHeadingResponse,
    KnowledgeDocsPublishedManifestResponse,
)
from app.shared.infra.database import managed_session
from app.shared.infra.storage import CourseStorageScope
from app.utils.time import ensure_utc_datetime
from app.workflows.digest.docgen.lib.build_lifecycle import get_docgen_result
from app.workflows.digest.docgen.lib.interactive_overlays import load_current_interactive_overlays
from app.workflows.digest.docgen.lib.published_manifest import resolve_published_versioned_paths


_MARKDOWN_PARSER = MarkdownIt("commonmark")
_HEADING_SLUG_RE = re.compile(r"[^A-Za-z0-9_\u4e00-\u9fff]+")
_KU_HEADING_ATTR_RE = re.compile(r"\s*\{#ku_[A-Za-z0-9_-]+\}")
_KU_HEADING_COMMENT_RE = re.compile(
    r"\s*<!--\s*ATM_KU:\s*ku_[A-Za-z0-9_-]+\s*-->"
)
_MANIFEST_READ_ATTEMPTS = 3
_PUBLICATION_CACHE_SIZE = 8
_PUBLICATION_CACHE_LOCK = Lock()


class PublishedDocumentUnavailableError(RuntimeError):
    """Raised when a committed publication cannot be read safely."""


class PublishedDocumentStaleError(RuntimeError):
    """Raised when a requested publication is no longer current."""


class PublishedDocumentBoundaryError(RuntimeError):
    """Raised when chapter boundaries cannot be proven from the Markdown."""


class PublishedDocumentChunkNotFoundError(LookupError):
    """Raised when a chunk index is outside the current publication."""


@dataclass(frozen=True, slots=True)
class _PublishedChapter:
    chapter_index: int
    title: str


@dataclass(frozen=True, slots=True)
class _PublicationSnapshot:
    publication_id: str
    version_no: int
    updated_at: datetime | None
    chapters: tuple[_PublishedChapter, ...]


@dataclass(frozen=True, slots=True)
class _ParsedHeading:
    id: str
    text: str
    level: int
    start: int


@dataclass(frozen=True, slots=True)
class _PublishedChunk:
    chapter_index: int
    title: str
    heading_id: str
    markdown: str
    headings: tuple[KnowledgeDocPublishedHeadingResponse, ...]


@dataclass(frozen=True, slots=True)
class _CachedPublication:
    chunks: tuple[_PublishedChunk, ...]
    updated_at: datetime | None


_PUBLICATION_CACHE: OrderedDict[str, _CachedPublication] = OrderedDict()


def _get_cached_publication(publication_id: str) -> _CachedPublication | None:
    with _PUBLICATION_CACHE_LOCK:
        cached = _PUBLICATION_CACHE.get(publication_id)
        if cached is not None:
            _PUBLICATION_CACHE.move_to_end(publication_id)
        return cached


def _cache_publication(
    publication_id: str,
    *,
    chunks: Sequence[_PublishedChunk],
    updated_at: datetime | None,
) -> _CachedPublication:
    cached = _CachedPublication(chunks=tuple(chunks), updated_at=updated_at)
    with _PUBLICATION_CACHE_LOCK:
        _PUBLICATION_CACHE[publication_id] = cached
        _PUBLICATION_CACHE.move_to_end(publication_id)
        while len(_PUBLICATION_CACHE) > _PUBLICATION_CACHE_SIZE:
            _PUBLICATION_CACHE.popitem(last=False)
    return cached


def _heading_text(token: Token) -> str:
    """Flatten inline token text the same way the React heading renderer does."""

    def flatten(tokens: Sequence[Token]) -> str:
        parts: list[str] = []
        for child in tokens:
            # mdast images have no textual children, so MarkdownViewer's
            # extractMarkdownAstText intentionally excludes their alt text.
            if child.type == "image":
                continue
            if child.children:
                parts.append(flatten(child.children))
            elif child.type in {"text", "code_inline", "html_inline"}:
                parts.append(str(child.content or ""))
        return "".join(parts)

    text = flatten(token.children or [])
    text = _KU_HEADING_ATTR_RE.sub("", text)
    text = _KU_HEADING_COMMENT_RE.sub("", text)
    return text.strip()


def _heading_id(text: str, counts: dict[str, int]) -> str:
    """Mirror MarkdownViewer's ASCII word-character slug and duplicate counter."""

    base = _HEADING_SLUG_RE.sub("-", str(text or "").lower()).strip("-") or "section"
    count = counts.get(base, 0) + 1
    counts[base] = count
    return base if count == 1 else f"{base}-{count}"


def _line_offsets(markdown: str) -> list[int]:
    offsets = [0]
    for line in markdown.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _parse_root_headings(markdown: str) -> list[_ParsedHeading]:
    tokens = _MARKDOWN_PARSER.parse(markdown)
    line_offsets = _line_offsets(markdown)
    counts: dict[str, int] = {}
    headings: list[_ParsedHeading] = []
    for index, token in enumerate(tokens):
        if (
            token.type != "heading_open"
            or token.level != 0
            or token.tag not in {"h1", "h2", "h3", "h4", "h5", "h6"}
            or token.map is None
            or index + 1 >= len(tokens)
            or tokens[index + 1].type != "inline"
        ):
            continue
        text = _heading_text(tokens[index + 1])
        start_line = int(token.map[0])
        if start_line < 0 or start_line >= len(line_offsets):
            raise PublishedDocumentBoundaryError("published_heading_line_out_of_range")
        headings.append(
            _ParsedHeading(
                id=_heading_id(text, counts),
                text=text,
                level=int(token.tag[1:]),
                start=line_offsets[start_line],
            )
        )
    return headings


def _split_published_markdown(
    markdown: str,
    *,
    chapters: Sequence[_PublishedChapter],
) -> list[_PublishedChunk]:
    """Split at proven chapter H1 boundaries without changing any character."""

    if not markdown:
        raise PublishedDocumentUnavailableError("published_markdown_empty")
    if not chapters:
        raise PublishedDocumentBoundaryError("published_chapters_empty")

    parsed_headings = _parse_root_headings(markdown)
    chapter_headings = [heading for heading in parsed_headings if heading.level == 1]
    expected_titles = [chapter.title for chapter in chapters]
    actual_titles = [heading.text for heading in chapter_headings]
    if actual_titles != expected_titles:
        raise PublishedDocumentBoundaryError("published_chapter_headings_mismatch")

    # Prefix material belongs to chapter zero; every later chapter starts at
    # the exact source offset of its H1.  The final chunk naturally retains all
    # trailing references and appendices.
    chunk_starts = [0, *(heading.start for heading in chapter_headings[1:])]
    chunk_ends = [*chunk_starts[1:], len(markdown)]
    heading_payloads: list[list[KnowledgeDocPublishedHeadingResponse]] = [
        [] for _ in chapters
    ]
    for heading in parsed_headings:
        chunk_index = max(0, bisect_right(chunk_starts, heading.start) - 1)
        heading_payloads[chunk_index].append(
            KnowledgeDocPublishedHeadingResponse(
                id=heading.id,
                text=heading.text,
                level=heading.level,
                chunk_index=chunk_index,
            )
        )

    return [
        _PublishedChunk(
            chapter_index=chapter.chapter_index,
            title=chapter.title,
            heading_id=chapter_headings[index].id,
            markdown=markdown[chunk_starts[index] : chunk_ends[index]],
            headings=tuple(heading_payloads[index]),
        )
        for index, chapter in enumerate(chapters)
    ]


def _canonical_timestamp(value: datetime | None) -> str:
    normalized = ensure_utc_datetime(value)
    return normalized.isoformat() if normalized is not None else ""


def _load_publication_snapshot(
    *,
    course_id: str,
    course_scope: CourseStorageScope,
) -> _PublicationSnapshot | None:
    """Read one fresh identity snapshot of the committed live publication."""

    with managed_session() as session:
        docs = get_current_published_doc_refs(session, course_id)
    if not docs:
        return None

    versions = {int(doc.version_no or doc.version or 0) for doc in docs}
    if len(versions) != 1 or next(iter(versions)) <= 0:
        raise PublishedDocumentUnavailableError("published_document_versions_mixed")
    version_no = next(iter(versions))

    versioned_paths = resolve_published_versioned_paths(docs, course_scope=course_scope)
    if versioned_paths.detected and versioned_paths.parent is None:
        raise PublishedDocumentUnavailableError("published_document_paths_mixed")

    package_keys = {
        normalized
        for doc in docs
        if (normalized := str(doc.package_key or "").strip())
    }
    if len(package_keys) > 1:
        raise PublishedDocumentUnavailableError("published_document_packages_mixed")
    authority = versioned_paths.parent or (next(iter(package_keys)) if package_keys else "legacy")

    if any(doc.id is None for doc in docs):
        raise PublishedDocumentUnavailableError("published_document_id_missing")
    chapter_docs = [
        doc for doc in docs if str(doc.document_role or "chapter") == "chapter"
    ] or docs
    chapters = tuple(
        _PublishedChapter(
            chapter_index=int(doc.chapter_index),
            title=str(doc.title or "").strip(),
        )
        for doc in chapter_docs
    )
    if any(not chapter.title for chapter in chapters):
        raise PublishedDocumentUnavailableError("published_document_title_missing")

    timestamps = [
        normalized
        for doc in docs
        if (
            normalized := ensure_utc_datetime(
                doc.published_at or doc.updated_at or doc.created_at
            )
        )
        is not None
    ]
    updated_at = max(timestamps) if timestamps else None
    overlays = load_current_interactive_overlays(course_scope, version_no=version_no)
    identity = {
        "version_no": version_no,
        "authority": authority,
        "docs": [
            {
                "id": int(doc.id),
                "chapter_index": int(doc.chapter_index),
                "order_index": int(doc.order_index or 0),
                "title": str(doc.title or ""),
                "role": str(doc.document_role or "chapter"),
                "path": str(doc.markdown_path or ""),
                "updated_at": _canonical_timestamp(doc.updated_at),
            }
            for doc in docs
        ],
        "overlays": overlays,
    }
    digest = hashlib.sha256(
        json.dumps(
            identity,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()[:20]
    return _PublicationSnapshot(
        publication_id=f"v{version_no:04d}-{digest}",
        version_no=version_no,
        updated_at=updated_at,
        chapters=chapters,
    )


def _load_snapshot_chunks(
    snapshot: _PublicationSnapshot,
    *,
    course_id: str,
    course_scope: CourseStorageScope,
) -> tuple[list[_PublishedChunk], datetime | None]:
    cached = _get_cached_publication(snapshot.publication_id)
    if cached is None:
        result = get_docgen_result(
            course_id=course_id,
            course_scope=course_scope,
            include_markdown=True,
            include_draft=False,
        )
        if not result.exists or not result.markdown:
            raise PublishedDocumentUnavailableError("published_markdown_unavailable")
        chunks = _split_published_markdown(result.markdown, chapters=snapshot.chapters)
        cached = _CachedPublication(
            chunks=tuple(chunks),
            updated_at=result.updated_at or snapshot.updated_at,
        )
    current = _load_publication_snapshot(course_id=course_id, course_scope=course_scope)
    if current is None or current.publication_id != snapshot.publication_id:
        raise PublishedDocumentStaleError("published_document_changed_during_read")
    if _get_cached_publication(snapshot.publication_id) is None:
        cached = _cache_publication(
            snapshot.publication_id,
            chunks=cached.chunks,
            updated_at=cached.updated_at,
        )
    return list(cached.chunks), cached.updated_at


def get_published_doc_manifest(
    *,
    course_id: str,
    course_scope: CourseStorageScope,
) -> KnowledgeDocsPublishedManifestResponse:
    """Return a stable lightweight manifest for the current publication."""

    for _attempt in range(_MANIFEST_READ_ATTEMPTS):
        snapshot = _load_publication_snapshot(course_id=course_id, course_scope=course_scope)
        if snapshot is None:
            return KnowledgeDocsPublishedManifestResponse()
        try:
            chunks, updated_at = _load_snapshot_chunks(
                snapshot,
                course_id=course_id,
                course_scope=course_scope,
            )
        except PublishedDocumentStaleError:
            continue
        headings = [heading for chunk in chunks for heading in chunk.headings]
        return KnowledgeDocsPublishedManifestResponse(
            exists=True,
            publication_id=snapshot.publication_id,
            version_no=snapshot.version_no,
            updated_at=updated_at,
            chunks=[
                KnowledgeDocPublishedChunkSummary(
                    chunk_index=index,
                    chapter_index=chunk.chapter_index,
                    title=chunk.title,
                    heading_id=chunk.heading_id,
                    char_count=len(chunk.markdown),
                )
                for index, chunk in enumerate(chunks)
            ],
            headings=headings,
        )
    raise PublishedDocumentStaleError("published_document_changed_repeatedly")


def get_published_doc_chunk(
    *,
    course_id: str,
    course_scope: CourseStorageScope,
    publication_id: str,
    chunk_index: int,
) -> KnowledgeDocPublishedChunkResponse:
    """Return one chunk only if ``publication_id`` is still authoritative."""

    requested_publication = str(publication_id or "").strip()
    snapshot = _load_publication_snapshot(course_id=course_id, course_scope=course_scope)
    if snapshot is None or snapshot.publication_id != requested_publication:
        raise PublishedDocumentStaleError("published_document_is_not_current")
    if chunk_index < 0 or chunk_index >= len(snapshot.chapters):
        raise PublishedDocumentChunkNotFoundError("published_document_chunk_not_found")

    chunks, _updated_at = _load_snapshot_chunks(
        snapshot,
        course_id=course_id,
        course_scope=course_scope,
    )
    if chunk_index < 0 or chunk_index >= len(chunks):
        raise PublishedDocumentChunkNotFoundError("published_document_chunk_not_found")
    chunk = chunks[chunk_index]
    return KnowledgeDocPublishedChunkResponse(
        publication_id=snapshot.publication_id,
        version_no=snapshot.version_no,
        chunk_index=chunk_index,
        chapter_index=chunk.chapter_index,
        title=chunk.title,
        markdown=chunk.markdown,
        headings=list(chunk.headings),
    )


__all__ = [
    "PublishedDocumentBoundaryError",
    "PublishedDocumentChunkNotFoundError",
    "PublishedDocumentStaleError",
    "PublishedDocumentUnavailableError",
    "get_published_doc_chunk",
    "get_published_doc_manifest",
]
