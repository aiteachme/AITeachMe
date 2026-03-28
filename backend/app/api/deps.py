"""接口层公共依赖。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Generator

from fastapi import Depends, Request, Response
from sqlmodel import Session

from app.infra.config import get_settings
from app.infra.database import managed_session
from app.infra.exceptions import AITeachMeError
from app.services.auth_service import (
    create_guest_user,
    resolve_guest_user_from_token,
    resolve_user_from_token,
    set_guest_cookie_for_user,
)
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


def _extract_guest_token(request: Request) -> str | None:
    settings = get_settings()
    raw = (request.cookies.get(settings.guest_cookie_name) or "").strip()
    return raw or None


def get_current_user_context(
    request: Request,
    response: Response,
    session: Session = Depends(get_db),
) -> CurrentUserContext:
    """返回当前运行时用户。优先 access token，其次 guest token。"""

    settings = get_settings()
    device_key = _extract_device_key(request)
    token = _extract_bearer_token(request)
    guest_token = _extract_guest_token(request)

    if token:
        user = resolve_user_from_token(session, token)
        if user is not None:
            # 维持一个游客 token，便于前端退出登录后回到同一浏览器游客身份。
            set_guest_cookie_for_user(response, user_id=user.id)
            return CurrentUserContext(
                user_id=user.id,
                email=user.email,
                is_local=settings.is_local_mode,
                device_key=(device_key or user.device_key),
                is_authenticated=True,
                auth_source="token",
            )

    if guest_token:
        user = resolve_guest_user_from_token(session, guest_token)
        if user is not None:
            set_guest_cookie_for_user(response, user_id=user.id)
            return CurrentUserContext(
                user_id=user.id,
                email=None,
                is_local=settings.is_local_mode,
                device_key=(device_key or user.device_key),
                is_authenticated=False,
                auth_source="guest_token",
            )

    user = create_guest_user(session, device_key=device_key)
    set_guest_cookie_for_user(response, user_id=user.id)
    return CurrentUserContext(
        user_id=user.id,
        email=None,
        is_local=settings.is_local_mode,
        device_key=(device_key or user.device_key),
        is_authenticated=False,
        auth_source="guest_bootstrap",
    )
