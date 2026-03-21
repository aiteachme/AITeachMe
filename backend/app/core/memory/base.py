"""记忆存储抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.memory.types import MemoryEntry, MemoryType


class MemoryStore(ABC):
    """记忆存储抽象基类。

    具体实现可以基于 SQLite、Redis、向量数据库等。
    """

    @abstractmethod
    async def save(self, entry: MemoryEntry) -> None:
        """保存一条记忆。"""

    @abstractmethod
    async def recall(
        self,
        query: str,
        *,
        memory_type: MemoryType | None = None,
        subject: str | None = None,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        """检索与查询相关的记忆。"""

    @abstractmethod
    async def forget(self, key: str) -> bool:
        """删除指定记忆。"""

    @abstractmethod
    async def clear(self, *, memory_type: MemoryType | None = None) -> int:
        """清空记忆，返回删除条数。"""
