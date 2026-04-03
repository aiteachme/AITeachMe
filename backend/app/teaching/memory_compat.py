"""多层记忆管理。

支持短期（会话内）、长期（跨会话）、语义记忆。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

import structlog

logger = structlog.get_logger()


# ── 类型定义 ──────────────────────────────────────────────────


class MemoryType(str, Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    SEMANTIC = "semantic"


@dataclass
class MemoryEntry:
    key: str
    content: str
    memory_type: MemoryType
    importance: float = 0.5
    subject: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── 存储接口 ──────────────────────────────────────────────────


class MemoryStore(ABC):
    @abstractmethod
    async def save(self, entry: MemoryEntry) -> None: ...

    @abstractmethod
    async def recall(self, query: str, *, memory_type: MemoryType | None = None, top_k: int = 5) -> list[MemoryEntry]: ...

    @abstractmethod
    async def forget(self, key: str) -> bool: ...


class InMemoryStore(MemoryStore):
    """基于内存的实现（开发用，后续可替换为 SQLite）。"""

    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}

    async def save(self, entry: MemoryEntry) -> None:
        self._entries[entry.key] = entry

    async def recall(self, query: str, *, memory_type: MemoryType | None = None, top_k: int = 5) -> list[MemoryEntry]:
        candidates = list(self._entries.values())
        if memory_type:
            candidates = [e for e in candidates if e.memory_type == memory_type]
        # 简单关键词匹配 + 按重要度排序
        q = query.lower()
        scored = [(e.importance + (0.3 if q in e.content.lower() else 0), e) for e in candidates]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:top_k]]

    async def forget(self, key: str) -> bool:
        return self._entries.pop(key, None) is not None


# ── 管理器 ────────────────────────────────────────────────────


class MemoryManager:
    """统一记忆管理入口。"""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store or InMemoryStore()

    async def remember(self, content: str, *, memory_type: MemoryType = MemoryType.SHORT_TERM,
                       key: str | None = None, importance: float = 0.5) -> str:
        key = key or uuid4().hex[:12]
        await self._store.save(MemoryEntry(key=key, content=content, memory_type=memory_type, importance=importance))
        return key

    async def recall(self, query: str, *, memory_type: MemoryType | None = None, top_k: int = 5) -> list[MemoryEntry]:
        return await self._store.recall(query, memory_type=memory_type, top_k=top_k)

    async def forget(self, key: str) -> bool:
        return await self._store.forget(key)
