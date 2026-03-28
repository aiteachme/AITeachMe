"""Authentication service: device-aware guest and email/password login."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from sqlmodel import Session

from app.core.config import get_settings
from app.core.exceptions import AITeachMeError, AuthDisabledError
from app.models import User
from app.repositories.user_repo import (
    attach_device_key,
    get_or_create_user_by_device_key,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
)
from app.schemas.auth import AuthSessionData
from app.schemas.system import RuntimeUser
from app.utils.time import utcnow

_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 120_000


def ensure_auth_enabled() -> None:
    settings = get_settings()
    if not settings.auth_enabled:
        raise AuthDisabledError()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if not normalized:
        raise AITeachMeError(
            detail="邮箱不能为空。",
            status_code=400,
            error_code="AUTH_INVALID_EMAIL",
        )
    return normalized


def _build_username_from_email(email: str) -> str:
    local = email.split("@", 1)[0].strip().lower()
    safe = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in local)
    safe = safe.strip("_")[:24]
    return safe or "user"


def _ensure_unique_username(session: Session, base: str) -> str:
    username = base
    suffix = 1
    while get_user_by_username(session, username) is not None:
        suffix += 1
        username = f"{base}_{suffix}"
    return username


def hash_password(password: str) -> str:
    if len(password) < 6:
        raise AITeachMeError(
            detail="密码至少需要 6 位。",
            status_code=400,
            error_code="AUTH_WEAK_PASSWORD",
        )
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PASSWORD_ITERATIONS,
    )
    return (
        f"{_PASSWORD_SCHEME}${_PASSWORD_ITERATIONS}$"
        f"{_b64url_encode(salt)}${_b64url_encode(digest)}"
    )


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        scheme, rounds_raw, salt_raw, digest_raw = encoded.split("$", 3)
    except ValueError:
        return False
    if scheme != _PASSWORD_SCHEME:
        return False
    try:
        rounds = int(rounds_raw)
    except ValueError:
        return False
    try:
        salt = _b64url_decode(salt_raw)
        expected = _b64url_decode(digest_raw)
    except Exception:
        return False
    computed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(expected, computed)


def issue_access_token(*, user: User, device_key: str | None = None) -> str:
    settings = get_settings()
    now = int(time.time())
    payload = {
        "sub": user.id,
        "email": user.email,
        "device_key": (device_key or user.device_key),
        "iat": now,
        "exp": now + max(60, settings.auth_token_ttl_hours * 3600),
    }
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload_json)
    signature = hmac.new(
        settings.auth_token_secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{payload_b64}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, object] | None:
    settings = get_settings()
    try:
        payload_b64, signature_b64 = token.split(".", 1)
    except ValueError:
        return None

    expected = hmac.new(
        settings.auth_token_secret.encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    try:
        provided = _b64url_decode(signature_b64)
    except Exception:
        return None
    if not hmac.compare_digest(expected, provided):
        return None

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return None
    return payload


def resolve_user_from_token(session: Session, token: str) -> User | None:
    payload = decode_access_token(token)
    if payload is None:
        return None
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id.strip():
        return None
    return get_user_by_id(session, user_id)


def get_or_create_guest_user(session: Session, *, device_key: str) -> User:
    return get_or_create_user_by_device_key(session, device_key=device_key)


def register_user(
    session: Session,
    *,
    email: str,
    password: str,
    device_key: str,
) -> AuthSessionData:
    ensure_auth_enabled()
    normalized_email = _normalize_email(email)

    existing_by_email = get_user_by_email(session, normalized_email)
    if existing_by_email is not None:
        raise AITeachMeError(
            detail="该邮箱已被注册，请直接登录。",
            status_code=409,
            error_code="AUTH_EMAIL_ALREADY_REGISTERED",
        )

    user = get_or_create_user_by_device_key(session, device_key=device_key)
    if user.is_registered:
        if user.email == normalized_email:
            raise AITeachMeError(
                detail="当前设备已绑定该邮箱，请直接登录。",
                status_code=409,
                error_code="AUTH_DEVICE_ALREADY_REGISTERED",
            )
        raise AITeachMeError(
            detail="当前设备已绑定其他账号，请先登录后再切换。",
            status_code=409,
            error_code="AUTH_DEVICE_ALREADY_REGISTERED",
        )

    if not user.username or user.username.startswith("guest_"):
        base = _build_username_from_email(normalized_email)
        user.username = _ensure_unique_username(session, base)

    user.email = normalized_email
    user.password_hash = hash_password(password)
    user.is_registered = True
    user.device_key = device_key
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)

    token = issue_access_token(user=user, device_key=device_key)
    return build_auth_session_data(user=user, access_token=token)


def login_user(
    session: Session,
    *,
    email: str,
    password: str,
    device_key: str,
) -> AuthSessionData:
    ensure_auth_enabled()
    normalized_email = _normalize_email(email)
    user = get_user_by_email(session, normalized_email)
    if user is None or not user.is_registered or not verify_password(password, user.password_hash):
        raise AITeachMeError(
            detail="邮箱或密码错误。",
            status_code=401,
            error_code="AUTH_INVALID_CREDENTIALS",
        )

    user = attach_device_key(session, user=user, device_key=device_key)
    token = issue_access_token(user=user, device_key=device_key)
    return build_auth_session_data(user=user, access_token=token)


def build_auth_session_data(
    *,
    user: User,
    access_token: str | None,
) -> AuthSessionData:
    settings = get_settings()
    return AuthSessionData(
        auth_enabled=settings.auth_enabled,
        auth_ready=settings.auth_ready,
        token_type="bearer",
        access_token=access_token,
        current_user=RuntimeUser(
            user_id=user.id,
            email=user.email,
            is_local=settings.is_local_mode,
            device_key=user.device_key,
            is_authenticated=user.is_registered,
        ),
    )


def build_guest_session_data(*, user: User | None) -> AuthSessionData:
    settings = get_settings()
    runtime_user: RuntimeUser | None = None
    if user is not None:
        runtime_user = RuntimeUser(
            user_id=user.id,
            email=user.email,
            is_local=settings.is_local_mode,
            device_key=user.device_key,
            is_authenticated=user.is_registered,
        )
    return AuthSessionData(
        auth_enabled=settings.auth_enabled,
        auth_ready=settings.auth_ready,
        token_type="bearer",
        access_token=None,
        current_user=runtime_user,
    )


def build_session_from_context(
    *,
    user_id: str,
    email: str | None,
    device_key: str | None,
    is_authenticated: bool,
) -> AuthSessionData:
    settings = get_settings()
    return AuthSessionData(
        auth_enabled=settings.auth_enabled,
        auth_ready=settings.auth_ready,
        token_type="bearer",
        access_token=None,
        current_user=RuntimeUser(
            user_id=user_id,
            email=email,
            is_local=settings.is_local_mode,
            device_key=device_key,
            is_authenticated=is_authenticated,
        ),
    )
