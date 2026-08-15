"""鉴权接口。"""

from __future__ import annotations

from time import perf_counter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import structlog
from fastapi import APIRouter, Body, Depends, Query, Request, Response
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
from sqlmodel import Session
from sqlmodel import select

from app.api.deps import (
    CurrentUserContext,
    get_current_user_context,
    get_db,
    require_authenticated_user,
)
from app.api.openapi import build_error_responses
from app.models import AuthIdentity, OAuthFlow, User, UserMergeJob
from app.schemas.auth import (
    AuthSessionData,
    AuthIdentityItem,
    LoginRequest,
    LogoutRequest,
    RegisterRequest,
    SendEmailCodeData,
    SendEmailCodeRequest,
    OAuthConfirmRequest,
    OAuthProviderItem,
    OAuthStartData,
    OAuthStartRequest,
)
from app.schemas.common import ApiResponse, ok_response
from app.shared.infra.analytics.posthog import capture_product_event_later
from app.workflows.support.auth import (
    build_logout_guest_user,
    build_session_from_context,
    clear_auth_session_cookie,
    create_auth_session,
    login_user,
    register_user,
    revoke_all_auth_sessions,
    revoke_auth_session,
    send_register_email_verification_code,
    set_auth_session_cookie,
    set_guest_cookie_for_user,
)
from app.workflows.support.auth.providers import (
    complete_oauth_flow,
    configured_providers,
    confirm_pending_oauth_identity,
    reject_oauth_flow,
    start_oauth_flow,
    unlink_identity,
)
from app.workflows.support.auth.merge import create_merge_offer, run_guest_merge
from app.workflows.support.auth.rate_limit import consume_auth_rate_limit
from app.workflows.support.credits import ensure_credit_account

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _redirect_with_query(return_to: str, **values: str) -> str:
    parts = urlsplit(return_to)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in values
    ]
    query.extend(values.items())
    return urlunsplit(("", "", parts.path or "/", urlencode(query), parts.fragment))


def _email_domain(email: str | None) -> str | None:
    normalized = str(email or "").strip().lower()
    if "@" not in normalized:
        return None
    return normalized.rsplit("@", 1)[-1] or None


def _capture_auth_event(
    event: str,
    *,
    data: AuthSessionData | None = None,
    user: CurrentUserContext | None = None,
    properties: dict[str, object] | None = None,
) -> None:
    current_user = data.current_user if data is not None else None
    user_id = current_user.user_id if current_user is not None else (user.user_id if user is not None else None)
    email = current_user.email if current_user is not None else (user.email if user is not None else None)
    device_key = current_user.device_key if current_user is not None else (user.device_key if user is not None else None)
    is_authenticated = (
        current_user.is_authenticated
        if current_user is not None
        else (user.is_authenticated if user is not None else None)
    )
    capture_product_event_later(
        event,
        user_id=user_id,
        device_key=device_key,
        email=email,
        is_authenticated=is_authenticated,
        insert_id_parts=[
            event,
            str(user_id or "unknown_user"),
            str(device_key or ""),
            str(perf_counter()),
        ],
        properties={
            "account_domain": _email_domain(email),
            **dict(properties or {}),
        },
    )


def _consume_password_rate_limits(
    session: Session,
    *,
    request: Request,
    email: str,
) -> None:
    consume_auth_rate_limit(
        session,
        scope="password_login_email",
        identity=email.strip().lower(),
        limit=10,
        window_seconds=900,
    )
    consume_auth_rate_limit(
        session,
        scope="password_login_ip",
        identity=request.client.host if request.client else "unknown",
        limit=60,
        window_seconds=900,
    )


