"""记忆管理器：编排多层记忆的统一入口。"""

from __future__ import annotations

from uuid import uuid4

import structlog

from app.core.memory.base import MemoryStore
from app.core.memory.in_memory_store import InMemoryStore
from app.core.memory.types import MemoryEntry, MemoryType

logger = structlog.get_logger()


class MemoryManager:
    """统一记忆管理器，编排短期、长期和语义记忆。"""

    def __init__(self, store: MemoryStore | None = None) -> None:
        self._store = store or InMemoryStore()

    async def remember(
        self,
        content: str,
        *,
        memory_type: MemoryType = MemoryType.SHORT_TERM,
        key: str | None = None,
        subject: str | None = None,
        importance: float = 0.5,
        metadata: dict | None = None,
    ) -> str:
        """保存一条记忆，返回 key。"""

        key = key or uuid4().hex[:12]
        entry = MemoryEntry(
            key=key,
            content=content,
            memory_type=memory_type,
            subject=subject,
            importance=importance,
            metadata=metadata or {},
        )
        await self._store.save(entry)
        logger.debug("memory_saved", key=key, memory_type=memory_type.value)
        return key

    async def recall(
        self,
        query: str,
        *,
        types: list[MemoryType] | None = None,
        subject: str | None = None,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        """检索相关记忆。"""

        if types is None:
            return await self._store.recall(query, subject=subject, top_k=top_k)

        # 跨类型检索并合并
        all_results: list[MemoryEntry] = []
        for memory_type in types:
            results = await self._store.recall(
                query,
                memory_type=memory_type,
                subject=subject,
                top_k=top_k,
            )
            all_results.extend(results)

        # 按重要度排序后截断
        all_results.sort(key=lambda e: e.importance, reverse=True)
        return all_results[:top_k]

    async def forget(self, key: str) -> bool:
        """删除一条记忆。"""

        return await self._store.forget(key)

    async def clear(self, *, memory_type: MemoryType | None = None) -> int:
        """清空记忆。"""

        count = await self._store.clear(memory_type=memory_type)
        logger.info("memory_cleared", memory_type=memory_type, deleted=count)
        return count

    async def summarize_short_term(self) -> str:
        """压缩短期记忆为摘要文本（防止上下文膨胀）。"""

        entries = await self._store.recall(
            "",
            memory_type=MemoryType.SHORT_TERM,
            top_k=50,
        )
        if not entries:
            return ""

        lines = [e.content for e in entries]
        return "\n".join(lines[-20:])  # 保留最近 20 条
