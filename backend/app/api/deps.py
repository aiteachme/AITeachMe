"""Shared FastAPI dependencies used by multiple route modules."""

from __future__ import annotations

from typing import Generator

from fastapi import Path
from sqlmodel import Session

from app.core.database import get_session
from app.schemas.common import PaginationParams
from app.utils.subject import validate_subject as _validate_subject


def validate_subject(
    subject: str = Path(
        ...,
        description="学科标识，仅允许字母、数字、下划线和连字符，系统会自动转为小写。",
        examples=["math"],
    )
) -> str:
    """Validate a subject path parameter and normalize it to lowercase."""
    return _validate_subject(subject)


def get_db() -> Generator[Session, None, None]:
    """Yield one SQLModel session per request and close it afterwards."""
    session = get_session()
    try:
        yield session
    finally:
        session.close()
