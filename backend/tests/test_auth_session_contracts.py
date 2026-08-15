from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import Response
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.models import EmailConfirmation, User
from app.shared.infra.exceptions import AITeachMeError, AuthDisabledError, AuthNotReadyError
from app.workflows.support.auth import sessions


def _auth_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[User.__table__, EmailConfirmation.__table__])
    return engine


def _enable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "resolve_auth_enabled", lambda: True)
    monkeypatch.setattr(sessions, "is_cloud_mode", lambda: False)
    monkeypatch.setattr(sessions, "is_local_mode", lambda: True)
    monkeypatch.setattr(sessions, "get_guest_cookie_name", lambda: "guest_token")
    monkeypatch.setattr(sessions, "resolve_guest_cookie_secure", lambda: False)
    monkeypatch.setattr(sessions, "resolve_guest_cookie_samesite", lambda: "lax")

    values = {
        "AUTH_TOKEN_SECRET": "x" * 40,
        "AUTH_TOKEN_TTL_HOURS": 1,
        "GUEST_TOKEN_TTL_HOURS": 1,
        "AUTH_EMAIL_CODE_TTL_S": 120,
        "AUTH_EMAIL_CODE_RESEND_INTERVAL_S": 60,
        "AUTH_EMAIL_CODE_MAX_ATTEMPTS": 2,
        "AUTH_EMAIL_CONFIRMATION_RETENTION_DAYS": 7,
        "SMTP_ADDRESS_FAMILY": "ipv4",
    }

    monkeypatch.setattr(sessions, "get_env", lambda name, default="": values.get(name, default))
    monkeypatch.setattr(sessions, "get_env_int", lambda name, default: int(values.get(name, default)))
    monkeypatch.setattr(sessions, "get_env_bool", lambda name, default: bool(values.get(name, default)))


def _issue_typeless_access_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "email": user.email,
        "device_key": user.device_key,
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    payload_b64 = sessions._b64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signature = hmac.new(
        ("x" * 40).encode("utf-8"),
        payload_b64.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return f"{payload_b64}.{sessions._b64url_encode(signature)}"


def test_auth_config_normalizers_passwords_tokens_and_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_auth(monkeypatch)

    assert sessions._normalize_email(" User@Example.COM ") == "user@example.com"
    assert sessions._normalize_verification_code(" A1b2 ") == "A1b2"
    assert sessions._clean_mail_header_part("Name\r\nInjected") == "Name Injected"
    assert sessions._resolve_smtp_sender_identity(
        raw_from_email="AITeachMe <noreply@example.com>",
        raw_from_name="",
    ) == ("AITeachMe", "noreply@example.com")
    assert sessions._build_username_from_email("A.B+tag@example.com") == "a_b_tag"
    assert sessions._normalize_smtp_address_family("") == "auto"
    assert sessions._socket_family_name(sessions.socket.AF_INET) == "ipv4"
    assert sessions._format_smtp_sockaddr(("127.0.0.1", 25)) == "127.0.0.1:25"

    for value, error_code in [
        ("", "AUTH_INVALID_EMAIL"),
        ("not-an-email", "AUTH_INVALID_EMAIL"),
    ]:
        with pytest.raises(AITeachMeError) as exc_info:
            sessions._normalize_email(value)
        assert exc_info.value.error_code == error_code

    with pytest.raises(AITeachMeError) as exc_info:
        sessions._normalize_verification_code("bad code!")
    assert exc_info.value.error_code == "AUTH_INVALID_EMAIL_CODE"

    with pytest.raises(AITeachMeError) as exc_info:
        sessions._resolve_smtp_sender_identity(raw_from_email="发件人@example.com", raw_from_name="")
    assert exc_info.value.error_code == "AUTH_SMTP_NOT_CONFIGURED"

    with pytest.raises(AITeachMeError) as exc_info:
        sessions._normalize_smtp_address_family("unix")
    assert exc_info.value.error_code == "AUTH_SMTP_NOT_CONFIGURED"

    encoded = sessions.hash_password("correct-password")
    assert sessions.verify_password("correct-password", encoded) is True
    assert sessions.verify_password("wrong-password", encoded) is False
    assert sessions.verify_password("correct-password", "bad-format") is False
    with pytest.raises(AITeachMeError) as exc_info:
        sessions.hash_password("short")
    assert exc_info.value.error_code == "AUTH_WEAK_PASSWORD"

    user = User(id="usr_1", username="user", email="user@example.com", device_key="device-1", is_registered=True)
    token = sessions.issue_access_token(user=user)
    decoded = sessions.decode_access_token(token)
    assert decoded is not None
    assert decoded["sub"] == "usr_1"
    assert decoded["device_key"] == "device-1"
    assert sessions.decode_access_token("not-a-token") is None
    assert sessions.decode_access_token(f"{token}tampered") is None

    guest_token = sessions.issue_guest_token(user_id="guest-1")
    assert sessions.decode_guest_token(guest_token)["sub"] == "guest-1"
    assert sessions.decode_guest_token(token) is None
    assert sessions.decode_access_token(guest_token) is None
    assert sessions.decode_legacy_access_token(guest_token) is None

    typeless_token = _issue_typeless_access_token(user)
    assert sessions.decode_access_token(typeless_token) is None
    assert sessions.decode_legacy_access_token(typeless_token)["sub"] == user.id

    response = Response()
    returned_token = sessions.set_guest_cookie_for_user(response, user_id="guest-1")
    assert sessions.decode_guest_token(returned_token)["sub"] == "guest-1"
    assert "guest_token=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]


def test_auth_disabled_and_cloud_secret_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "resolve_auth_enabled", lambda: False)
    with pytest.raises(AuthDisabledError):
        sessions.ensure_auth_enabled()

    monkeypatch.setattr(sessions, "resolve_auth_enabled", lambda: True)
    monkeypatch.setattr(sessions, "is_cloud_mode", lambda: True)
    monkeypatch.setattr(sessions, "get_env", lambda name, default="": "too-short" if name == "AUTH_TOKEN_SECRET" else default)

    with pytest.raises(AuthNotReadyError):
        sessions._auth_token_secret()


