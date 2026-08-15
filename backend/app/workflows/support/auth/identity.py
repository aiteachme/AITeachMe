"""Identity and token helpers for support auth workflows."""

from app.workflows.support.auth.sessions import (
    build_guest_session_data,
    build_logout_guest_user,
    create_guest_user,
    decode_access_token,
    decode_guest_token,
    decode_legacy_access_token,
    ensure_auth_enabled,
    issue_access_token,
    issue_guest_token,
    resolve_guest_user_from_token,
    resolve_user_from_legacy_bearer,
    resolve_user_from_token,
    set_guest_cookie,
    set_guest_cookie_for_user,
)

__all__ = [
    "build_guest_session_data",
    "build_logout_guest_user",
    "create_guest_user",
    "decode_access_token",
    "decode_guest_token",
    "decode_legacy_access_token",
    "ensure_auth_enabled",
    "issue_access_token",
    "issue_guest_token",
    "resolve_guest_user_from_token",
    "resolve_user_from_legacy_bearer",
    "resolve_user_from_token",
    "set_guest_cookie",
    "set_guest_cookie_for_user",
]
