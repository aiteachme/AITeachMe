"""Database-portable persistent memory store."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.models.memory import LearningLogRecord, MemoryRecord
from app.shared.infra.database import managed_session
from app.shared.infra.memory.types import LearningLogEntry, MemoryEntry
from app.utils.time import utcnow


def _to_memory_entry(record: MemoryRecord) -> MemoryEntry:
    return MemoryEntry(
        key=record.key,
        user_id=record.user_id,
        content=record.content,
        tag=record.tag,
        importance=record.importance,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _to_learning_log(record: LearningLogRecord) -> LearningLogEntry:
    return LearningLogEntry(
        user_id=record.user_id,
        event_type=record.event_type,
        course_id=record.course_id,
        summary=record.summary,
        metadata=dict(record.metadata_json or {}),
        created_at=record.created_at,
    )


class DatabaseMemoryStore:
    """Memory repository backed by the configured SQLite/PostgreSQL engine."""

    async def save(self, entry: MemoryEntry) -> None:
        now = utcnow()
        with managed_session() as session:
            record = session.exec(
                select(MemoryRecord).where(MemoryRecord.key == entry.key)
            ).first()
            if record is None:
                record = MemoryRecord(
                    key=entry.key,
                    user_id=entry.user_id,
                    content=entry.content,
                    tag=str(entry.tag),
                    importance=entry.importance,
                    created_at=entry.created_at,
                    updated_at=now,
                )
            else:
                record.user_id = entry.user_id
                record.content = entry.content
                record.tag = str(entry.tag)
                record.importance = entry.importance
                record.updated_at = now
            session.add(record)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                current = session.exec(
                    select(MemoryRecord).where(MemoryRecord.key == entry.key)
                ).first()
                if current is None:
                    raise
                current.user_id = entry.user_id
                current.content = entry.content
                current.tag = str(entry.tag)
                current.importance = entry.importance
                current.updated_at = now
                session.add(current)
                session.commit()

    async def recall(
        self,
        query: str,
        *,
        user_id: str = "default",
        tag: str | None = None,
        top_k: int = 5,
    ) -> list[MemoryEntry]:
        limit = max(1, top_k)
        with managed_session() as session:
            statement = select(MemoryRecord).where(MemoryRecord.user_id == user_id)
            if tag:
                statement = statement.where(MemoryRecord.tag == tag)
            records = list(
                session.exec(
                    statement.order_by(
                        MemoryRecord.importance.desc(),
                        MemoryRecord.updated_at.desc(),
                    ).limit(limit * 3)
                ).all()
            )

        normalized_query = query.lower()
        ranked = [
            (
                record.importance
                + (0.3 if normalized_query and normalized_query in record.content.lower() else 0.0),
                _to_memory_entry(record),
            )
            for record in records
        ]
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in ranked[:limit]]

    async def forget(self, key: str) -> bool:
        with managed_session() as session:
            result = session.exec(delete(MemoryRecord).where(MemoryRecord.key == key))
            session.commit()
            return bool(result.rowcount)

    async def get_all_by_user(
        self,
        user_id: str,
        *,
        tag: str | None = None,
    ) -> list[MemoryEntry]:
        with managed_session() as session:
            statement = select(MemoryRecord).where(MemoryRecord.user_id == user_id)
            if tag:
                statement = statement.where(MemoryRecord.tag == tag)
            records = session.exec(
                statement.order_by(MemoryRecord.importance.desc(), MemoryRecord.updated_at.desc())
            ).all()
            return [_to_memory_entry(record) for record in records]

    async def save_learning_log(self, entry: LearningLogEntry) -> None:
        with managed_session() as session:
            session.add(
                LearningLogRecord(
                    user_id=entry.user_id,
                    event_type=entry.event_type,
                    course_id=entry.course_id,
                    summary=entry.summary,
                    metadata_json=dict(entry.metadata),
                    created_at=entry.created_at,
                )
            )
            session.commit()

    async def get_learning_logs(
        self,
        user_id: str,
        *,
        days: int = 7,
    ) -> list[LearningLogEntry]:
        cutoff = utcnow() - timedelta(days=max(0, days))
        with managed_session() as session:
            records = session.exec(
                select(LearningLogRecord)
                .where(
                    LearningLogRecord.user_id == user_id,
                    LearningLogRecord.created_at >= cutoff,
                )
                .order_by(LearningLogRecord.created_at.desc())
            ).all()
            return [_to_learning_log(record) for record in records]


# Compatibility alias for callers importing the former concrete class.
SQLiteMemoryStore = DatabaseMemoryStore

_store: DatabaseMemoryStore | None = None


def get_memory_store() -> DatabaseMemoryStore:
    global _store
    if _store is None:
        _store = DatabaseMemoryStore()
    return _store
