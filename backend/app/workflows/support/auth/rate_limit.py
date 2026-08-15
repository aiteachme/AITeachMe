"""Database-backed authentication rate limiting for multi-instance cloud deployments."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from app.models import AuthRateLimitBucket
from app.shared.infra.exceptions import AITeachMeError
from app.utils.time import utcnow


def _window_start(now: datetime, seconds: int) -> datetime:
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % seconds), tz=timezone.utc)


def consume_auth_rate_limit(
    session: Session,
    *,
    scope: str,
    identity: str,
    limit: int,
    window_seconds: int,
) -> None:
    now = utcnow()
    window = _window_start(now, max(1, window_seconds))
    bucket_key = hashlib.sha256(f"{scope}:{identity}".encode("utf-8")).hexdigest()
    values = {
        "id": f"arb_{hashlib.sha256(f'{bucket_key}:{window.isoformat()}'.encode('utf-8')).hexdigest()}",
        "bucket_key": bucket_key,
        "window_started_at": window,
        "count": 1,
        "expires_at": window + timedelta(seconds=window_seconds * 2),
        "updated_at": now,
    }
    table = AuthRateLimitBucket.__table__
    dialect = session.get_bind().dialect.name
    insert = pg_insert(table) if dialect == "postgresql" else sqlite_insert(table)
    statement = insert.values(**values).on_conflict_do_update(
        index_elements=[table.c.bucket_key, table.c.window_started_at],
        set_={"count": table.c.count + 1, "updated_at": now},
        where=table.c.count < max(1, limit),
    ).returning(table.c.count)
    consumed = session.exec(statement).first()
    session.commit()
    if consumed is None:
        raise AITeachMeError(
            detail="请求过于频繁，请稍后重试。",
            status_code=429,
            error_code="AUTH_RATE_LIMITED",
            data={"retry_after_s": window_seconds},
        )
