"""System initialization queries."""

from __future__ import annotations

from app.schemas.system import InitData, RuntimeUser
from app.shared.infra.env_support import get_env_bool
from app.shared.infra.runtime import get_app_version, resolve_app_mode


def build_init_data(
    *,
    user_id: str,
    email: str | None,
    is_local: bool,
    device_key: str | None,
    is_authenticated: bool,
) -> InitData:
    """Build frontend runtime initialization data."""

    auth_enabled = get_env_bool("AUTH_ENABLED", True)
    return InitData(
        mode=resolve_app_mode(),
        auth_enabled=auth_enabled,
        auth_ready=True,
        current_user=RuntimeUser(
            user_id=user_id,
            email=email,
            is_local=is_local,
            device_key=device_key,
            is_authenticated=is_authenticated,
        ),
        feature_flags={
            "auth": auth_enabled,
            "files": True,
            "knowledge": True,
            "chat": True,
            "exam": True,
            "profile": True,
        },
        version=get_app_version(),
    )
