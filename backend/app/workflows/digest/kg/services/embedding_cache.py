"""Persistent embedding cache helpers for digest KG resolution."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.utils.path_helpers import build_knowledge_node_embedding_cache_path


def compute_embedding_text_hash(text: str) -> str:
    """Return a stable hash for embedding input text."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_subject_embedding_cache(subject: str) -> dict[str, dict[str, object]]:
    """Load the persisted node embedding cache for one subject."""

    path = build_knowledge_node_embedding_cache_path(subject)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        str(key): value
        for key, value in payload.items()
        if isinstance(value, dict)
    }


def write_subject_embedding_cache(
    subject: str,
    cache_payload: dict[str, dict[str, object]],
) -> Path:
    """Persist the node embedding cache for one subject."""

    path = build_knowledge_node_embedding_cache_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


__all__ = [
    "compute_embedding_text_hash",
    "load_subject_embedding_cache",
    "write_subject_embedding_cache",
]
