from __future__ import annotations

import asyncio

import pytest
from fastapi import Request, Response
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.api import auth as auth_api
from app.api import courses as courses_api
from app.api.deps import CurrentUserContext
from app.models import (
    AuthRateLimitBucket,
    AuthSession,
    Course,
    CreditAccount,
    CreditLedger,
    EmailConfirmation,
    User,
)
from app.schemas.auth import LoginRequest, LogoutRequest, RegisterRequest
from app.workflows.support.auth import sessions


def _engine(*tables):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=list(tables))
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


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth",
            "headers": [],
            "client": ("127.0.0.1", 1),
        }
    )


def test_auth_success_events_are_captured_without_sensitive_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_auth(monkeypatch)
    engine = _engine(
        User.__table__,
        EmailConfirmation.__table__,
        AuthSession.__table__,
        AuthRateLimitBucket.__table__,
        CreditAccount.__table__,
        CreditLedger.__table__,
    )
    captured: list[tuple[str, dict[str, object]]] = []
    sent_codes: list[str] = []

    monkeypatch.setattr(sessions.secrets, "randbelow", lambda _limit: 112233)
    monkeypatch.setattr(
        sessions,
        "_send_email_verification_message",
        lambda *, to_email, code, ttl_seconds: sent_codes.append(code),
    )
    monkeypatch.setattr(
        auth_api,
        "capture_product_event_later",
        lambda event, **kwargs: captured.append((event, kwargs)) or None,
    )

    with Session(engine, expire_on_commit=False) as session:
        guest = sessions.create_guest_user(session, device_key="device-auth-00000001")
        sessions.send_register_email_verification_code(session, email="learner@example.com")
        register_response = asyncio.run(
            auth_api.register(
                request=_request(),
                response=Response(),
                body=RegisterRequest(
                    email="learner@example.com",
                    password="strong-password",
                    verification_code=sent_codes[-1],
                ),
                user=CurrentUserContext(
                    user_id=guest.id,
                    email=None,
                    is_local=True,
                    device_key="device-auth-00000001",
                    is_authenticated=False,
                ),
                session=session,
            )
        )
        login_response = asyncio.run(
            auth_api.login(
                request=_request(),
                response=Response(),
                body=LoginRequest(email="learner@example.com", password="strong-password"),
                user=CurrentUserContext(
                    user_id=guest.id,
                    email=None,
                    is_local=True,
                    device_key="device-auth-00000002",
                    is_authenticated=False,
                ),
                session=session,
            )
        )
        asyncio.run(
            auth_api.logout(
                response=Response(),
                _=LogoutRequest(),
                user=CurrentUserContext(
                    user_id=guest.id,
                    email="learner@example.com",
                    is_local=True,
                    device_key="device-auth-00000002",
                    is_authenticated=True,
                ),
                session=session,
            )
        )

    assert register_response.data.current_user is not None
    assert login_response.data.current_user is not None
    assert [event for event, _kwargs in captured] == [
        "auth_register_succeeded",
        "auth_login_succeeded",
        "auth_logout_succeeded",
    ]
    for _event, kwargs in captured:
        properties = kwargs["properties"]
        assert isinstance(properties, dict)
        assert properties["account_domain"] == "example.com"
        assert "learner@example.com" not in str(properties)
        assert kwargs["device_key"].startswith("device-auth-")

    assert captured[-1][1]["properties"]["was_authenticated"] is True


def test_course_created_event_is_captured_after_draft_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = _engine(Course.__table__)
    captured: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        courses_api,
        "capture_product_event_later",
        lambda event, **kwargs: captured.append((event, kwargs)) or None,
    )

    with Session(engine, expire_on_commit=False) as session:
        response = asyncio.run(
            courses_api.create_course_draft_api(
                user=CurrentUserContext(
                    user_id="user-course-12345678",
                    email="owner@example.com",
                    is_local=True,
                    device_key="device-course-abcdef12",
                    is_authenticated=True,
                ),
                session=session,
            )
        )

    assert response.data.course_id
    assert captured[0][0] == "course_created"
    kwargs = captured[0][1]
    assert kwargs["user_id"] == "user-course-12345678"
    assert kwargs["course_id"] == response.data.course_id
    assert kwargs["is_authenticated"] is True
    assert kwargs["properties"] == {
        "course_creation_mode": "draft",
        "has_name": False,
        "has_description": False,
    }
