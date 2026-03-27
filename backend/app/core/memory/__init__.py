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

    # LEARNER.md 学习者档案
    from app.core.memory import read_learner_doc, update_learner_section
    doc = await read_learner_doc("u1")
    await update_learner_section("u1", "薄弱领域", "- 线性代数：特征值")
"""

from app.core.memory.api import (
    forget,
    get_learning_log,
    get_user_profile,
    recall,
    remember,
)
from app.core.memory.learner_doc import (
    append_to_learner_section,
    get_learner_doc_path,
    load_doc_to_context,
    read_learner_doc,
    read_learner_section,
    sync_profile_to_doc,
    update_learner_section,
    write_learner_doc,
)
from app.core.memory.profile import UserProfile
from app.core.memory.types import LearningLogEntry, MemoryEntry, MemoryTag

__all__ = [
    # 核心 API
    "forget",
    "get_learning_log",
    "get_user_profile",
    "recall",
    "remember",
    # LEARNER.md
    "append_to_learner_section",
    "get_learner_doc_path",
    "load_doc_to_context",
    "read_learner_doc",
    "read_learner_section",
    "sync_profile_to_doc",
    "update_learner_section",
    "write_learner_doc",
    # 数据类型
    "LearningLogEntry",
    "MemoryEntry",
    "MemoryTag",
    "UserProfile",
]