def test_send_register_code_rate_limits_and_rolls_back_failed_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_auth(monkeypatch)
    engine = _auth_engine()
    sent_codes: list[str] = []
    monkeypatch.setattr(sessions.secrets, "randbelow", lambda _limit: 123456)
    monkeypatch.setattr(
        sessions,
        "_send_email_verification_message",
        lambda *, to_email, code, ttl_seconds: sent_codes.append(f"{to_email}:{code}:{ttl_seconds}"),
    )

    with Session(engine, expire_on_commit=False) as session:
        data = sessions.send_register_email_verification_code(session, email=" New@Example.com ")
        records = session.exec(select(EmailConfirmation)).all()

        assert data.expires_in_s == 120
        assert data.resend_after_s == 60
        assert sent_codes == ["new@example.com:123456:120"]
        assert len(records) == 1
        assert records[0].email == "new@example.com"

        with pytest.raises(AITeachMeError) as exc_info:
            sessions.send_register_email_verification_code(session, email="new@example.com")
        assert exc_info.value.error_code == "AUTH_EMAIL_CODE_RATE_LIMITED"

    engine = _auth_engine()
    monkeypatch.setattr(
        sessions,
        "_send_email_verification_message",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("smtp down")),
    )
    with Session(engine, expire_on_commit=False) as session:
        with pytest.raises(RuntimeError):
            sessions.send_register_email_verification_code(session, email="fail@example.com")
        assert session.exec(select(EmailConfirmation)).all() == []


