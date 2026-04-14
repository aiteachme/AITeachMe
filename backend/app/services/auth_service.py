"""Authentication service: device-aware guest and email/password login."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import socket
import smtplib
import ssl
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr

import structlog
from fastapi import Response
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.shared.infra.env_support import (
    get_env,
    get_env_bool,
    get_env_int,
)
from app.shared.infra.exceptions import AITeachMeError, AuthDisabledError
from app.shared.infra.runtime import (
    get_guest_cookie_name,
    is_local_mode,
    resolve_guest_cookie_samesite,
    resolve_guest_cookie_secure,
)
from app.models import EmailVerificationCode, User
from app.repositories.user_repo import (
    attach_device_key,
    create_user,
    get_user_by_device_key,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
)
from app.schemas.auth import AuthSessionData, SendEmailCodeData
from app.schemas.system import RuntimeUser
from app.utils.time import utcnow

logger = structlog.get_logger()

_PASSWORD_SCHEME = "pbkdf2_sha256"
_PASSWORD_ITERATIONS = 120_000
_GUEST_TOKEN_KIND = "guest"
_VERIFICATION_PURPOSE_REGISTER = "register"
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_EMAIL_CODE_RE = re.compile(r"^[A-Za-z0-9]{4,16}$")
_SMTP_ADDRESS_FAMILY_MAP = {
    "auto": socket.AF_UNSPEC,
    "ipv4": socket.AF_INET,
    "ipv6": socket.AF_INET6,
}


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _auth_token_secret() -> str:
    return get_env("AUTH_TOKEN_SECRET", "aiteachme-dev-token-secret") or "aiteachme-dev-token-secret"


def ensure_auth_enabled() -> None:
    if not get_env_bool("AUTH_ENABLED", True):
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
    if not _EMAIL_RE.fullmatch(normalized):
        raise AITeachMeError(
            detail="邮箱格式不正确。",
            status_code=400,
            error_code="AUTH_INVALID_EMAIL",
        )
    return normalized


def _normalize_verification_code(raw_code: str) -> str:
    code = raw_code.strip()
    if not _EMAIL_CODE_RE.fullmatch(code):
        raise AITeachMeError(
            detail="验证码格式不正确。",
            status_code=400,
            error_code="AUTH_INVALID_EMAIL_CODE",
        )
    return code


def _hash_email_verification_code(*, email: str, purpose: str, code: str) -> str:
    secret = _auth_token_secret()
    payload = f"{purpose}:{email}:{code}:{secret}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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


def _normalize_smtp_address_family(raw_value: str | None) -> str:
    normalized = (raw_value or "auto").strip().lower()
    if not normalized:
        return "auto"
    if normalized not in _SMTP_ADDRESS_FAMILY_MAP:
        raise AITeachMeError(
            detail="SMTP_ADDRESS_FAMILY 仅支持 auto、ipv4、ipv6。",
            status_code=503,
            error_code="AUTH_SMTP_NOT_CONFIGURED",
        )
    return normalized


def _socket_family_name(family: int) -> str:
    if family == socket.AF_INET:
        return "ipv4"
    if family == socket.AF_INET6:
        return "ipv6"
    return str(family)


def _format_smtp_sockaddr(sockaddr: tuple[object, ...]) -> str:
    if len(sockaddr) >= 4:
        host, port = sockaddr[:2]
        return f"[{host}]:{port}"
    host, port = sockaddr[:2]
    return f"{host}:{port}"


def _resolve_smtp_target_addresses(
    host: str,
    port: int,
    *,
    address_family: str,
) -> list[tuple[int, int, int, str, tuple[object, ...]]]:
    family = _SMTP_ADDRESS_FAMILY_MAP[address_family]
    return socket.getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)


def _open_smtp_socket(
    *,
    host: str,
    port: int,
    timeout_s: float,
    address_family: str,
    ssl_context: ssl.SSLContext | None = None,
) -> socket.socket:
    addresses = _resolve_smtp_target_addresses(host, port, address_family=address_family)
    logger.info(
        "email_verification_smtp_resolved",
        smtp_host=host,
        smtp_port=port,
        smtp_address_family=address_family,
        resolved_addresses=[_format_smtp_sockaddr(sockaddr) for _, _, _, _, sockaddr in addresses],
    )

    last_error: OSError | None = None
    for family, socktype, proto, _, sockaddr in addresses:
        attempt_started = time.perf_counter()
        raw_socket: socket.socket | None = None
        try:
            raw_socket = socket.socket(family, socktype, proto)
            raw_socket.settimeout(timeout_s)
            raw_socket.connect(sockaddr)
            connected_socket: socket.socket = raw_socket
            if ssl_context is not None:
                connected_socket = ssl_context.wrap_socket(raw_socket, server_hostname=host)
            logger.info(
                "email_verification_smtp_connect_attempt_finished",
                smtp_host=host,
                smtp_port=port,
                smtp_address_family=address_family,
                socket_family=_socket_family_name(family),
                target_address=_format_smtp_sockaddr(sockaddr),
                elapsed_ms=int((time.perf_counter() - attempt_started) * 1000),
            )
            return connected_socket
        except OSError as exc:
            last_error = exc
            if raw_socket is not None:
                raw_socket.close()
            logger.warning(
                "email_verification_smtp_connect_attempt_failed",
                smtp_host=host,
                smtp_port=port,
                smtp_address_family=address_family,
                socket_family=_socket_family_name(family),
                target_address=_format_smtp_sockaddr(sockaddr),
                elapsed_ms=int((time.perf_counter() - attempt_started) * 1000),
                error=str(exc),
            )

    if last_error is not None:
        raise last_error
    raise OSError("No SMTP target addresses were resolved.")


class _AddressFamilySMTP(smtplib.SMTP):
    def __init__(self, *, timeout: float, address_family: str):
        self._smtp_address_family = address_family
        super().__init__(host="", port=0, timeout=timeout)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        return _open_smtp_socket(
            host=host,
            port=port,
            timeout_s=timeout,
            address_family=self._smtp_address_family,
        )


class _AddressFamilySMTP_SSL(smtplib.SMTP_SSL):
    def __init__(self, *, timeout: float, address_family: str, context: ssl.SSLContext):
        self._smtp_address_family = address_family
        super().__init__(host="", port=0, timeout=timeout, context=context)

    def _get_socket(self, host: str, port: int, timeout: float) -> socket.socket:
        return _open_smtp_socket(
            host=host,
            port=port,
            timeout_s=timeout,
            address_family=self._smtp_address_family,
            ssl_context=self.context,
        )


def _ensure_smtp_ready() -> None:
    host = (get_env("SMTP_HOST") or "").strip()
    from_email = (get_env("SMTP_FROM_EMAIL") or "").strip()
    username = (get_env("SMTP_USERNAME") or "").strip()
    password = get_env("SMTP_PASSWORD", "") or ""
    _normalize_smtp_address_family(get_env("SMTP_ADDRESS_FAMILY", "ipv4"))

    if not host or not from_email:
        raise AITeachMeError(
            detail="SMTP 未配置完整，请检查 SMTP_HOST 与 SMTP_FROM_EMAIL。",
            status_code=503,
            error_code="AUTH_SMTP_NOT_CONFIGURED",
        )
    if username and not password:
        raise AITeachMeError(
            detail="SMTP 用户名已配置，但缺少 SMTP 密码。",
            status_code=503,
            error_code="AUTH_SMTP_NOT_CONFIGURED",
        )
    if get_env_bool("SMTP_USE_SSL", True) and get_env_bool("SMTP_USE_STARTTLS", False):
        raise AITeachMeError(
            detail="SMTP_USE_SSL 与 SMTP_USE_STARTTLS 不能同时开启。",
            status_code=503,
            error_code="AUTH_SMTP_NOT_CONFIGURED",
        )


def _send_email_verification_message(*, to_email: str, code: str, ttl_seconds: int) -> None:
    _ensure_smtp_ready()

    host = (get_env("SMTP_HOST") or "").strip()
    port = get_env_int("SMTP_PORT", 465)
    username = (get_env("SMTP_USERNAME") or "").strip() or None
    password = get_env("SMTP_PASSWORD", "") or ""
    from_email = (get_env("SMTP_FROM_EMAIL") or "").strip()
    from_name = (get_env("SMTP_FROM_NAME", "AITeachMe") or "AITeachMe").strip() or "AITeachMe"
    address_family = _normalize_smtp_address_family(get_env("SMTP_ADDRESS_FAMILY", "ipv4"))
    timeout_s = max(3, get_env_int("SMTP_TIMEOUT_S", 15))
    ttl_min = max(1, int(round(ttl_seconds / 60)))

    msg = EmailMessage()
    msg["Subject"] = "AITeachMe 邮箱验证码"
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_email
    msg.set_content(
        "\n".join(
            [
                "你好，",
                "",
                f"你的验证码是：{code}",
                f"有效期：{ttl_min} 分钟",
                "",
                "如果这不是你的操作，请忽略这封邮件。",
                "",
                "AITeachMe",
            ]
        ),
        charset="utf-8",
    )

    ssl_context = ssl.create_default_context()
    started_at = time.perf_counter()
    to_domain = to_email.rsplit("@", 1)[-1].lower() if "@" in to_email else None
    smtp_use_ssl = get_env_bool("SMTP_USE_SSL", True)
    smtp_use_starttls = get_env_bool("SMTP_USE_STARTTLS", False)
    smtp_mode = "ssl" if smtp_use_ssl else ("starttls" if smtp_use_starttls else "plain")
    logger.info(
        "email_verification_send_started",
        to_domain=to_domain,
        smtp_host=host,
        smtp_port=port,
        smtp_mode=smtp_mode,
        smtp_address_family=address_family,
        smtp_timeout_s=timeout_s,
    )
    try:
        if smtp_use_ssl:
            with _AddressFamilySMTP_SSL(
                timeout=timeout_s,
                address_family=address_family,
                context=ssl_context,
            ) as client:
                connect_started = time.perf_counter()
                client.connect(host=host, port=port)
                logger.info(
                    "email_verification_smtp_connected",
                    smtp_host=host,
                    smtp_port=port,
                    smtp_mode=smtp_mode,
                    elapsed_ms=int((time.perf_counter() - connect_started) * 1000),
                )
                if username is not None:
                    login_started = time.perf_counter()
                    client.login(username, password)
                    logger.info(
                        "email_verification_smtp_login_finished",
                        smtp_host=host,
                        smtp_port=port,
                        elapsed_ms=int((time.perf_counter() - login_started) * 1000),
                    )
                send_started = time.perf_counter()
                client.send_message(msg)
                logger.info(
                    "email_verification_smtp_send_finished",
                    smtp_host=host,
                    smtp_port=port,
                    elapsed_ms=int((time.perf_counter() - send_started) * 1000),
                )
            logger.info(
                "email_verification_send_finished",
                to_domain=to_domain,
                smtp_host=host,
                smtp_port=port,
                elapsed_ms=int((time.perf_counter() - started_at) * 1000),
            )
            return

        with _AddressFamilySMTP(timeout=timeout_s, address_family=address_family) as client:
            connect_started = time.perf_counter()
            client.connect(host=host, port=port)
            logger.info(
                "email_verification_smtp_connected",
                smtp_host=host,
                smtp_port=port,
                smtp_mode=smtp_mode,
                elapsed_ms=int((time.perf_counter() - connect_started) * 1000),
            )
            ehlo_started = time.perf_counter()
            client.ehlo()
            logger.info(
                "email_verification_smtp_ehlo_finished",
                smtp_host=host,
                smtp_port=port,
                elapsed_ms=int((time.perf_counter() - ehlo_started) * 1000),
            )
            if smtp_use_starttls:
                starttls_started = time.perf_counter()
                client.starttls(context=ssl_context)
                client.ehlo()
                logger.info(
                    "email_verification_smtp_starttls_finished",
                    smtp_host=host,
                    smtp_port=port,
                    elapsed_ms=int((time.perf_counter() - starttls_started) * 1000),
                )
            if username is not None:
                login_started = time.perf_counter()
                client.login(username, password)
                logger.info(
                    "email_verification_smtp_login_finished",
                    smtp_host=host,
                    smtp_port=port,
                    elapsed_ms=int((time.perf_counter() - login_started) * 1000),
                )
            send_started = time.perf_counter()
            client.send_message(msg)
            logger.info(
                "email_verification_smtp_send_finished",
                smtp_host=host,
                smtp_port=port,
                elapsed_ms=int((time.perf_counter() - send_started) * 1000),
            )
        logger.info(
            "email_verification_send_finished",
            to_domain=to_domain,
            smtp_host=host,
            smtp_port=port,
            elapsed_ms=int((time.perf_counter() - started_at) * 1000),
        )
    except smtplib.SMTPException as exc:
        logger.warning("email_verification_send_failed", error=str(exc))
        raise AITeachMeError(
            detail="验证码邮件发送失败，请稍后重试。",
            status_code=502,
            error_code="AUTH_EMAIL_CODE_SEND_FAILED",
        ) from exc
    except OSError as exc:
        logger.warning("email_verification_smtp_unavailable", error=str(exc))
        raise AITeachMeError(
            detail="SMTP 服务暂不可用，请稍后重试。",
            status_code=503,
            error_code="AUTH_SMTP_UNAVAILABLE",
        ) from exc


def _query_latest_pending_verification(
    session: Session,
    *,
    email: str,
    purpose: str,
) -> EmailVerificationCode | None:
    stmt = (
        select(EmailVerificationCode)
        .where(
            EmailVerificationCode.email == email,
            EmailVerificationCode.purpose == purpose,
            EmailVerificationCode.consumed_at.is_(None),
        )
        .order_by(
            EmailVerificationCode.created_at.desc(),
            EmailVerificationCode.id.desc(),
        )
    )
    return session.exec(stmt).first()


def send_register_email_verification_code(
    session: Session,
    *,
    email: str,
) -> SendEmailCodeData:
    ensure_auth_enabled()
    normalized_email = _normalize_email(email)

    existing = get_user_by_email(session, normalized_email)
    if existing is not None and existing.is_registered:
        raise AITeachMeError(
            detail="该邮箱已被注册，请直接登录。",
            status_code=409,
            error_code="AUTH_EMAIL_ALREADY_REGISTERED",
        )

    now = utcnow()
    resend_interval_s = max(1, get_env_int("AUTH_EMAIL_CODE_RESEND_INTERVAL_S", 60))
    latest = _query_latest_pending_verification(
        session,
        email=normalized_email,
        purpose=_VERIFICATION_PURPOSE_REGISTER,
    )
    if latest is not None and _as_utc(latest.expires_at) > now:
        elapsed_s = int((now - _as_utc(latest.created_at)).total_seconds())
        remaining_s = resend_interval_s - elapsed_s
        if remaining_s > 0:
            raise AITeachMeError(
                detail=f"验证码发送过于频繁，请 {remaining_s} 秒后重试。",
                status_code=429,
                error_code="AUTH_EMAIL_CODE_RATE_LIMITED",
            )

    ttl_s = max(60, get_env_int("AUTH_EMAIL_CODE_TTL_S", 600))
    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = _hash_email_verification_code(
        email=normalized_email,
        purpose=_VERIFICATION_PURPOSE_REGISTER,
        code=code,
    )
    record = EmailVerificationCode(
        email=normalized_email,
        purpose=_VERIFICATION_PURPOSE_REGISTER,
        code_hash=code_hash,
        expires_at=now + timedelta(seconds=ttl_s),
    )

    session.add(record)
    try:
        _send_email_verification_message(
            to_email=normalized_email,
            code=code,
            ttl_seconds=ttl_s,
        )
    except Exception:
        session.rollback()
        raise
    session.commit()

    return SendEmailCodeData(
        expires_in_s=ttl_s,
        resend_after_s=resend_interval_s,
    )


def _consume_register_email_code(
    session: Session,
    *,
    email: str,
    verification_code: str,
) -> None:
    now = utcnow()
    code = _normalize_verification_code(verification_code)

    latest = _query_latest_pending_verification(
        session,
        email=email,
        purpose=_VERIFICATION_PURPOSE_REGISTER,
    )
    if latest is None:
        raise AITeachMeError(
            detail="请先发送邮箱验证码。",
            status_code=400,
            error_code="AUTH_EMAIL_CODE_REQUIRED",
        )

    if _as_utc(latest.expires_at) <= now:
        latest.consumed_at = now
        latest.updated_at = now
        session.add(latest)
        session.commit()
        raise AITeachMeError(
            detail="验证码已过期，请重新发送。",
            status_code=400,
            error_code="AUTH_EMAIL_CODE_EXPIRED",
        )

    max_attempts = max(1, get_env_int("AUTH_EMAIL_CODE_MAX_ATTEMPTS", 5))
    if latest.attempt_count >= max_attempts:
        latest.consumed_at = now
        latest.updated_at = now
        session.add(latest)
        session.commit()
        raise AITeachMeError(
            detail="验证码错误次数过多，请重新发送。",
            status_code=400,
            error_code="AUTH_EMAIL_CODE_TOO_MANY_ATTEMPTS",
        )

    provided_hash = _hash_email_verification_code(
        email=email,
        purpose=_VERIFICATION_PURPOSE_REGISTER,
        code=code,
    )
    if not hmac.compare_digest(latest.code_hash, provided_hash):
        latest.attempt_count += 1
        if latest.attempt_count >= max_attempts:
            latest.consumed_at = now
        latest.updated_at = now
        session.add(latest)
        session.commit()
        if latest.attempt_count >= max_attempts:
            raise AITeachMeError(
                detail="验证码错误次数过多，请重新发送。",
                status_code=400,
                error_code="AUTH_EMAIL_CODE_TOO_MANY_ATTEMPTS",
            )
        raise AITeachMeError(
            detail="验证码错误。",
            status_code=400,
            error_code="AUTH_INVALID_EMAIL_CODE",
        )

    latest.consumed_at = now
    latest.updated_at = now
    session.add(latest)


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
    now = int(time.time())
    payload = {
        "sub": user.id,
        "email": user.email,
        "device_key": (device_key or user.device_key),
        "iat": now,
        "exp": now + max(60, get_env_int("AUTH_TOKEN_TTL_HOURS", 24 * 30) * 3600),
    }
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload_json)
    signature = hmac.new(
        _auth_token_secret().encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{payload_b64}.{_b64url_encode(signature)}"


def issue_guest_token(*, user_id: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "typ": _GUEST_TOKEN_KIND,
        "iat": now,
        "exp": now + max(60, get_env_int("GUEST_TOKEN_TTL_HOURS", 24 * 30) * 3600),
    }
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload_json)
    signature = hmac.new(
        _auth_token_secret().encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{payload_b64}.{_b64url_encode(signature)}"


def decode_access_token(token: str) -> dict[str, object] | None:
    try:
        payload_b64, signature_b64 = token.split(".", 1)
    except ValueError:
        return None

    expected = hmac.new(
        _auth_token_secret().encode("utf-8"),
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


def decode_guest_token(token: str) -> dict[str, object] | None:
    try:
        payload_b64, signature_b64 = token.split(".", 1)
    except ValueError:
        return None

    expected = hmac.new(
        _auth_token_secret().encode("utf-8"),
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

    token_type = payload.get("typ")
    exp = payload.get("exp")
    if token_type != _GUEST_TOKEN_KIND:
        return None
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


def resolve_guest_user_from_token(session: Session, token: str) -> User | None:
    payload = decode_guest_token(token)
    if payload is None:
        return None
    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id.strip():
        return None
    user = get_user_by_id(session, user_id)
    if user is None or user.is_registered:
        return None
    return user


def _build_guest_username(session: Session) -> str:
    base = f"guest_{secrets.token_hex(6)}"
    username = base
    suffix = 1
    while get_user_by_username(session, username) is not None:
        suffix += 1
        username = f"{base}_{suffix}"
    return username


def _persist_guest_user(session: Session) -> User:
    while True:
        try:
            return create_user(
                session,
                username=_build_guest_username(session),
                is_registered=False,
            )
        except IntegrityError:
            session.rollback()


def create_guest_user(session: Session, *, device_key: str | None = None) -> User:
    normalized_device_key = (device_key or "").strip() or None
    if normalized_device_key is None:
        return _persist_guest_user(session)

    owner = get_user_by_device_key(session, normalized_device_key)
    if owner is not None and not owner.is_registered:
        return owner

    guest = _persist_guest_user(session)
    return attach_device_key(session, user=guest, device_key=normalized_device_key)


def build_logout_guest_user(session: Session, *, device_key: str | None) -> User:
    return create_guest_user(session, device_key=device_key)


def set_guest_cookie(response: Response, *, guest_token: str) -> None:
    max_age = max(60, get_env_int("GUEST_TOKEN_TTL_HOURS", 24 * 30) * 3600)
    response.set_cookie(
        key=get_guest_cookie_name(),
        value=guest_token,
        max_age=max_age,
        httponly=True,
        secure=resolve_guest_cookie_secure(),
        samesite=resolve_guest_cookie_samesite(),
        path="/",
    )


def set_guest_cookie_for_user(response: Response, *, user_id: str) -> str:
    token = issue_guest_token(user_id=user_id)
    set_guest_cookie(response, guest_token=token)
    return token


def register_user(
    session: Session,
    *,
    current_user_id: str | None,
    email: str,
    password: str,
    verification_code: str,
    device_key: str | None,
) -> AuthSessionData:
    ensure_auth_enabled()
    normalized_email = _normalize_email(email)

    existing_by_email = get_user_by_email(session, normalized_email)
    if existing_by_email is not None and existing_by_email.is_registered:
        raise AITeachMeError(
            detail="该邮箱已被注册，请直接登录。",
            status_code=409,
            error_code="AUTH_EMAIL_ALREADY_REGISTERED",
        )

    user = get_user_by_id(session, current_user_id) if current_user_id else None
    if user is None:
        user = create_guest_user(session, device_key=device_key)
    if user.is_registered:
        raise AITeachMeError(
            detail="当前会话已绑定账号，请直接登录或先退出。",
            status_code=409,
            error_code="AUTH_SESSION_ALREADY_REGISTERED",
        )

    _consume_register_email_code(
        session,
        email=normalized_email,
        verification_code=verification_code,
    )

    if not user.username or user.username.startswith("guest_"):
        base = _build_username_from_email(normalized_email)
        user.username = _ensure_unique_username(session, base)

    user.email = normalized_email
    user.password_hash = hash_password(password)
    user.is_registered = True
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)

    if device_key:
        user = attach_device_key(session, user=user, device_key=device_key)

    token = issue_access_token(user=user, device_key=device_key)
    return build_auth_session_data(user=user, access_token=token)


def login_user(
    session: Session,
    *,
    email: str,
    password: str,
    device_key: str | None,
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

    if device_key:
        user = attach_device_key(session, user=user, device_key=device_key)
    token = issue_access_token(user=user, device_key=device_key)
    return build_auth_session_data(user=user, access_token=token)


def build_auth_session_data(
    *,
    user: User,
    access_token: str | None,
) -> AuthSessionData:
    return AuthSessionData(
        auth_enabled=get_env_bool("AUTH_ENABLED", True),
        auth_ready=True,
        token_type="bearer",
        access_token=access_token,
        current_user=RuntimeUser(
            user_id=user.id,
            email=user.email,
            is_local=is_local_mode(),
            device_key=user.device_key,
            is_authenticated=user.is_registered,
        ),
    )


def build_guest_session_data(*, user: User | None) -> AuthSessionData:
    runtime_user: RuntimeUser | None = None
    if user is not None:
        runtime_user = RuntimeUser(
            user_id=user.id,
            email=user.email,
            is_local=is_local_mode(),
            device_key=user.device_key,
            is_authenticated=user.is_registered,
        )
    return AuthSessionData(
        auth_enabled=get_env_bool("AUTH_ENABLED", True),
        auth_ready=True,
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
    return AuthSessionData(
        auth_enabled=get_env_bool("AUTH_ENABLED", True),
        auth_ready=True,
        token_type="bearer",
        access_token=None,
        current_user=RuntimeUser(
            user_id=user_id,
            email=email,
            is_local=is_local_mode(),
            device_key=device_key,
            is_authenticated=is_authenticated,
        ),
    )
