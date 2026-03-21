"""接口层公共依赖。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generator

from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import managed_session
from app.utils.subject import validate_subject as _validate_subject


@dataclass(frozen=True)
class CurrentUserContext:
    """当前运行时用户上下文。"""

    user_id: str
    email: str | None
    is_local: bool


def normalize_subject_slug(subject: str) -> str:
    """统一规范化学科标识。"""

    return _validate_subject(subject)


def get_current_user_context() -> CurrentUserContext:
    """返回当前运行时用户。"""

    settings = get_settings()
    if settings.is_local_mode:
        return CurrentUserContext(user_id="local", email=None, is_local=True)
    return CurrentUserContext(user_id="anonymous", email=None, is_local=False)


def get_db() -> Generator[Session, None, None]:
    """为每个请求提供一个数据库会话（自动 commit/rollback/close）。"""

    with managed_session() as session:
        yield session
