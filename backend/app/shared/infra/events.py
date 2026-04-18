"""教学事件日志 — 五大引擎闭环回流的数据基础。

记录学习过程中的结构化事件，供 Profile 引擎消费。

对外使用::

    from app.shared.infra.events import emit_event, get_events

    # 记录事件
    await emit_event("exam_completed", user_id="u1", subject="math",
                     data={"score": 85, "weak_points": ["贝叶斯"]})

    # 查询事件
    events = await get_events(user_id="u1", event_type="exam_completed")
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import structlog

logger = structlog.get_logger()


# ── 事件类型常量 ──────────────────────────────────────────────

class EventType:
    """预定义事件类型。"""

    QUESTION_ASKED = "question_asked"       # 用户提问
    ANSWER_GIVEN = "answer_given"           # 系统回答
    CONCEPT_EXPLAINED = "concept_explained" # 概念讲解完成
    CONCEPT_MASTERED = "concept_mastered"   # 概念掌握确认
    MISTAKE_MADE = "mistake_made"           # 做错了题
    EXAM_COMPLETED = "exam_completed"       # 完成考试
    EXAM_GRADED = "exam_graded"            # 试卷批改完成
    REVIEW_STARTED = "review_started"       # 开始复习
    REVIEW_COMPLETED = "review_completed"   # 复习完成
    MATERIAL_UPLOADED = "material_uploaded" # 上传了资料
    SESSION_STARTED = "session_started"     # 学习会话开始
    SESSION_ENDED = "session_ended"         # 学习会话结束


@dataclass
class TeachingEvent:
    """教学事件。"""

    event_id: str
    event_type: str
    user_id: str
    subject: str
    data: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── 存储 ──────────────────────────────────────────────────────

class _EventStore:
    """SQLite 事件存储（内部）。"""

    def __init__(self) -> None:
        self._initialized = False

    def _get_conn(self):
        from app.shared.infra.database import get_engine
        return get_engine().raw_connection()

    def _ensure_table(self) -> None:
        if self._initialized:
            return
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS teaching_events (
                    id          TEXT PRIMARY KEY,
                    event_type  TEXT NOT NULL,
                    user_id     TEXT NOT NULL DEFAULT 'default',
                    subject     TEXT DEFAULT '',
                    data        TEXT DEFAULT '{}',
                    created_at  TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_user_type
                    ON teaching_events(user_id, event_type, created_at)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_subject
                    ON teaching_events(user_id, subject, created_at)
            """)
            conn.commit()
            self._initialized = True
        finally:
            conn.close()

    async def save(self, event: TeachingEvent) -> None:
        self._ensure_table()
        conn = self._get_conn()
        try:
            conn.execute(
                """INSERT INTO teaching_events (id, event_type, user_id, subject, data, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (event.event_id, event.event_type, event.user_id,
                 event.subject, json.dumps(event.data, ensure_ascii=False),
                 event.created_at.isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    async def query(
        self,
        *,
        user_id: str = "default",
        event_type: str | None = None,
        subject: str | None = None,
        days: int = 30,
        limit: int = 100,
    ) -> list[TeachingEvent]:
        self._ensure_table()
        conn = self._get_conn()
        try:
            sql = "SELECT id, event_type, user_id, subject, data, created_at FROM teaching_events WHERE user_id = ?"
            params: list = [user_id]

            if event_type:
                sql += " AND event_type = ?"
                params.append(event_type)
            if subject:
                sql += " AND subject = ?"
                params.append(subject)

            sql += " AND created_at >= datetime('now', ?) ORDER BY created_at DESC LIMIT ?"
            params.extend([f"-{days} days", limit])

            cursor = conn.execute(sql, params)
            return [
                TeachingEvent(
                    event_id=row[0], event_type=row[1], user_id=row[2],
                    subject=row[3],
                    data=json.loads(row[4]) if row[4] else {},
                    created_at=datetime.fromisoformat(row[5]),
                )
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    async def count(
        self,
        *,
        user_id: str = "default",
        event_type: str | None = None,
        days: int = 30,
    ) -> int:
        self._ensure_table()
        conn = self._get_conn()
        try:
            sql = "SELECT COUNT(*) FROM teaching_events WHERE user_id = ?"
            params: list = [user_id]
            if event_type:
                sql += " AND event_type = ?"
                params.append(event_type)
            sql += " AND created_at >= datetime('now', ?)"
            params.append(f"-{days} days")
            cursor = conn.execute(sql, params)
            return cursor.fetchone()[0]
        finally:
            conn.close()


_store: _EventStore | None = None

def _get_store() -> _EventStore:
    global _store
    if _store is None:
        _store = _EventStore()
    return _store


# ── 对外 API ─────────────────────────────────────────────────


async def emit_event(
    event_type: str,
    *,
    user_id: str = "default",
    subject: str = "",
    data: dict[str, Any] | None = None,
) -> str:
    """发射一个教学事件。

    Args:
        event_type: 事件类型（使用 EventType 常量或自定义字符串）。
        user_id: 用户标识。
        subject: 学科标识。
        data: 事件附加数据。

    Returns:
        事件 ID。

    Example::

        await emit_event(EventType.EXAM_COMPLETED, user_id="u1",
                         subject="math", data={"score": 85})
    """

    event = TeachingEvent(
        event_id=uuid4().hex[:16],
        event_type=event_type,
        user_id=user_id,
        subject=subject,
        data=data or {},
    )
    await _get_store().save(event)
    logger.info("event_emitted", event_type=event_type,
                user_id=user_id, subject=subject)
    return event.event_id


async def get_events(
    *,
    user_id: str = "default",
    event_type: str | None = None,
    subject: str | None = None,
    days: int = 30,
    limit: int = 100,
) -> list[TeachingEvent]:
    """查询教学事件。

    Args:
        user_id: 用户标识。
        event_type: 可选过滤事件类型。
        subject: 可选过滤学科。
        days: 回溯天数。
        limit: 最大返回数量。

    Returns:
        事件列表（按时间倒序）。
    """

    return await _get_store().query(
        user_id=user_id, event_type=event_type,
        subject=subject, days=days, limit=limit,
    )


async def count_events(
    *,
    user_id: str = "default",
    event_type: str | None = None,
    days: int = 30,
) -> int:
    """统计事件数量。"""

    return await _get_store().count(
        user_id=user_id, event_type=event_type, days=days,
    )
