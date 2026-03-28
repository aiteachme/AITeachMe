"""系统信息服务层。"""

from __future__ import annotations

from app.infra.config import get_settings
from app.schemas.system import InitData, RuntimeUser


def build_init_data(
    *,
    user_id: str,
    email: str | None,
    is_local: bool,
    device_key: str | None,
    is_authenticated: bool,
) -> InitData:
    """构造系统初始化数据。"""

    settings = get_settings()
    return InitData(
        mode=settings.app_mode,
        auth_enabled=settings.auth_enabled,
        auth_ready=settings.auth_ready,
        current_user=RuntimeUser(
            user_id=user_id,
            email=email,
            is_local=is_local,
            device_key=device_key,
            is_authenticated=is_authenticated,
        ),
        feature_flags={
            "auth": settings.auth_enabled,
            "files": True,
            "knowledge": True,
            "chat": True,
            "exam": True,
            "profile": True,
        },
        version=settings.app_version,
    )
