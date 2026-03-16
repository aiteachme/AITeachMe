"""Shared FastAPI dependencies used by multiple route modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generator

from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import get_session
from app.schemas.common import PaginationParams
from app.utils.subject import validate_subject as _validate_subject


@dataclass(frozen=True)
class CurrentUserContext:
    user_id: str
    email: str | None
    is_local: bool


def normalize_subject_slug(subject: str) -> str:
    """Normalize the top-level subject slug in one place for future terminology changes."""

    return _validate_subject(subject)


def get_current_user_context() -> CurrentUserContext:
    """Return the current runtime user context used by local-mode scaffolding."""

    settings = get_settings()
    if settings.is_local_mode:
        return CurrentUserContext(user_id="local", email=None, is_local=True)
    return CurrentUserContext(user_id="anonymous", email=None, is_local=False)


def get_db() -> Generator[Session, None, None]:
    """Yield one SQLModel session per request and close it afterwards."""

    session = get_session()
    try:
        yield session
    finally:
        session.close()
