from __future__ import annotations

from fastapi import Response
from starlette.requests import Request

from app.api.deps import get_current_user_context
from app.repositories.user_repo import attach_device_key, create_user, get_user_by_id
from app.services.auth_service import (
    build_logout_guest_user,
    create_guest_user,
    issue_guest_token,
    resolve_guest_user_from_token,
)
from app.services.subject_service import create_subject_record, get_subject_record
from app.shared.infra.config import Settings


_DEVICE_KEY = "dk_guest_identity_0001"


def _build_request(*, device_key: str | None = None, guest_token: str | None = None) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if device_key is not None:
        headers.append((b"x-device-key", device_key.encode("utf-8")))
    if guest_token is not None:
        cookie_value = f"atm_guest_token={guest_token}"
        headers.append((b"cookie", cookie_value.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/v1/auth/user",
        "headers": headers,
    }
    return Request(scope)


def test_get_current_user_context_reuses_guest_identity_by_device_key(session) -> None:
    first = get_current_user_context(
        _build_request(device_key=_DEVICE_KEY),
        Response(),
        session,
    )
    second = get_current_user_context(
        _build_request(device_key=_DEVICE_KEY),
        Response(),
        session,
    )

    assert second.user_id == first.user_id
    assert second.device_key == _DEVICE_KEY


def test_guest_subject_round_trip_stays_visible_for_same_device_key(session) -> None:
    current = get_current_user_context(
        _build_request(device_key=_DEVICE_KEY),
        Response(),
        session,
    )
    created = create_subject_record(
        session,
        owner_user_id=current.user_id,
        name="高等数学",
    )

    revisited = get_current_user_context(
        _build_request(device_key=_DEVICE_KEY),
        Response(),
        session,
    )
    subject = get_subject_record(
        session,
        created.subject_id,
        owner_user_id=revisited.user_id,
    )

    assert subject.slug == created.subject_id
    assert subject.user_id == current.user_id


def test_registered_device_key_bootstraps_real_guest(session) -> None:
    registered = create_user(
        session,
        username="registered_owner",
        email="owner@example.com",
        device_key=_DEVICE_KEY,
        is_registered=True,
    )

    current = get_current_user_context(
        _build_request(device_key=_DEVICE_KEY),
        Response(),
        session,
    )

    session.refresh(registered)
    guest = get_user_by_id(session, current.user_id)

    assert current.user_id != registered.id
    assert guest is not None
    assert not guest.is_registered
    assert guest.device_key == _DEVICE_KEY
    assert registered.device_key is None


def test_guest_token_cannot_resolve_registered_user(session) -> None:
    registered = create_user(
        session,
        username="registered_token_owner",
        email="token-owner@example.com",
        is_registered=True,
    )
    token = issue_guest_token(user_id=registered.id)

    assert resolve_guest_user_from_token(session, token) is None


def test_stale_guest_cookie_yields_to_current_device_owner(session) -> None:
    original_guest = create_guest_user(session, device_key=_DEVICE_KEY)
    stale_token = issue_guest_token(user_id=original_guest.id)
    registered = create_user(
        session,
        username="registered_switch_owner",
        email="switch-owner@example.com",
        is_registered=True,
    )
    attach_device_key(session, user=registered, device_key=_DEVICE_KEY)

    current = get_current_user_context(
        _build_request(device_key=_DEVICE_KEY, guest_token=stale_token),
        Response(),
        session,
    )

    session.refresh(registered)

    assert current.user_id != original_guest.id
    assert current.auth_source == "guest_bootstrap"
    assert current.device_key == _DEVICE_KEY
    assert registered.device_key is None


def test_build_logout_guest_user_moves_device_key_to_guest(session) -> None:
    registered = create_user(
        session,
        username="logout_owner",
        email="logout-owner@example.com",
        device_key=_DEVICE_KEY,
        is_registered=True,
    )

    guest = build_logout_guest_user(session, device_key=_DEVICE_KEY)

    session.refresh(registered)

    assert guest.id != registered.id
    assert not guest.is_registered
    assert guest.device_key == _DEVICE_KEY
    assert registered.device_key is None


def test_cloud_guest_cookie_defaults_support_cross_site_requests() -> None:
    local_settings = Settings(app_mode="local", guest_cookie_secure=None, guest_cookie_samesite="auto")
    cloud_settings = Settings(app_mode="cloud", guest_cookie_secure=None, guest_cookie_samesite="auto")

    assert local_settings.resolved_guest_cookie_samesite == "lax"
    assert local_settings.resolved_guest_cookie_secure is False
    assert cloud_settings.resolved_guest_cookie_samesite == "none"
    assert cloud_settings.resolved_guest_cookie_secure is True


def test_auto_app_mode_defaults_to_cloud_on_render(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")

    settings = Settings()

    assert settings.resolved_app_mode == "cloud"
    assert settings.resolved_guest_cookie_samesite == "none"
    assert settings.resolved_guest_cookie_secure is True
