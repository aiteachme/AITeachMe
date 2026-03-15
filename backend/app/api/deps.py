"""
共享依赖 — Subject 校验、DB Session、分页参数
"""

from __future__ import annotations

from typing import Generator

from fastapi import Depends, Path
from pydantic import BaseModel, Field
from sqlmodel import Session

from app.core.database import get_session
from app.utils.subject import validate_subject as _validate_subject


def validate_subject(subject: str = Path(...)) -> str:
    """路径依赖：校验 subject 命名并转小写。"""
    return _validate_subject(subject)


def get_db() -> Generator[Session, None, None]:
    """会话依赖：每请求创建 Session，请求结束后关闭。"""
    session = get_session()
    try:
        yield session
    finally:
        session.close()


class PaginationParams(BaseModel):
    """请求体分页参数：limit 默认 100，offset 默认 0。"""

    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
