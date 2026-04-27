"""Authentication support workflows."""

from app.workflows.support.auth.identity import (
    build_guest_session_data,
    build_logout_guest_user,
    create_guest_user,
    decode_access_token,
    decode_guest_token,
    ensure_auth_enabled,
    issue_access_token,
    issue_guest_token,
    resolve_guest_user_from_token,
    resolve_user_from_token,
    set_guest_cookie,
    set_guest_cookie_for_user,
)
from app.workflows.support.auth.sessions import (
    build_auth_session_data,
    build_session_from_context,
    hash_password,
    login_user,
    purge_expired_email_confirmations,
    register_user,
    verify_password,
)
from app.workflows.support.auth.smtp import send_register_email_verification_code

__all__ = [
    "build_auth_session_data",
    "build_guest_session_data",
    "build_logout_guest_user",
    "build_session_from_context",
    "create_guest_user",
    "decode_access_token",
    "decode_guest_token",
    "ensure_auth_enabled",
    "hash_password",
    "issue_access_token",
    "issue_guest_token",
    "login_user",
    "purge_expired_email_confirmations",
    "register_user",
    "resolve_guest_user_from_token",
    "resolve_user_from_token",
    "send_register_email_verification_code",
    "set_guest_cookie",
    "set_guest_cookie_for_user",
    "verify_password",
]
