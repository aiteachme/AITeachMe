"""鉴权接口。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Response
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db
from app.api.openapi import build_error_responses
from app.schemas.auth import (
    AuthSessionData,
    LoginRequest,
    LogoutRequest,
    RegisterRequest,
    SendEmailCodeData,
    SendEmailCodeRequest,
)
from app.schemas.common import ApiResponse, ok_response
from app.services.auth_service import (
    build_session_from_context,
    login_user,
    register_user,
    send_register_email_verification_code,
    set_guest_cookie_for_user,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/email/send-code",
    response_model=ApiResponse[SendEmailCodeData],
    summary="发送注册邮箱验证码",
    description="向邮箱发送 6 位验证码，用于注册前校验。",
    responses=build_error_responses([400, 409, 422, 429, 500, 503]),
)
async def send_email_code(
    body: SendEmailCodeRequest = Body(...),
    _: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[SendEmailCodeData]:
    data = send_register_email_verification_code(
        session,
        email=body.email,
    )
    return ok_response(data)


@router.post(
    "/register",
    response_model=ApiResponse[AuthSessionData],
    summary="注册",
    description="基于 device_key 的匿名身份升级为邮箱账号。",
    responses=build_error_responses([400, 409, 422, 500, 503]),
)
async def register(
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
    if data.current_user is not None:
        set_guest_cookie_for_user(response, user_id=data.current_user.user_id)
    return ok_response(data)


@router.post(
    "/login",
    response_model=ApiResponse[AuthSessionData],
    summary="登录",
    description="邮箱密码登录，并绑定当前 device_key。",
    responses=build_error_responses([400, 401, 422, 500]),
)
async def login(
    response: Response,
    body: LoginRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[AuthSessionData]:
    data = login_user(
        session,
        email=body.email,
        password=body.password,
        device_key=user.device_key,
    )
    if data.current_user is not None:
        set_guest_cookie_for_user(response, user_id=data.current_user.user_id)
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
) -> ApiResponse[AuthSessionData]:
    # 无状态 token：服务端不保存会话，前端删除 token 即可。
    set_guest_cookie_for_user(response, user_id=user.user_id)
    return ok_response(
        build_session_from_context(
            user_id=user.user_id,
            email=None,
            device_key=user.device_key,
            is_authenticated=False,
        )
    )


@router.post(
    "/user",
    response_model=ApiResponse[AuthSessionData],
    summary="当前用户",
    description="读取当前 token/device_key 对应的用户会话信息。",
    responses=build_error_responses([401, 422, 500]),
)
async def user(
    response: Response,
    _: LogoutRequest = Body(default=LogoutRequest()),
    current: CurrentUserContext = Depends(get_current_user_context),
) -> ApiResponse[AuthSessionData]:
    set_guest_cookie_for_user(response, user_id=current.user_id)
    return ok_response(
        build_session_from_context(
            user_id=current.user_id,
            email=current.email,
            device_key=current.device_key,
            is_authenticated=current.is_authenticated,
        )
    )
