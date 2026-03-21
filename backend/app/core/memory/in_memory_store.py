"""基于内存的记忆存储实现（开发阶段使用）。"""

from __future__ import annotations

from collections import defaultdict

from app.core.memory.base import MemoryStore
from app.core.memory.types import MemoryEntry, MemoryType


class InMemoryStore(MemoryStore):
    """基于内存字典的简单记忆存储。

    适合开发测试，后续可替换为 SQLite 实现。
    """

    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}
        self._by_type: dict[MemoryType, list[str]] = defaultdict(list)

    async def save(self, entry: MemoryEntry) -> None:
        self._entries[entry.key] = entry
        if entry.key not in self._by_type[entry.memory_type]:
            self._by_type[entry.memory_type].append(entry.key)

    async def recall(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        subject: str | None = None,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        candidates = list(self._entries.values())

        if memory_type is not None:
            candidates = [e for e in candidates if e.memory_type == memory_type]
        if subject is not None:
            candidates = [e for e in candidates if e.subject == subject]

        # 简单关键词匹配 + 按重要度排序
        query_lower = query.lower()
        scored = []
        for entry in candidates:
            score = entry.importance
            if query_lower in entry.content.lower():
                score += 0.3
            if query_lower in entry.key.lower():
                score += 0.2
            scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    async def forget(self, key: str) -> bool:
        entry = self._entries.pop(key, None)
        if entry is not None:
            keys = self._by_type.get(entry.memory_type, [])
            if key in keys:
                keys.remove(key)
            return True
        return False

    async def clear(self, *, memory_type: MemoryType | None = None) -> int:
        if memory_type is None:
            count = len(self._entries)
            self._entries.clear()
            self._by_type.clear()
            return count

        keys = self._by_type.pop(memory_type, [])
        for key in keys:
            self._entries.pop(key, None)
        return len(keys)
