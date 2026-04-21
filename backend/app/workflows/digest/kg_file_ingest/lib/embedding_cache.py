"""Persistent embedding cache helpers for digest knowledge graph resolution."""

from __future__ import annotations

import hashlib

from app.shared.infra.storage import (
    get_content_store,
    resolve_subject_storage_scope,
    run_store_sync,
)


def compute_embedding_text_hash(text: str) -> str:
    """Return a stable hash for embedding input text."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_subject_embedding_cache(subject: str) -> dict[str, dict[str, object]]:
    """Load the persisted node embedding cache for one subject."""

    cs = get_content_store()
    key = resolve_subject_storage_scope(subject).embedding_cache_key()
    payload = run_store_sync(cs.read_json_raw, key)
    if not isinstance(payload, dict):
        return {}
    return {
        str(k): v
        for k, v in payload.items()
        if isinstance(v, dict)
    }


def write_subject_embedding_cache(
    subject: str,
    cache_payload: dict[str, dict[str, object]],
) -> str:
    """Persist the node embedding cache for one subject."""

    cs = get_content_store()
    key = resolve_subject_storage_scope(subject).embedding_cache_key()
    run_store_sync(cs.write_json_raw, key, cache_payload)
    return key


__all__ = [
    "compute_embedding_text_hash",
    "load_subject_embedding_cache",
    "write_subject_embedding_cache",
]
