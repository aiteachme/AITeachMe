"""接口层公共依赖。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Generator

from fastapi import Depends, Request
from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import managed_session
from app.core.exceptions import AITeachMeError
from app.services.auth_service import get_or_create_guest_user, resolve_user_from_token
from app.utils.subject import validate_subject as _validate_subject

_DEVICE_KEY_HEADER = "x-device-key"
_DEVICE_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


@dataclass(frozen=True)
class CurrentUserContext:
    """当前运行时用户上下文。"""

    user_id: str
    email: str | None
    is_local: bool
    device_key: str | None = None
    is_authenticated: bool = False
    auth_source: str = "device"


def normalize_subject_slug(subject: str) -> str:
    """统一规范化学科标识。"""

    return _validate_subject(subject)


def get_db() -> Generator[Session, None, None]:
    """为每个请求提供一个数据库会话（自动 commit/rollback/close）。"""

    with managed_session() as session:
        yield session


def _extract_device_key(request: Request) -> str | None:
    raw = (request.headers.get(_DEVICE_KEY_HEADER) or "").strip()
    if not raw:
        return None
    if not _DEVICE_KEY_RE.fullmatch(raw):
        raise AITeachMeError(
            detail="device_key 格式非法。",
            status_code=400,
            error_code="INVALID_DEVICE_KEY",
        )
    return raw


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = (request.headers.get("authorization") or "").strip()
    if not auth_header:
        return None
    prefix = "bearer "
    if auth_header.lower().startswith(prefix):
        token = auth_header[len(prefix):].strip()
        return token or None
    return None


def get_current_user_context(
    request: Request,
    session: Session = Depends(get_db),
) -> CurrentUserContext:
    """返回当前运行时用户。优先 token，其次 device_key。"""

    settings = get_settings()
    device_key = _extract_device_key(request)
    token = _extract_bearer_token(request)

    if token:
        user = resolve_user_from_token(session, token)
        if user is not None:
            return CurrentUserContext(
                user_id=user.id,
                email=user.email,
                is_local=settings.is_local_mode,
                device_key=(device_key or user.device_key),
                is_authenticated=True,
                auth_source="token",
            )
        # token 失效时，如携带 device_key 则自动回落到设备匿名身份，避免阻塞匿名可用性。
        if not device_key:
            raise AITeachMeError(
                detail="登录态已失效，请重新登录。",
                status_code=401,
                error_code="AUTH_TOKEN_INVALID",
            )

    if device_key:
        user = get_or_create_guest_user(session, device_key=device_key)
        return CurrentUserContext(
            user_id=user.id,
            email=None,
            is_local=settings.is_local_mode,
            device_key=device_key,
            is_authenticated=False,
            auth_source="device",
        )

    # 兼容旧客户端（尚未发送 device_key）
    return CurrentUserContext(
        user_id="local",
        email=None,
        is_local=settings.is_local_mode,
        device_key=None,
        is_authenticated=False,
        auth_source="fallback",
    )