def test_registered_email_uses_the_same_resend_cooldown_without_sending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_auth(monkeypatch)
    sent_to: list[str] = []
    monkeypatch.setattr(
        sessions,
        "_send_email_verification_message",
        lambda *, to_email, **_kwargs: sent_to.append(to_email),
    )

    with Session(_auth_engine(), expire_on_commit=False) as session:
        session.add(
            User(
                id="registered-user",
                username="registered-user",
                email="registered@example.com",
                is_registered=True,
            )
        )
        session.commit()

        first = sessions.send_register_email_verification_code(
            session,
            email="registered@example.com",
        )
        assert first.resend_after_s == 60
        assert sent_to == []
        assert session.exec(
            select(EmailConfirmation).where(
                EmailConfirmation.email == "registered@example.com"
            )
        ).one()

        with pytest.raises(AITeachMeError) as exc_info:
            sessions.send_register_email_verification_code(
                session,
                email="registered@example.com",
            )
        assert exc_info.value.error_code == "AUTH_EMAIL_CODE_RATE_LIMITED"


def test_register_login_and_token_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_auth(monkeypatch)
    engine = _auth_engine()
    sent_codes: list[str] = []
    monkeypatch.setattr(sessions.secrets, "randbelow", lambda _limit: 654321)
    monkeypatch.setattr(
        sessions,
        "_send_email_verification_message",
        lambda *, to_email, code, ttl_seconds: sent_codes.append(code),
    )

    with Session(engine, expire_on_commit=False) as session:
        guest = sessions.create_guest_user(session, device_key="device-a")
        assert guest.is_registered is False
        assert sessions.create_guest_user(session, device_key="device-a").id == guest.id

        sessions.send_register_email_verification_code(session, email="learner@example.com")
        registration = sessions.register_user(
            session,
            current_user_id=guest.id,
            email="learner@example.com",
            password="strong-password",
            verification_code=sent_codes[-1],
            device_key="device-a",
        )

        assert registration.current_user is not None
        assert registration.current_user.user_id == guest.id
        assert registration.current_user.is_authenticated is True
        assert registration.access_token is None

        legacy_token = sessions.issue_access_token(user=session.get(User, guest.id))
        resolved = sessions.resolve_user_from_token(session, legacy_token)
        assert resolved is not None
        assert resolved.email == "learner@example.com"

        typeless_token = _issue_typeless_access_token(session.get(User, guest.id))
        assert sessions.resolve_user_from_token(session, typeless_token) is None
        assert sessions.resolve_user_from_legacy_bearer(session, typeless_token).id == guest.id

        login = sessions.login_user(
            session,
            email="LEARNER@example.com",
            password="strong-password",
            device_key="device-b",
        )
        assert login.current_user is not None
        assert login.current_user.device_key == "device-a"
        assert login.access_token is None

        with pytest.raises(AITeachMeError) as exc_info:
            sessions.login_user(session, email="learner@example.com", password="wrong", device_key=None)
        assert exc_info.value.error_code == "AUTH_INVALID_CREDENTIALS"

        guest_after_logout = sessions.build_logout_guest_user(session, device_key="device-b")
        assert guest_after_logout.is_registered is False
        guest_token = sessions.issue_guest_token(user_id=guest_after_logout.id)
        assert sessions.resolve_guest_user_from_token(session, guest_token).id == guest_after_logout.id
        assert sessions.resolve_guest_user_from_token(session, legacy_token) is None

        guest_session = sessions.build_guest_session_data(user=guest_after_logout)
        context_session = sessions.build_session_from_context(
            user_id="u-context",
            email=None,
            device_key="device-context",
            is_authenticated=False,
        )
        assert guest_session.current_user is not None
        assert guest_session.current_user.is_authenticated is False
        assert context_session.current_user is not None
        assert context_session.current_user.device_key == "device-context"


def test_guest_device_key_cannot_claim_existing_user() -> None:
    engine = _auth_engine()

    with Session(engine, expire_on_commit=False) as session:
        registered = User(
            id="usr_existing",
            username="existing",
            email="existing@example.com",
            device_key="device-claimed",
            is_registered=True,
        )
        session.add(registered)
        session.commit()

        guest = sessions.create_guest_user(session, device_key="device-claimed")

        assert guest.id != registered.id
        assert guest.is_registered is False
        assert guest.device_key is None


