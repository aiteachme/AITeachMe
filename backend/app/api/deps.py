"""接口层公共依赖。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Generator

import structlog
from fastapi import Depends, Request, Response
from sqlmodel import Session
from app.models import User

from app.shared.infra.database import managed_session
from app.shared.infra.runtime import get_guest_cookie_name, is_local_mode
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.logger import bind_logging_context
from app.workflows.support.auth import (
    clear_auth_session_cookie,
    create_auth_session,
    create_guest_user,
    get_session_cookie_name,
    resolve_auth_session,
    resolve_guest_user_from_token,
    resolve_user_from_legacy_bearer,
    set_auth_session_cookie,
    set_guest_cookie_for_user,
    validate_session_request,
)
from app.utils.course import normalize_course_scope

logger = structlog.get_logger()

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
    role: str = "user"
    display_name: str | None = None
    avatar_url: str | None = None
    auth_session_id: str | None = None
    csrf_token: str | None = None


def normalize_course_id(course_id: str | None, *, allow_global: bool = False) -> str:
    """统一规范化课程标识。"""

    return normalize_course_scope(course_id, allow_global=allow_global)


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
    raw = (request.cookies.get(get_guest_cookie_name()) or "").strip()
    return raw or None


def _device_key_suffix(device_key: str | None) -> str | None:
    if not device_key:
        return None
    return device_key[-8:]


def _log_current_user_context(
    request: Request,
    context: CurrentUserContext,
    *,
    has_bearer_token: bool,
    has_guest_token: bool,
) -> None:
    bind_logging_context(
        user_id=context.user_id,
        auth_source=context.auth_source,
        is_authenticated=context.is_authenticated,
        device_key_suffix=_device_key_suffix(context.device_key),
    )
    logger.debug(
        "current_user_context_resolved",
        path=request.url.path,
        method=request.method,
        user_id=context.user_id,
        auth_source=context.auth_source,
        is_authenticated=context.is_authenticated,
        device_key_suffix=_device_key_suffix(context.device_key),
        has_bearer_token=has_bearer_token,
        has_guest_token=has_guest_token,
    )


def get_current_user_context(
    request: Request,
    response: Response,
    session: Session = Depends(get_db),
) -> CurrentUserContext:
    """Resolve Cookie session, one-release legacy Bearer, then guest identity."""

    device_key = _extract_device_key(request)
    token = _extract_bearer_token(request)
    guest_token = _extract_guest_token(request)
    raw_session_token = (request.cookies.get(get_session_cookie_name()) or "").strip()

    if raw_session_token:
        resolved_session = resolve_auth_session(session, raw_token=raw_session_token)
        if resolved_session is not None:
            user, auth_session = resolved_session
            validate_session_request(request, auth_session=auth_session)
            context = CurrentUserContext(
                user_id=user.id,
                email=user.email,
                is_local=is_local_mode(),
                device_key=(device_key or auth_session.device_key or user.device_key),
                is_authenticated=True,
                auth_source="session_cookie",
                role="admin" if user.role == "admin" else "user",
                display_name=user.display_name,
                avatar_url=user.avatar_url,
                auth_session_id=auth_session.id,
                csrf_token=auth_session.csrf_token,
            )
            _log_current_user_context(
                request,
                context,
                has_bearer_token=token is not None,
                has_guest_token=guest_token is not None,
            )
            return context
        clear_auth_session_cookie(response)

    if token:
        user = resolve_user_from_legacy_bearer(session, token)
        if user is not None:
            auth_session, raw_token = create_auth_session(
                session,
                user=user,
                device_key=(device_key or user.device_key),
                request=request,
            )
            set_auth_session_cookie(response, raw_token=raw_token)
            context = CurrentUserContext(
                user_id=user.id,
                email=user.email,
                is_local=is_local_mode(),
                device_key=(device_key or user.device_key),
                is_authenticated=True,
                auth_source="legacy_bearer",
                role="admin" if user.role == "admin" else "user",
                display_name=user.display_name,
                avatar_url=user.avatar_url,
                auth_session_id=auth_session.id,
                csrf_token=auth_session.csrf_token,
            )
            _log_current_user_context(
                request,
                context,
                has_bearer_token=True,
                has_guest_token=guest_token is not None,
            )
            return context

    if guest_token:
        user = resolve_guest_user_from_token(session, guest_token)
        if user is not None:
            if device_key is not None and user.device_key is not None and user.device_key != device_key:
                logger.warning(
                    "guest_token_device_key_mismatch",
                    path=request.url.path,
                    method=request.method,
                    user_id=user.id,
                    guest_device_key_suffix=_device_key_suffix(user.device_key),
                    request_device_key_suffix=_device_key_suffix(device_key),
                )
                user = None
            else:
                set_guest_cookie_for_user(response, user_id=user.id)
                context = CurrentUserContext(
                    user_id=user.id,
                    email=None,
                    is_local=is_local_mode(),
                    device_key=(device_key or user.device_key),
                    is_authenticated=False,
                    auth_source="guest_token",
                )
                _log_current_user_context(
                    request,
                    context,
                    has_bearer_token=token is not None,
                    has_guest_token=True,
                )
                return context

    user = create_guest_user(session, device_key=device_key)
    set_guest_cookie_for_user(response, user_id=user.id)
    context = CurrentUserContext(
        user_id=user.id,
        email=None,
        is_local=is_local_mode(),
        device_key=(device_key or user.device_key),
        is_authenticated=False,
        auth_source="guest_bootstrap",
    )
    _log_current_user_context(
        request,
        context,
        has_bearer_token=token is not None,
        has_guest_token=guest_token is not None,
    )
    return context


def require_authenticated_user(
    current: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> User:
    if not current.is_authenticated:
        raise AITeachMeError(detail="请先登录。", status_code=401, error_code="AUTH_REQUIRED")
    user = session.get(User, current.user_id)
    if user is None or not user.is_registered or user.merged_into_user_id is not None:
        raise AITeachMeError(detail="登录账号不可用。", status_code=401, error_code="AUTH_ACCOUNT_UNAVAILABLE")
    return user


def require_admin_user(user: User = Depends(require_authenticated_user)) -> User:
    if user.role != "admin":
        raise AITeachMeError(detail="需要管理员权限。", status_code=403, error_code="ADMIN_REQUIRED")
    return user
