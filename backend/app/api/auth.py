"""鉴权接口。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db
from app.api.openapi import build_error_responses
from app.schemas.auth import AuthSessionData, LoginRequest, LogoutRequest, RegisterRequest
from app.schemas.common import ApiResponse, ok_response
from app.services.auth_service import (
    build_session_from_context,
    login_user,
    register_user,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _require_device_key(user: CurrentUserContext) -> str:
    device_key = (user.device_key or "").strip()
    if not device_key:
        from app.core.exceptions import AITeachMeError

        raise AITeachMeError(
            detail="当前请求缺少 device_key，请刷新页面后重试。",
            status_code=400,
            error_code="DEVICE_KEY_REQUIRED",
        )
    return device_key


@router.post(
    "/register",
    response_model=ApiResponse[AuthSessionData],
    summary="注册",
    description="基于 device_key 的匿名身份升级为邮箱账号。",
    responses=build_error_responses([400, 409, 422, 500]),
)
async def register(
    body: RegisterRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[AuthSessionData]:
    data = register_user(
        session,
        email=body.email,
        password=body.password,
        device_key=_require_device_key(user),
    )
    return ok_response(data)


@router.post(
    "/login",
    response_model=ApiResponse[AuthSessionData],
    summary="登录",
    description="邮箱密码登录，并绑定当前 device_key。",
    responses=build_error_responses([400, 401, 422, 500]),
)
async def login(
    body: LoginRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[AuthSessionData]:
    data = login_user(
        session,
        email=body.email,
        password=body.password,
        device_key=_require_device_key(user),
    )
    return ok_response(data)


@router.post(
    "/logout",
    response_model=ApiResponse[AuthSessionData],
    summary="登出",
    description="清除登录态后回到 device_key 匿名身份。",
    responses=build_error_responses([422, 500]),
)
async def logout(
    _: LogoutRequest = Body(default=LogoutRequest()),
    user: CurrentUserContext = Depends(get_current_user_context),
) -> ApiResponse[AuthSessionData]:
    # 无状态 token：服务端不保存会话，前端删除 token 即可。
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
    _: LogoutRequest = Body(default=LogoutRequest()),
    current: CurrentUserContext = Depends(get_current_user_context),
) -> ApiResponse[AuthSessionData]:
    return ok_response(
        build_session_from_context(
            user_id=current.user_id,
            email=current.email,
            device_key=current.device_key,
            is_authenticated=current.is_authenticated,
        )
    )
