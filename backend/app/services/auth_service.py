"""鉴权占位服务层。"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.exceptions import AuthDisabledError, AuthNotReadyError
from app.schemas.auth import AuthSessionData


def ensure_auth_ready() -> None:
    """检查鉴权能力是否可用。"""

    settings = get_settings()
    if not settings.auth_enabled or settings.is_local_mode:
        raise AuthDisabledError()
    raise AuthNotReadyError()


def build_auth_session_data() -> AuthSessionData:
    """返回鉴权会话占位数据。"""

    settings = get_settings()
    return AuthSessionData(
        auth_enabled=settings.auth_enabled,
        auth_ready=settings.auth_ready,
        token_type="bearer",
        access_token=None,
        current_user=None,
    )
