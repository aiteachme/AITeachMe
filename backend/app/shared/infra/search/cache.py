"""Lightweight runtime caches for retrieval-heavy search flows."""

from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Awaitable, Callable, TypeVar

import structlog

from app.shared.infra.config import get_settings

logger = structlog.get_logger(__name__)

T = TypeVar("T")


@dataclass(slots=True)
class _CacheEntry:
    value: Any
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    hit_count: int = 0


class SearchRuntimeCache:
    """Small in-memory cache with TTL and inflight deduplication."""

    def __init__(self, *, namespace: str) -> None:
        self.namespace = str(namespace or "runtime").strip() or "runtime"
        self._entries: dict[str, _CacheEntry] = {}
        self._inflight: dict[str, asyncio.Task[Any]] = {}
        self._hits = 0
        self._shared_hits = 0
        self._misses = 0

    def _enabled(self) -> bool:
        return bool(get_settings().search_runtime_cache_enabled)

    def _ttl_s(self) -> int:
        return max(1, int(get_settings().search_runtime_cache_ttl_s))

    def _max_entries(self) -> int:
        return max(1, int(get_settings().search_runtime_cache_max_entries))

    def _is_expired(self, entry: _CacheEntry) -> bool:
        age_s = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
        return age_s > self._ttl_s()

    def _key_for_payload(self, payload: Any) -> str:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(f"{self.namespace}:{serialized}".encode("utf-8")).hexdigest()

    def _evict_oldest(self) -> None:
        if not self._entries:
            return
        oldest_key = min(self._entries, key=lambda key: self._entries[key].created_at)
        self._entries.pop(oldest_key, None)

    def _put(self, key: str, value: Any) -> None:
        while len(self._entries) >= self._max_entries():
            self._evict_oldest()
        self._entries[key] = _CacheEntry(value=copy.deepcopy(value))

    def clear(self) -> None:
        self._entries.clear()
        self._inflight.clear()

    async def get_or_compute(
        self,
        *,
        payload: Any,
        loader: Callable[[], Awaitable[T]],
    ) -> tuple[T, str]:
        if not self._enabled():
            return await loader(), "disabled"

        key = self._key_for_payload(payload)
        entry = self._entries.get(key)
        if entry is not None:
            if self._is_expired(entry):
                self._entries.pop(key, None)
            else:
                entry.hit_count += 1
                self._hits += 1
                logger.debug("search_runtime_cache_hit", namespace=self.namespace, key=key)
                return copy.deepcopy(entry.value), "hit"

        inflight = self._inflight.get(key)
        if inflight is not None:
            self._shared_hits += 1
            logger.debug("search_runtime_cache_shared", namespace=self.namespace, key=key)
            value = await asyncio.shield(inflight)
            return copy.deepcopy(value), "shared"

        task = asyncio.create_task(loader())
        self._inflight[key] = task
        try:
            value = await asyncio.shield(task)
            self._put(key, value)
            self._misses += 1
            logger.debug("search_runtime_cache_miss", namespace=self.namespace, key=key)
            return copy.deepcopy(value), "miss"
        finally:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)

    def get_stats(self) -> dict[str, int | float]:
        total = self._hits + self._shared_hits + self._misses
        return {
            "entries": len(self._entries),
            "inflight": len(self._inflight),
            "hits": self._hits,
            "shared_hits": self._shared_hits,
            "misses": self._misses,
            "hit_rate": round((self._hits + self._shared_hits) / total, 3) if total > 0 else 0.0,
        }


_RETRIEVER_RUNTIME_CACHE = SearchRuntimeCache(namespace="retriever")
_READER_RUNTIME_CACHE = SearchRuntimeCache(namespace="reader")
_COMPRESSION_RUNTIME_CACHE = SearchRuntimeCache(namespace="compression")


def get_retriever_runtime_cache() -> SearchRuntimeCache:
    return _RETRIEVER_RUNTIME_CACHE


def get_reader_runtime_cache() -> SearchRuntimeCache:
    return _READER_RUNTIME_CACHE


def get_compression_runtime_cache() -> SearchRuntimeCache:
    return _COMPRESSION_RUNTIME_CACHE


def reset_search_runtime_caches() -> None:
    _RETRIEVER_RUNTIME_CACHE.clear()
    _READER_RUNTIME_CACHE.clear()
    _COMPRESSION_RUNTIME_CACHE.clear()


__all__ = [
    "SearchRuntimeCache",
    "get_compression_runtime_cache",
    "get_reader_runtime_cache",
    "get_retriever_runtime_cache",
    "reset_search_runtime_caches",
]