"""Stable candidate identity helpers for typed digest resolution."""

from __future__ import annotations

import re
from typing import Protocol

from app.utils.kg_helpers import normalize_name
from app.models.kg_taxonomy import (
    SECONDARY_KNOWLEDGE_UNIT_TYPES,
    normalize_knowledge_unit_type,
)

_TOKEN_RE = re.compile(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{1,}")


class CandidateLike(Protocol):
    candidate_id: str
    node_type: str
    name: str
    taxonomy_hint: str
    parent_entity_name: str | None


def normalize_scope_name(value: str | None) -> str:
    """Normalize a local semantic scope such as parent/topic bucket."""

    return normalize_name(value or "")


def build_candidate_name_key(
    node_type: str,
    name: str,
    *,
    scope: str | None = None,
) -> str:
    """Build a typed lookup key for name-based candidate resolution."""

    return f"{node_type}::{normalize_name(name)}::{normalize_scope_name(scope)}"


def build_candidate_stable_id(
    *,
    node_type: str,
    name: str,
    local_index: int,
    scope: str | None = None,
) -> str:
    """Build a per-chunk stable candidate id."""

    return f"{node_type}::{normalize_name(name)}::{normalize_scope_name(scope)}::{local_index}"


def candidate_scope(candidate: CandidateLike) -> str:
    """Return the strongest available local scope for a candidate."""

    return normalize_scope_name(candidate.parent_entity_name or candidate.taxonomy_hint)


def candidate_lookup_keys(candidate: CandidateLike) -> list[str]:
    """Return candidate ids plus typed fallback lookup keys."""

    keys: list[str] = []
    if candidate.candidate_id:
        keys.append(candidate.candidate_id)
    scope = candidate_scope(candidate)
    keys.append(
        build_candidate_name_key(
            candidate.node_type,
            candidate.name,
            scope=scope,
        )
    )
    if scope:
        keys.append(
            build_candidate_name_key(
                candidate.node_type,
                candidate.name,
                scope=None,
            )
        )
    return list(dict.fromkeys(key for key in keys if key))


def bucket_scope(candidate: CandidateLike) -> str:
    """Return the bucket scope used for clustering/filtering."""

    if normalize_knowledge_unit_type(candidate.node_type) in SECONDARY_KNOWLEDGE_UNIT_TYPES:
        return candidate_scope(candidate)
    return normalize_scope_name(candidate.taxonomy_hint)


def token_bucket(name: str) -> str:
    """Create a cheap token bucket to avoid full O(n²) comparisons."""

    normalized = normalize_name(name)
    if not normalized:
        return ""
    tokens = [normalize_name(token) for token in _TOKEN_RE.findall(name) if normalize_name(token)]
    if tokens:
        return "::".join(tokens[:2])
    return normalized[:12]


__all__ = [
    "bucket_scope",
    "build_candidate_name_key",
    "build_candidate_stable_id",
    "candidate_lookup_keys",
    "candidate_scope",
    "normalize_scope_name",
    "token_bucket",
]