def test_email_code_consumption_attempt_limits_and_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_auth(monkeypatch)
    engine = _auth_engine()
    now = datetime.now(timezone.utc)

    with Session(engine, expire_on_commit=False) as session:
        old_expired = EmailConfirmation(
            email="old@example.com",
            purpose="register",
            code_hash="old",
            expires_at=now - timedelta(days=8),
        )
        old_consumed = EmailConfirmation(
            email="consumed@example.com",
            purpose="register",
            code_hash="consumed",
            expires_at=now + timedelta(days=1),
            consumed_at=now - timedelta(days=8),
        )
        recent = EmailConfirmation(
            email="recent@example.com",
            purpose="register",
            code_hash="recent",
            expires_at=now + timedelta(days=1),
        )
        session.add_all([old_expired, old_consumed, recent])
        session.commit()

        assert sessions.purge_expired_email_confirmations(session, now=now) == 2
        assert session.exec(select(EmailConfirmation)).one().email == "recent@example.com"

    engine = _auth_engine()
    with Session(engine, expire_on_commit=False) as session:
        expired = EmailConfirmation(
            email="expired@example.com",
            purpose="register",
            code_hash=sessions._hash_email_verification_code(email="expired@example.com", purpose="register", code="123456"),
            expires_at=now - timedelta(seconds=1),
        )
        session.add(expired)
        session.commit()

        with pytest.raises(AITeachMeError) as exc_info:
            sessions._consume_register_email_code(session, email="expired@example.com", verification_code="123456")
        assert exc_info.value.error_code == "AUTH_EMAIL_CODE_EXPIRED"
        assert session.get(EmailConfirmation, expired.id).consumed_at is not None

    engine = _auth_engine()
    with Session(engine, expire_on_commit=False) as session:
        pending = EmailConfirmation(
            email="attempts@example.com",
            purpose="register",
            code_hash=sessions._hash_email_verification_code(email="attempts@example.com", purpose="register", code="123456"),
            expires_at=now + timedelta(minutes=5),
        )
        session.add(pending)
        session.commit()

        with pytest.raises(AITeachMeError) as first_error:
            sessions._consume_register_email_code(session, email="attempts@example.com", verification_code="000000")
        assert first_error.value.error_code == "AUTH_INVALID_EMAIL_CODE"

        with pytest.raises(AITeachMeError) as second_error:
            sessions._consume_register_email_code(session, email="attempts@example.com", verification_code="000000")
        assert second_error.value.error_code == "AUTH_EMAIL_CODE_TOO_MANY_ATTEMPTS"
        assert session.get(EmailConfirmation, pending.id).consumed_at is not None


def test_smtp_readiness_rejects_unsafe_or_incomplete_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_auth(monkeypatch)

    values = {"SMTP_ADDRESS_FAMILY": "ipv4"}

    def env(name: str, default: str = "") -> str:
        return values.get(name, default)

    def env_bool(name: str, default: bool) -> bool:
        return bool(values.get(name, default))

    monkeypatch.setattr(sessions, "get_env", env)
    monkeypatch.setattr(sessions, "get_env_bool", env_bool)

    with pytest.raises(AITeachMeError) as missing:
        sessions._ensure_smtp_ready()
    assert missing.value.error_code == "AUTH_SMTP_NOT_CONFIGURED"

    values.update({"SMTP_HOST": "smtp.example.com", "SMTP_FROM_EMAIL": "noreply@example.com", "SMTP_USERNAME": "user"})
    with pytest.raises(AITeachMeError) as no_password:
        sessions._ensure_smtp_ready()
    assert no_password.value.error_code == "AUTH_SMTP_NOT_CONFIGURED"

    values.update({"SMTP_PASSWORD": "secret", "SMTP_USE_SSL": True, "SMTP_USE_STARTTLS": True})
    with pytest.raises(AITeachMeError) as conflict:
        sessions._ensure_smtp_ready()
    assert conflict.value.error_code == "AUTH_SMTP_NOT_CONFIGURED"

    values["SMTP_USE_STARTTLS"] = False
    sessions._ensure_smtp_ready()