@router.post(
    "/email/send-code",
    response_model=ApiResponse[SendEmailCodeData],
    summary="发送注册邮箱验证码",
    description="向邮箱发送 6 位验证码，用于注册前校验。",
    responses=build_error_responses([400, 409, 422, 429, 500, 503]),
)
async def send_email_code(
    request: Request,
    body: SendEmailCodeRequest = Body(...),
    _: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SendEmailCodeData]:
    started_at = perf_counter()
    email_domain = body.email.rsplit("@", 1)[-1].lower() if "@" in body.email else None
    logger.info("auth_send_email_code_started", email_domain=email_domain)

    success = False
    try:
        consume_auth_rate_limit(
            session,
            scope="email_code_email",
            identity=body.email.strip().lower(),
            limit=5,
            window_seconds=600,
        )
        consume_auth_rate_limit(
            session,
            scope="email_code_ip",
            identity=request.client.host if request.client else "unknown",
            limit=30,
            window_seconds=600,
        )
        data = await run_in_threadpool(
            send_register_email_verification_code,
            session,
            email=body.email,
        )
        success = True
        return ok_response(data)
    finally:
        logger.info(
            "auth_send_email_code_finished",
            success=success,
            elapsed_ms=int((perf_counter() - started_at) * 1000),
            email_domain=email_domain,
        )


