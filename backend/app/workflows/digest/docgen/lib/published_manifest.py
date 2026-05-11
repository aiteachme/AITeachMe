"""Helpers for restoring published knowledge-document manifests."""

from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, select

from app.models.knowledge_doc import KnowledgeDocument
from app.shared.infra.knowledge.build_store import (
    KnowledgeDocsManifest,
    read_knowledge_manifest,
    write_knowledge_manifest,
)
from app.shared.infra.storage import CourseStorageScope
from app.utils.time import ensure_utc_datetime, utcnow


def ensure_published_knowledge_manifest(
    session: Session,
    *,
    course_id: str,
    course_scope: CourseStorageScope,
) -> KnowledgeDocsManifest | None:
    """Return the published-doc manifest, rebuilding it from DB rows when absent."""

    manifest = read_knowledge_manifest(course_id, course_scope=course_scope)
    if manifest is not None:
        return manifest

    manifest = build_manifest_from_published_docs(session, course_id=course_id)
    if manifest is None:
        return None

    write_knowledge_manifest(course_id, manifest, course_scope=course_scope)
    return manifest


def build_manifest_from_published_docs(
    session: Session,
    *,
    course_id: str,
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
    return KnowledgeDocsManifest(
        updated_at=max(timestamps) if timestamps else utcnow(),
        version_no=max(int(doc.version_no or doc.version or 1) for doc in docs),
        source_file_ids=source_file_ids,
        chapter_count=len(chapter_docs),
        chapter_titles=[doc.title for doc in chapter_docs if doc.title],
    )


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(str(value or "[]"))
    except Exception:
        return []
    return parsed if isinstance(parsed, list) else []
