"""Stable identities shared by retrieval materialization and course migration."""

from __future__ import annotations

import hashlib


def published_knowledge_docs_source_id(course_id: str) -> str:
    normalized = str(course_id or "").strip()
    return "published-knowledge-docs-" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def build_digest_chunk_uid(*, file_id: str, chunk_index: int, title: str, content: str) -> str:
    uid_hash = hashlib.md5(
        f"{file_id}:{chunk_index}:{title}:{content.strip()}".encode("utf-8")
    ).hexdigest()[:10]
    return f"rf_{file_id}_sec_{chunk_index:03d}_{uid_hash}"