@router.post(
    "/register",
    response_model=ApiResponse[AuthSessionData],
    summary="注册",
    description="基于 device_key 的匿名身份升级为邮箱账号。",
    responses=build_error_responses([400, 409, 422, 500, 503]),
)
async def register(
    request: Request,
    response: Response,
    body: RegisterRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[AuthSessionData]:
    data = register_user(
        session,
        current_user_id=user.user_id,
        email=body.email,
        password=body.password,
        verification_code=body.verification_code,
        device_key=user.device_key,
    )
    registered = session.get(User, data.current_user.user_id)
    if registered is None:
        raise RuntimeError("Registered user disappeared before session creation.")
    auth_session, raw_token = create_auth_session(
        session, user=registered, device_key=user.device_key, request=request,
    )
    set_auth_session_cookie(response, raw_token=raw_token)
    data.csrf_token = auth_session.csrf_token
    ensure_credit_account(session, user=registered)
    _capture_auth_event("auth_register_succeeded", data=data)
    return ok_response(data)


@router.post(
    "/login",
    response_model=ApiResponse[AuthSessionData],
    summary="登录",
    description="邮箱密码登录，并绑定当前 device_key。",
    responses=build_error_responses([400, 401, 422, 500]),
)
async def login(
    request: Request,
    response: Response,
    body: LoginRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[AuthSessionData]:
    _consume_password_rate_limits(session, request=request, email=body.email)
    data = login_user(
        session,
        email=body.email,
        password=body.password,
        device_key=user.device_key,
    )
    registered = session.get(User, data.current_user.user_id)
    if registered is None:
        raise RuntimeError("Authenticated user disappeared before session creation.")
    auth_session, raw_token = create_auth_session(
        session, user=registered, device_key=user.device_key, request=request,
    )
    set_auth_session_cookie(response, raw_token=raw_token)
    data.csrf_token = auth_session.csrf_token
    ensure_credit_account(session, user=registered)
    data.merge_offer = create_merge_offer(
        session,
        source_user_id=user.user_id,
        target_user_id=registered.id,
    )
    _capture_auth_event("auth_login_succeeded", data=data)
    return ok_response(data)


@router.post(
    "/logout",
    response_model=ApiResponse[AuthSessionData],
    summary="登出",
    description="清除登录态后回到 device_key 匿名身份。",
    responses=build_error_responses([422, 500]),
)
async def logout(
    response: Response,
    _: LogoutRequest = Body(default=LogoutRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[AuthSessionData]:
    if user.auth_session_id:
        revoke_auth_session(session, session_id=user.auth_session_id)
    clear_auth_session_cookie(response)
    guest = build_logout_guest_user(session, device_key=user.device_key)
    set_guest_cookie_for_user(response, user_id=guest.id)
    _capture_auth_event(
        "auth_logout_succeeded",
        user=user,
        properties={"was_authenticated": bool(user.is_authenticated)},
    )
    return ok_response(
        build_session_from_context(
            user_id=guest.id,
            email=None,
            device_key=guest.device_key,
            is_authenticated=False,
        )
    )


@router.post(
    "/logout-all",
    response_model=ApiResponse[dict[str, int]],
    summary="撤销全部登录会话",
    responses=build_error_responses([401, 403, 422, 500]),
)
async def logout_all(
    response: Response,
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[dict[str, int]]:
    if not user.is_authenticated:
        from app.shared.infra.exceptions import AITeachMeError
        raise AITeachMeError(detail="请先登录。", status_code=401, error_code="AUTH_REQUIRED")
    revoked = revoke_all_auth_sessions(session, user_id=user.user_id)
    clear_auth_session_cookie(response)
    return ok_response({"revoked_sessions": revoked})


@router.get(
    "/user",
    response_model=ApiResponse[AuthSessionData],
    summary="当前用户",
    description="读取当前 token/device_key 对应的用户会话信息。",
    responses=build_error_responses([401, 422, 500]),
)
async def user(
    response: Response,
    current: CurrentUserContext = Depends(get_current_user_context),
) -> ApiResponse[AuthSessionData]:
    if not current.is_authenticated:
        set_guest_cookie_for_user(response, user_id=current.user_id)
    return ok_response(
        build_session_from_context(
            user_id=current.user_id,
            email=current.email,
            device_key=current.device_key,
            is_authenticated=current.is_authenticated,
            role=current.role,
            display_name=current.display_name,
            avatar_url=current.avatar_url,
            csrf_token=current.csrf_token,
        )
    )


@router.get(
    "/providers",
    response_model=ApiResponse[list[OAuthProviderItem]],
    summary="可用第三方登录",
)
async def providers() -> ApiResponse[list[OAuthProviderItem]]:
    return ok_response([OAuthProviderItem.model_validate(item) for item in configured_providers()])


@router.post(
    "/oauth/{provider}/start",
    response_model=ApiResponse[OAuthStartData],
    responses=build_error_responses([401, 404, 422, 500]),
)
async def oauth_start(
    provider: str,
    request: Request,
    body: OAuthStartRequest = Body(default=OAuthStartRequest()),
    current: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[OAuthStartData]:
    consume_auth_rate_limit(
        session,
        scope="oauth_start",
        identity=f"{provider}:{request.client.host if request.client else ''}",
        limit=30,
        window_seconds=600,
    )
    initiating_user = session.get(User, current.user_id) if current.is_authenticated else None
    _, authorization_url = start_oauth_flow(
        session,
        provider=provider,
        mode=body.mode,
        return_to=body.return_to,
        initiating_user=initiating_user,
        source_guest_user_id=None if current.is_authenticated else current.user_id,
    )
    return ok_response(OAuthStartData(authorization_url=authorization_url, expires_in_s=600))


@router.get(
    "/oauth/{provider}/callback",
    response_model=None,
    responses=build_error_responses([400, 403, 404, 409, 500]),
)
async def oauth_callback(
    provider: str,
    request: Request,
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
    current: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
):
    authorization_code = (code or "").strip()
    if error or not authorization_code:
        flow = reject_oauth_flow(session, provider=provider, state=state)
        return RedirectResponse(
            _redirect_with_query(flow.return_to, oauth="denied"),
            status_code=303,
        )
    current_user = session.get(User, current.user_id) if current.is_authenticated else None
    completion = await complete_oauth_flow(
        session,
        provider=provider,
        state=state,
        code=authorization_code,
        current_user=current_user,
    )
    if completion.status == "confirmation_required":
        return RedirectResponse(
            _redirect_with_query(
                completion.flow.return_to,
                oauth="confirmation_required",
                flow_id=completion.flow.id,
            ),
            status_code=303,
        )
    if completion.user is None:
        raise RuntimeError("OAuth completion did not resolve a user.")
    auth_session, raw_token = create_auth_session(
        session,
        user=completion.user,
        device_key=current.device_key,
        request=request,
    )
    ensure_credit_account(session, user=completion.user)
    merge_offer = create_merge_offer(
        session,
        source_user_id=completion.flow.source_guest_user_id or "",
        target_user_id=completion.user.id,
    )
    redirect_query = {"oauth": completion.status}
    if merge_offer is not None:
        redirect_query["merge_job_id"] = str(merge_offer["job_id"])
    redirect = RedirectResponse(
        _redirect_with_query(completion.flow.return_to, **redirect_query),
        status_code=303,
    )
    set_auth_session_cookie(redirect, raw_token=raw_token)
    return redirect


@router.post(
    "/oauth/confirm",
    response_model=ApiResponse[AuthSessionData],
    responses=build_error_responses([400, 401, 409, 422, 500]),
)
async def oauth_confirm(
    request: Request,
    response: Response,
    body: OAuthConfirmRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[AuthSessionData]:
    _consume_password_rate_limits(session, request=request, email=body.email)
    flow = session.get(OAuthFlow, body.flow_id)
    authenticated = login_user(
        session,
        email=body.email,
        password=body.password,
        device_key=None,
    )
    target_user_id = authenticated.current_user.user_id if authenticated.current_user else ""
    target = session.get(User, target_user_id)
    if target is None:
        raise RuntimeError("Authenticated OAuth confirmation user disappeared.")
    target = confirm_pending_oauth_identity(session, flow_id=body.flow_id, user=target)
    auth_session, raw_token = create_auth_session(session, user=target, device_key=None, request=request)
    set_auth_session_cookie(response, raw_token=raw_token)
    data = build_session_from_context(
        user_id=target.id,
        email=target.email,
        device_key=target.device_key,
        is_authenticated=True,
        role=target.role,
        display_name=target.display_name,
        avatar_url=target.avatar_url,
        csrf_token=auth_session.csrf_token,
        merge_offer=create_merge_offer(
            session,
            source_user_id=flow.source_guest_user_id if flow is not None else "",
            target_user_id=target.id,
        ),
    )
    return ok_response(data)


@router.get(
    "/identities",
    response_model=ApiResponse[list[AuthIdentityItem]],
    responses=build_error_responses([401, 403, 500]),
)
async def list_identities(
    current: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[AuthIdentityItem]]:
    if not current.is_authenticated:
        from app.shared.infra.exceptions import AITeachMeError
        raise AITeachMeError(detail="请先登录。", status_code=401, error_code="AUTH_REQUIRED")
    rows = session.exec(select(AuthIdentity).where(AuthIdentity.user_id == current.user_id)).all()
    return ok_response([
        AuthIdentityItem(
            id=row.id,
            provider=row.provider,
            provider_email=row.provider_email,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ])


@router.delete(
    "/identities/{identity_id}",
    response_model=ApiResponse[dict[str, bool]],
    responses=build_error_responses([401, 403, 404, 409, 500]),
)
async def delete_identity(
    identity_id: str,
    current: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[dict[str, bool]]:
    user = session.get(User, current.user_id) if current.is_authenticated else None
    if user is None:
        from app.shared.infra.exceptions import AITeachMeError
        raise AITeachMeError(detail="请先登录。", status_code=401, error_code="AUTH_REQUIRED")
    unlink_identity(session, user=user, identity_id=identity_id)
    return ok_response({"unlinked": True})


@router.get(
    "/merge/{job_id}",
    response_model=ApiResponse[dict],
    responses=build_error_responses([401, 403, 404, 500]),
)
def get_guest_merge_offer(
    job_id: str,
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_db),
) -> ApiResponse[dict]:
    job = session.get(UserMergeJob, job_id)
    if job is None or job.target_user_id != user.id:
        from app.shared.infra.exceptions import AITeachMeError
        raise AITeachMeError(detail="游客迁移任务不存在。", status_code=404, error_code="AUTH_MERGE_NOT_FOUND")
    return ok_response(
        {
            "job_id": job.id,
            "counts": dict(job.asset_counts_json or {}),
            "status": job.status,
        }
    )


@router.post(
    "/merge/{job_id}/confirm",
    response_model=ApiResponse[dict],
    responses=build_error_responses([401, 403, 404, 409, 422, 500]),
)
def confirm_guest_merge(
    job_id: str,
    current: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[dict]:
    if not current.is_authenticated:
        from app.shared.infra.exceptions import AITeachMeError
        raise AITeachMeError(detail="请先登录。", status_code=401, error_code="AUTH_REQUIRED")
    job = run_guest_merge(session, job_id=job_id, target_user_id=current.user_id)
    return ok_response(
        {
            "job_id": job.id,
            "status": job.status,
            "course_mapping": dict(job.course_mapping_json or {}),
            "recovery_expires_at": job.recovery_expires_at.isoformat() if job.recovery_expires_at else None,
        }
    )
