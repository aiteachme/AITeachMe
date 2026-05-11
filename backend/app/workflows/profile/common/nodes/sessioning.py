"""Profile session helpers for graph nodes.

Node modules use this small helper to share optional API-provided sessions.
It does not own workflow routing, tracing, or profile business rules.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager

from sqlmodel import Session

from app.shared.infra.database import managed_session


@contextmanager
def node_session(session_override: Session | None) -> Generator[Session, None, None]:
    """Yield a database session for one Profile graph node."""

    if session_override is not None:
        yield session_override
        return
    with managed_session() as session:
        yield session


__all__ = ["node_session"]
