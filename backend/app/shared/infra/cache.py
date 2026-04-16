"""语义缓存：基于语义相似度的 LLM 响应缓存。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import md5

import structlog

from app.shared.infra.settings import get_settings

logger = structlog.get_logger()


@dataclass
class CacheEntry:
    """缓存条目。"""

    query_hash: str
    query_text: str
    response: str
    model: str
    task_type: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    hit_count: int = 0


class SemanticCache:
    """基于语义相似度的 LLM 响应缓存。

    当前实现使用精确哈希匹配（Phase 1）。
    后续可升级为基于 embedding 相似度的语义匹配。
    """

    def __init__(
        self,
        *,
        ttl_s: int | None = None,
        max_entries: int | None = None,
    ) -> None:
        settings = get_settings()
        self._ttl_s = ttl_s or settings.cache.ttl_s
        self._max_entries = max_entries or settings.cache.max_entries
        self._cache: dict[str, CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _hash(text: str) -> str:
        return md5(text.encode("utf-8")).hexdigest()

    def get(self, query: str, *, model: str = "", task_type: str = "") -> str | None:
        """查找缓存。"""

        settings = get_settings()
        if not settings.cache.enabled:
            return None

        key = self._hash(f"{model}:{task_type}:{query}")
        entry = self._cache.get(key)

        if entry is None:
            self._misses += 1
            return None

        # 检查 TTL
        age = (datetime.now(timezone.utc) - entry.created_at).total_seconds()
        if age > self._ttl_s:
            del self._cache[key]
            self._misses += 1
            return None

        entry.hit_count += 1
        self._hits += 1
        logger.debug("cache_hit", query_len=len(query), hit_count=entry.hit_count)
        return entry.response

    def put(
        self,
        query: str,
        response: str,
        *,
        model: str = "",
        task_type: str = "",
    ) -> None:
        """存入缓存。"""

        settings = get_settings()
        if not settings.cache.enabled:
            return

        # 如果超过容量上限，清理最旧的条目
        if len(self._cache) >= self._max_entries:
            self._evict_oldest()

        key = self._hash(f"{model}:{task_type}:{query}")
        self._cache[key] = CacheEntry(
            query_hash=key,
            query_text=query[:200],
            response=response,
            model=model,
            task_type=task_type,
        )

    def _evict_oldest(self) -> None:
        """淘汰最旧的缓存条目。"""

        if not self._cache:
            return
        oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
        del self._cache[oldest_key]

    def invalidate(self, older_than: datetime | None = None) -> int:
        """清理过期缓存。"""

        if older_than is None:
            count = len(self._cache)
            self._cache.clear()
            return count

        expired_keys = [
            k for k, v in self._cache.items()
            if v.created_at < older_than
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)

    def get_stats(self) -> dict:
        """返回缓存统计。"""

        total = self._hits + self._misses
        return {
            "entries": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
        }


# ── 全局单例 ──────────────────────────────────────────────────

_cache: SemanticCache | None = None


def get_cache() -> SemanticCache:
    """返回全局缓存单例。"""

    global _cache
    if _cache is None:
        _cache = SemanticCache()
    return _cache
