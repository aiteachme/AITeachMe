"""Authentication support workflows."""

from app.workflows.support.auth.identity import (
    build_guest_session_data,
    build_logout_guest_user,
    create_guest_user,
    decode_access_token,
    decode_legacy_access_token,
    decode_guest_token,
    ensure_auth_enabled,
    issue_access_token,
    issue_guest_token,
    resolve_guest_user_from_token,
    resolve_user_from_legacy_bearer,
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
from app.workflows.support.auth.session_store import (
    clear_auth_session_cookie,
    create_auth_session,
    get_session_cookie_name,
    resolve_auth_session,
    revoke_all_auth_sessions,
    revoke_auth_session,
    set_auth_session_cookie,
    validate_session_request,
)
from app.workflows.support.auth.merge import run_guest_merge_cleanup_loop
from app.workflows.support.auth.housekeeping import (
    cleanup_expired_auth_records_once,
    run_auth_housekeeping_loop,
)
from app.workflows.support.auth.smtp import send_register_email_verification_code

__all__ = [
    "build_auth_session_data",
    "build_guest_session_data",
    "build_logout_guest_user",
    "build_session_from_context",
    "create_guest_user",
    "cleanup_expired_auth_records_once",
    "clear_auth_session_cookie",
    "create_auth_session",
    "decode_access_token",
    "decode_legacy_access_token",
    "decode_guest_token",
    "ensure_auth_enabled",
    "hash_password",
    "issue_access_token",
    "issue_guest_token",
    "get_session_cookie_name",
    "login_user",
    "purge_expired_email_confirmations",
    "register_user",
    "resolve_guest_user_from_token",
    "resolve_user_from_legacy_bearer",
    "resolve_auth_session",
    "resolve_user_from_token",
    "run_guest_merge_cleanup_loop",
    "run_auth_housekeeping_loop",
    "send_register_email_verification_code",
    "set_guest_cookie",
    "set_guest_cookie_for_user",
    "set_auth_session_cookie",
    "revoke_auth_session",
    "revoke_all_auth_sessions",
    "validate_session_request",
    "verify_password",
]
