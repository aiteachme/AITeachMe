"""记忆系统的数据类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MemoryTag(str, Enum):
    """记忆标签 — 用于分类和过滤。"""

    PREFERENCE = "preference"     # 学习偏好（"喜欢类比解释"）
    STRENGTH = "strength"         # 擅长领域（"Python 基础扎实"）
    WEAKNESS = "weakness"         # 薄弱领域（"概率论贝叶斯不熟"）
    BACKGROUND = "background"     # 用户背景（"大三计算机专业"）
    NOTE = "note"                 # 学习笔记
    INSIGHT = "insight"           # 教学过程中的洞察
    GENERAL = "general"           # 通用记忆


@dataclass
class MemoryEntry:
    """记忆条目。"""

    key: str
    user_id: str
    content: str
    tag: str = MemoryTag.GENERAL
    importance: float = 0.5
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class LearningLogEntry:
    """学习日志条目。"""

    user_id: str
    event_type: str         # "chat" | "exam" | "review" | "study"
    subject: str
    summary: str
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
