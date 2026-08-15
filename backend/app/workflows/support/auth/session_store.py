"""Opaque, revocable browser sessions and CSRF protection."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import Request, Response
from sqlmodel import Session, select

from app.models import AuthSession, User
from app.shared.infra.env_support import get_env, get_env_int, get_env_optional_bool
from app.shared.infra.exceptions import AITeachMeError
from app.shared.infra.runtime import is_cloud_mode, resolve_guest_cookie_samesite, resolve_guest_cookie_secure
from app.utils.time import utcnow

SESSION_COOKIE_NAME = "atm_session"
SESSION_TOUCH_INTERVAL = timedelta(minutes=5)
_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_DEFAULT_ORIGINS = {
    "https://aiteachme.cn",
    "https://www.aiteachme.cn",
    "https://aiteachme.pages.dev",
    "http://localhost:5180",
    "http://127.0.0.1:5180",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "tauri://localhost",
}
_TRUSTED_NATIVE_ORIGINS = {"aiteachme://android"}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _request_digest(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None


def get_session_cookie_name() -> str:
    return (get_env("AUTH_SESSION_COOKIE_NAME", SESSION_COOKIE_NAME) or SESSION_COOKIE_NAME).strip()


def _cookie_secure() -> bool:
    explicit = get_env_optional_bool("AUTH_SESSION_COOKIE_SECURE")
    return resolve_guest_cookie_secure() if explicit is None else explicit


def _cookie_samesite() -> str:
    configured = (get_env("AUTH_SESSION_COOKIE_SAMESITE") or "").strip().lower()
    return configured if configured in {"lax", "strict", "none"} else resolve_guest_cookie_samesite()


def _session_ttl() -> timedelta:
    return timedelta(hours=max(1, get_env_int("AUTH_SESSION_TTL_HOURS", 24 * 7)))


def create_auth_session(
    session: Session,
    *,
    user: User,
    device_key: str | None,
    request: Request | None = None,
) -> tuple[AuthSession, str]:
    if not user.is_registered or user.merged_into_user_id is not None:
        raise AITeachMeError(
            detail="当前账号不能创建登录会话。",
            status_code=401,
            error_code="AUTH_ACCOUNT_UNAVAILABLE",
        )
    raw_token = secrets.token_urlsafe(48)
    now = utcnow()
    record = AuthSession(
        id=f"ses_{uuid4().hex}",
        user_id=user.id,
        token_hash=_token_hash(raw_token),
        csrf_token=secrets.token_urlsafe(32),
        device_key=(device_key or "").strip() or None,
        ip_hash=_request_digest(request.client.host if request and request.client else None),
        user_agent_hash=_request_digest(request.headers.get("user-agent") if request else None),
        created_at=now,
        last_seen_at=now,
        expires_at=now + _session_ttl(),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record, raw_token


def set_auth_session_cookie(response: Response, *, raw_token: str) -> None:
    response.set_cookie(
        key=get_session_cookie_name(),
        value=raw_token,
        max_age=int(_session_ttl().total_seconds()),
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        path="/",
    )


def clear_auth_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=get_session_cookie_name(),
        httponly=True,
        secure=_cookie_secure(),
        samesite=_cookie_samesite(),
        path="/",
    )


def resolve_auth_session(
    session: Session,
    *,
    raw_token: str,
) -> tuple[User, AuthSession] | None:
    record = session.exec(
        select(AuthSession).where(AuthSession.token_hash == _token_hash(raw_token))
    ).first()
    now = utcnow()
    if record is None or record.revoked_at is not None or _as_utc(record.expires_at) <= _as_utc(now):
        return None
    user = session.get(User, record.user_id)
    if user is None or not user.is_registered or user.merged_into_user_id is not None:
        return None
    if _as_utc(record.last_seen_at) <= _as_utc(now - SESSION_TOUCH_INTERVAL):
        record.last_seen_at = now
        session.add(record)
        session.commit()
    return user, record


def revoke_auth_session(session: Session, *, session_id: str) -> None:
    record = session.get(AuthSession, session_id)
    if record is not None and record.revoked_at is None:
        record.revoked_at = utcnow()
        session.add(record)
        session.commit()


def revoke_all_auth_sessions(session: Session, *, user_id: str) -> int:
    records = session.exec(
        select(AuthSession).where(
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    now = utcnow()
    for record in records:
        record.revoked_at = now
        session.add(record)
    session.commit()
    return len(records)


def validate_session_request(request: Request, *, auth_session: AuthSession) -> None:
    if request.method.upper() not in _UNSAFE_METHODS:
        return

    configured = (get_env("CORS_ALLOWED_ORIGINS") or "").strip()
    allowed_origins = (
        {item.strip() for item in configured.split(",") if item.strip()}
        if configured
        else _DEFAULT_ORIGINS
    )
    allowed_origins.update(_TRUSTED_NATIVE_ORIGINS)
    origin = (request.headers.get("origin") or "").strip()
    if origin and origin not in allowed_origins:
        raise AITeachMeError(
            detail="请求来源不受信任。",
            status_code=403,
            error_code="AUTH_ORIGIN_REJECTED",
        )
    if is_cloud_mode() and not origin:
        raise AITeachMeError(
            detail="登录写请求缺少 Origin。",
            status_code=403,
            error_code="AUTH_ORIGIN_REQUIRED",
        )

    provided = (request.headers.get("x-csrf-token") or "").strip()
    if not provided or not hmac.compare_digest(provided, auth_session.csrf_token):
        raise AITeachMeError(
            detail="CSRF 校验失败，请刷新登录状态后重试。",
            status_code=403,
            error_code="AUTH_CSRF_INVALID",
        )
