"""Bounded cleanup for expired authentication records."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import sqlalchemy as sa
import structlog
from sqlmodel import Session, select

from app.models import AuthRateLimitBucket, AuthSession, OAuthFlow
from app.shared.infra.database import managed_session
from app.utils.time import utcnow

logger = structlog.get_logger(__name__)

AUTH_HOUSEKEEPING_INTERVAL_SECONDS = 3600
OAUTH_CONSUMED_RETENTION = timedelta(days=1)
REVOKED_SESSION_RETENTION = timedelta(days=7)


def _delete_ids(session: Session, model: type, ids: list[str]) -> int:
    if not ids:
        return 0
    session.exec(
        sa.delete(model)
        .where(model.id.in_(ids))
        .execution_options(synchronize_session=False)
    )
    return len(ids)


def _cleanup_expired_auth_records(
    session: Session,
    *,
    limit: int,
) -> int:
    now = utcnow()
    batch_size = max(1, int(limit))
    rate_limit_ids = list(
        session.exec(
            select(AuthRateLimitBucket.id)
            .where(AuthRateLimitBucket.expires_at <= now)
            .order_by(AuthRateLimitBucket.expires_at.asc())
            .limit(batch_size)
        ).all()
    )
    oauth_flow_ids = list(
        session.exec(
            select(OAuthFlow.id)
            .where(
                sa.or_(
                    OAuthFlow.expires_at <= now,
                    OAuthFlow.consumed_at <= now - OAUTH_CONSUMED_RETENTION,
                )
            )
            .order_by(OAuthFlow.expires_at.asc())
            .limit(batch_size)
        ).all()
    )
    auth_session_ids = list(
        session.exec(
            select(AuthSession.id)
            .where(
                sa.or_(
                    AuthSession.expires_at <= now,
                    AuthSession.revoked_at <= now - REVOKED_SESSION_RETENTION,
                )
            )
            .order_by(AuthSession.expires_at.asc())
            .limit(batch_size)
        ).all()
    )

    deleted = sum(
        (
            _delete_ids(session, AuthRateLimitBucket, rate_limit_ids),
            _delete_ids(session, OAuthFlow, oauth_flow_ids),
            _delete_ids(session, AuthSession, auth_session_ids),
        )
    )
    if deleted:
        session.commit()
    return deleted


def cleanup_expired_auth_records_once(*, limit: int = 500) -> int:
    """Delete one bounded batch per auth table and return the total rows removed."""

    with managed_session() as session:
        return _cleanup_expired_auth_records(session, limit=limit)


async def run_auth_housekeeping_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(cleanup_expired_auth_records_once)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("auth_housekeeping_loop_failed", error=str(exc))
        await asyncio.sleep(AUTH_HOUSEKEEPING_INTERVAL_SECONDS)


__all__ = ["cleanup_expired_auth_records_once", "run_auth_housekeeping_loop"]
