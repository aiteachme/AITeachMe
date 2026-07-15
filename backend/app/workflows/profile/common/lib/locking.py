"""Transaction-scoped serialization for Profile writes."""

from __future__ import annotations

import hashlib

import sqlalchemy as sa
from sqlmodel import Session


_PROFILE_UPDATE_LOCK_NAMESPACE = "profile.update"


def profile_user_lock_key(user_id: str) -> int:
    """Return a stable signed int64 advisory-lock key for one user."""

    normalized_user_id = str(user_id).strip()
    if not normalized_user_id:
        raise ValueError("profile_user_lock_user_id_required")
    digest = hashlib.sha256(
        f"{_PROFILE_UPDATE_LOCK_NAMESPACE}:{normalized_user_id}".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def postgres_profile_user_lock_statement(lock_key: int):
    """Build the PostgreSQL transaction-level advisory-lock statement."""

    return sa.select(
        sa.func.pg_advisory_xact_lock(
            sa.literal(lock_key, type_=sa.BigInteger()),
        )
    )


def _dialect_name(session: Session) -> str:
    return str(session.get_bind().dialect.name)


def _sqlite_driver_transaction_active(session: Session) -> bool:
    connection = session.connection()
    driver_connection = getattr(connection.connection, "driver_connection", None)
    return bool(getattr(driver_connection, "in_transaction", False))


def prepare_profile_write_transaction(session: Session) -> None:
    """Start the write transaction before Profile business reads.

    PostgreSQL can acquire its user-scoped advisory lock after resolving the
    exam's real user. SQLite must reserve the single writer slot before any
    business read, so a dependency-created read-only transaction is restarted
    as ``BEGIN IMMEDIATE``. Pending ORM writes are never discarded implicitly.
    """

    if _dialect_name(session) != "sqlite":
        return

    if session.new or session.dirty or session.deleted:
        raise RuntimeError("profile_sqlite_transaction_has_pending_writes")
    if session.in_nested_transaction():
        raise RuntimeError("profile_sqlite_nested_transaction_cannot_be_restarted")
    if session.in_transaction():
        if _sqlite_driver_transaction_active(session):
            raise RuntimeError("profile_sqlite_transaction_is_not_read_only")
        session.rollback()
    session.exec(sa.text("BEGIN IMMEDIATE"))


def acquire_profile_user_lock(session: Session, *, user_id: str) -> None:
    """Serialize Profile writes for one user until transaction completion."""

    dialect_name = _dialect_name(session)
    if dialect_name == "postgresql":
        session.exec(postgres_profile_user_lock_statement(profile_user_lock_key(user_id)))
        return
    if dialect_name == "sqlite":
        if not session.in_transaction():
            raise RuntimeError("profile_sqlite_write_transaction_not_prepared")
        return
    raise RuntimeError(f"profile_write_lock_unsupported_dialect:{dialect_name}")


__all__ = [
    "acquire_profile_user_lock",
    "postgres_profile_user_lock_statement",
    "prepare_profile_write_transaction",
    "profile_user_lock_key",
]
