"""记忆类型与条目定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MemoryType(str, Enum):
    """记忆类型。"""

    SHORT_TERM = "short_term"     # 当前会话 / 任务内
    LONG_TERM = "long_term"       # 跨会话持久化
    SEMANTIC = "semantic"         # 基于语义相似度的知识


@dataclass
class MemoryEntry:
    """一条记忆条目。"""

    key: str
    content: str
    memory_type: MemoryType
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    importance: float = 0.5       # 0.0 ~ 1.0 重要度
    subject: str | None = None    # 关联学科
