"""SQLite 持久化记忆存储。

使用与主项目相同的 SQLite 数据库，通过原始 SQL 操作记忆表。
表结构在首次使用时自动创建。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import structlog

from app.teaching.memory.types import LearningLogEntry, MemoryEntry

logger = structlog.get_logger()


class SQLiteMemoryStore:
    """基于 SQLite 的记忆持久化存储。"""

    def __init__(self) -> None:
        self._initialized = False

    def _get_conn(self):
        """获取原始 SQLite 连接（绕过 SQLAlchemy ORM）。"""
        from app.core.database import get_engine

        engine = get_engine()
        return engine.raw_connection()

    def _ensure_tables(self) -> None:
        """首次使用时创建记忆相关表。"""
        if self._initialized:
            return

        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.executescript("""
                CREATE TABLE IF NOT EXISTS memory_entries (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    key         TEXT UNIQUE NOT NULL,
                    user_id     TEXT NOT NULL DEFAULT 'default',
                    content     TEXT NOT NULL,
                    tag         TEXT DEFAULT 'general',
                    importance  REAL DEFAULT 0.5,
                    created_at  TEXT NOT NULL,
                    updated_at  TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_memory_user
                    ON memory_entries(user_id);
                CREATE INDEX IF NOT EXISTS idx_memory_tag
                    ON memory_entries(user_id, tag);

                CREATE TABLE IF NOT EXISTS learning_logs (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     TEXT NOT NULL DEFAULT 'default',
                    event_type  TEXT NOT NULL,
                    subject     TEXT DEFAULT '',
                    summary     TEXT NOT NULL,
                    metadata    TEXT DEFAULT '{}',
                    created_at  TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_log_user_date
                    ON learning_logs(user_id, created_at);
            """)
            conn.commit()
            self._initialized = True
            logger.info("memory_tables_initialized")
        finally:
            conn.close()

    async def save(self, entry: MemoryEntry) -> None:
        """保存或更新一条记忆。"""
        self._ensure_tables()
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            now = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                """
                INSERT INTO memory_entries (key, user_id, content, tag, importance, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    content = excluded.content,
                    tag = excluded.tag,
                    importance = excluded.importance,
                    updated_at = excluded.updated_at
                """,
                (entry.key, entry.user_id, entry.content, entry.tag,
                 entry.importance, entry.created_at.isoformat(), now),
            )
            conn.commit()
        finally:
            conn.close()

    async def recall(
        self,
        query: str,
        *,
        user_id: str = "default",
        tag: str | None = None,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        """按关键词 + 重要度检索记忆。

        当前使用关键词匹配 + importance 排序。
        后续可升级为 sqlite-vec 语义检索。
        """
        self._ensure_tables()
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            sql = "SELECT key, user_id, content, tag, importance, created_at, updated_at FROM memory_entries WHERE user_id = ?"
            params: list = [user_id]

            if tag:
                sql += " AND tag = ?"
                params.append(tag)

            sql += " ORDER BY importance DESC, updated_at DESC LIMIT ?"
            params.append(top_k * 3)  # 取多一些做后续过滤

            cursor.execute(sql, params)
            rows = cursor.fetchall()

            # 关键词加权：匹配 query 的条目加分
            q = query.lower()
            entries = []
            for row in rows:
                key, uid, content, rtag, importance, created_str, updated_str = row
                # 关键词命中加分
                keyword_boost = 0.3 if q and q in content.lower() else 0.0
                entries.append((
                    importance + keyword_boost,
                    MemoryEntry(
                        key=key,
                        user_id=uid,
                        content=content,
                        tag=rtag,
                        importance=importance,
                        created_at=datetime.fromisoformat(created_str),
                        updated_at=datetime.fromisoformat(updated_str),
                    ),
                ))

            entries.sort(key=lambda x: x[0], reverse=True)
            return [e for _, e in entries[:top_k]]
        finally:
            conn.close()

    async def forget(self, key: str) -> bool:
        """删除一条记忆。"""
        self._ensure_tables()
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memory_entries WHERE key = ?", (key,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    async def get_all_by_user(
        self,
        user_id: str,
        *,
        tag: str | None = None,
    ) -> list[MemoryEntry]:
        """获取用户的所有记忆条目。"""
        self._ensure_tables()
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            sql = "SELECT key, user_id, content, tag, importance, created_at, updated_at FROM memory_entries WHERE user_id = ?"
            params: list = [user_id]
            if tag:
                sql += " AND tag = ?"
                params.append(tag)
            sql += " ORDER BY importance DESC, updated_at DESC"

            cursor.execute(sql, params)
            return [
                MemoryEntry(
                    key=row[0], user_id=row[1], content=row[2],
                    tag=row[3], importance=row[4],
                    created_at=datetime.fromisoformat(row[5]),
                    updated_at=datetime.fromisoformat(row[6]),
                )
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()

    async def save_learning_log(self, entry: LearningLogEntry) -> None:
        """保存学习日志。"""
        self._ensure_tables()
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO learning_logs (user_id, event_type, subject, summary, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (entry.user_id, entry.event_type, entry.subject,
                 entry.summary, json.dumps(entry.metadata, ensure_ascii=False),
                 entry.created_at.isoformat()),
            )
            conn.commit()
        finally:
            conn.close()

    async def get_learning_logs(
        self,
        user_id: str,
        *,
        days: int = 7,
    ) -> list[LearningLogEntry]:
        """获取最近 N 天的学习日志。"""
        self._ensure_tables()
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT user_id, event_type, subject, summary, metadata, created_at
                FROM learning_logs
                WHERE user_id = ? AND created_at >= datetime('now', ?)
                ORDER BY created_at DESC
                """,
                (user_id, f"-{days} days"),
            )
            return [
                LearningLogEntry(
                    user_id=row[0], event_type=row[1], subject=row[2],
                    summary=row[3],
                    metadata=json.loads(row[4]) if row[4] else {},
                    created_at=datetime.fromisoformat(row[5]),
                )
                for row in cursor.fetchall()
            ]
        finally:
            conn.close()


# ── 全局单例 ──────────────────────────────────────────────────

_store: SQLiteMemoryStore | None = None


def get_memory_store() -> SQLiteMemoryStore:
    """返回全局记忆存储单例。"""
    global _store
    if _store is None:
        _store = SQLiteMemoryStore()
    return _store
