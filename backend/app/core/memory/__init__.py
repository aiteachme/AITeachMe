"""多层记忆系统 — 对外极简 API。

外部使用方式::

    from app.core.memory import remember, recall, forget, get_user_profile

    # 记住
    await remember("用户偏好类比教学", user_id="u1", tag="preference")

    # 回忆
    entries = await recall("类比", user_id="u1")

    # 获取画像
    profile = await get_user_profile("u1")
    system_msg = profile.to_system_message()
"""

from app.core.memory.api import (
    forget,
    get_learning_log,
    get_user_profile,
    recall,
    remember,
)
from app.core.memory.profile import UserProfile
from app.core.memory.types import LearningLogEntry, MemoryEntry, MemoryTag

__all__ = [
    "forget",
    "get_learning_log",
    "get_user_profile",
    "recall",
    "remember",
    "LearningLogEntry",
    "MemoryEntry",
    "MemoryTag",
    "UserProfile",
]
