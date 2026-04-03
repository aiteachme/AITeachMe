"""记忆系统对外 API — 外部模块的唯一入口。

所有函数都是顶层 async 函数，一行 import + 一次调用即可。
内部自动管理存储实例、表创建等细节。
"""

from __future__ import annotations

from uuid import uuid4

import structlog

from app.shared.infra.memory.profile import UserProfile
from app.shared.infra.memory.store import get_memory_store
from app.shared.infra.memory.types import LearningLogEntry, MemoryEntry, MemoryTag

logger = structlog.get_logger()


async def remember(
    content: str,
    *,
    user_id: str = "default",
    tag: str = MemoryTag.GENERAL,
    importance: float = 0.5,
    key: str | None = None,
) -> str:
    """记住一条信息。

    Args:
        content: 要记住的内容（自然语言）。
        user_id: 用户标识（默认 "default"）。
        tag: 记忆标签（preference / strength / weakness / background 等）。
        importance: 重要度 0.0 ~ 1.0，越高越容易被回忆。
        key: 可选的唯一键。不传则自动生成。相同 key 会覆盖旧记忆。

    Returns:
        记忆的 key。

    Example::

        from app.shared.infra.memory import remember
        await remember("用户线性代数较弱", user_id="u1", tag="weakness")
    """

    entry_key = key or uuid4().hex[:12]
    entry = MemoryEntry(
        key=entry_key,
        user_id=user_id,
        content=content,
        tag=tag,
        importance=importance,
    )
    store = get_memory_store()
    await store.save(entry)
    logger.debug("memory_saved", key=entry_key, user_id=user_id, tag=tag)
    return entry_key


async def recall(
    query: str,
    *,
    user_id: str = "default",
    top_k: int = 5,
    tag: str | None = None,
) -> list[MemoryEntry]:
    """按语义相关性回忆信息。

    Args:
        query: 查询内容（自然语言）。
        user_id: 用户标识。
        top_k: 返回最多几条。
        tag: 可选的标签过滤。

    Returns:
        按相关性排序的记忆列表。

    Example::

        from app.shared.infra.memory import recall
        entries = await recall("类比教学", user_id="u1")
        for e in entries:
            print(e.content)
    """

    store = get_memory_store()
    return await store.recall(query, user_id=user_id, tag=tag, top_k=top_k)


async def forget(key: str) -> bool:
    """忘记一条记忆。

    Args:
        key: 记忆的唯一键。

    Returns:
        是否成功删除。
    """

    store = get_memory_store()
    result = await store.forget(key)
    if result:
        logger.debug("memory_forgotten", key=key)
    return result


async def get_user_profile(user_id: str = "default") -> UserProfile:
    """获取用户画像。

    内部自动汇总该用户的所有记忆条目，按 tag 分类构建画像。

    Args:
        user_id: 用户标识。

    Returns:
        UserProfile 对象 — 可直接调用 ``.to_system_message()``
        注入 LLM 上下文。

    Example::

        from app.shared.infra.memory import get_user_profile
        profile = await get_user_profile("u1")
        # 注入到 LLM 上下文
        messages = [profile.to_system_message()] + other_messages
    """

    store = get_memory_store()
    memories = await store.get_all_by_user(user_id)
    return UserProfile.build_from_memories(user_id, memories)


async def get_learning_log(
    user_id: str = "default",
    *,
    days: int = 7,
) -> list[LearningLogEntry]:
    """获取最近 N 天的学习日志。

    Args:
        user_id: 用户标识。
        days: 回溯天数（默认 7 天）。

    Returns:
        学习日志条目列表（按时间倒序）。
    """

    store = get_memory_store()
    return await store.get_learning_logs(user_id, days=days)


async def log_learning_event(
    user_id: str,
    *,
    event_type: str,
    subject: str = "",
    summary: str,
    metadata: dict | None = None,
) -> None:
    """记录一次学习事件到日志。

    Args:
        user_id: 用户标识。
        event_type: 事件类型（"chat" / "exam" / "review" / "study"）。
        subject: 学科标识。
        summary: 事件摘要。
        metadata: 附加元数据。

    Example::

        from app.shared.infra.memory.api import log_learning_event
        await log_learning_event("u1", event_type="exam", subject="math",
                                 summary="完成概率论测验，得分 85")
    """

    entry = LearningLogEntry(
        user_id=user_id,
        event_type=event_type,
        subject=subject,
        summary=summary,
        metadata=metadata or {},
    )
    store = get_memory_store()
    await store.save_learning_log(entry)
    logger.debug("learning_event_logged", user_id=user_id, event_type=event_type)
